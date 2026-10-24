"""确定性工作流引擎。

流程：
  pending -> planning(COO) -> coding(Engineer) -> [机械门禁] -> reviewing(Reviewer)
          -> [fixing(Engineer) -> 机械门禁 -> reviewing] * max_fix_rounds
          -> marketing(Marketer) -> completed

审查是双层结构：
  第一层 Mechanical Gate（Playwright，确定性断言）
  第二层 AI Reviewer（读 PRD + 代码 + 门禁报告，输出 PASS / ITERATE）

裁决规则：
  - 机械门禁失败时，即使 AI 给出 PASS 也强制改为 ITERATE（forced_by_gate）。
  - 门禁通过后，以 AI 的 verdict 为准。
  - Reviewer 输出无法解析时，直接终止任务，不做无意义的修复循环。

约束：
- 状态迁移只经由 state_machine 校验后执行。
- Reviewer 不写代码，Marketer 不改游戏。
- 任一阶段异常都保留已写入的产物。
- 修复前把当前 index.html 快照进 history/，保证旧版本不丢。
"""

from __future__ import annotations

from collections.abc import Callable

from backend.core.vessel import (
    OutputParseError,
    OutputValidationError,
    Vessel,
    VesselError,
)
from backend.gate import GateUnavailableError, run_mechanical_gate
from backend.marketing import find_fabricated_claims, render_marketing
from backend.models.contract import TaskRecord, TaskStatus
from backend.models.events import AgentStatus, EventType, TraceEvent
from backend.schemas import (
    GameArtifact,
    GamePRD,
    GateCheck,
    Issue,
    MarketingKit,
    MechanicalReport,
    ReviewReport,
)
from backend.store import TaskStore
from backend.workflow.state_machine import assert_transition


class WorkflowError(RuntimeError):
    """工作流层面的错误基类。"""


class TaskAlreadyRunningError(WorkflowError):
    """同一 task_id 已在执行，拒绝并发启动。"""


class StageExecutionError(WorkflowError):
    """阶段执行的确定性检查失败（如产物不合法）。"""


def render_prd(prd: GamePRD) -> str:
    lines = [f"# {prd.title}", "", f"**类型**：{prd.genre}", "", "## 核心循环", ""]
    lines += [f"{i}. {step}" for i, step in enumerate(prd.core_loop, 1)]
    lines += ["", "## 功能", ""] + [f"- {item}" for item in prd.features]
    lines += ["", "## 操作", ""] + [f"- {item}" for item in prd.controls]
    lines += [
        "",
        f"**胜利条件**：{prd.win_condition}",
        f"**失败条件**：{prd.lose_condition}",
        "",
    ]
    return "\n".join(lines)


# 机械门禁检查项 -> 可对外宣传的功能描述
_VERIFIED_LABELS = {
    "game_area": "Canvas 画面渲染",
    "arrow_keys": "方向键操作",
    "score_updates": "实时计分",
    "restart_after_gameover": "结束后可重新开始",
}


def _feature_summary(report: MechanicalReport) -> tuple[list[str], list[str]]:
    """把门禁结果拆成"已验证可宣传"与"未验证不可宣传"两组。"""
    verified: list[str] = []
    for check in report.checks:
        label = _VERIFIED_LABELS.get(check.id)
        if label and check.status == "pass" and label not in verified:
            verified.append(label)
    unverified = [c.title for c in report.checks if c.status == "unverified"]
    return verified, unverified


def _gate_issue(check: GateCheck) -> Issue:
    return Issue(
        severity="high",
        description=f"机械门禁未通过：{check.title}（{check.detail}）",
        suggestion="修复后必须重新通过机械门禁与 AI 审查",
    )


class WorkflowEngine:
    def __init__(
        self,
        vessel: Vessel,
        store: TaskStore,
        *,
        max_fix_rounds: int = 2,
        on_event: Callable[[dict], None] | None = None,
    ) -> None:
        self._vessel = vessel
        self._store = store
        self._max_fix = max_fix_rounds
        self._on_event = on_event
        self._running: set[str] = set()
        # task_id -> 当前正在执行的员工，用于失败时标记 error 状态
        self._active_agent: dict[str, str] = {}

    @property
    def is_running(self) -> set[str]:
        return set(self._running)

    async def start(self, task_id: str) -> TaskRecord:
        """启动一个任务；同一 task_id 并发启动会被拒绝。"""
        if task_id in self._running:
            raise TaskAlreadyRunningError(f"任务已在执行：{task_id}")
        self._running.add(task_id)
        try:
            return await self._run(task_id)
        finally:
            self._running.discard(task_id)

    async def _run(self, task_id: str) -> TaskRecord:
        record = self._store.load(task_id)
        record.max_fix_rounds = self._max_fix

        try:
            # ---------- COO ----------
            self._transition(record, TaskStatus.PLANNING)
            self._agent(record, "coo", AgentStatus.WORKING, "正在制定游戏方案")
            prd: GamePRD = await self._call(record, "coo", record.requirement)
            self._agent(record, "coo", AgentStatus.COMPLETED, "游戏方案已完成")
            self._write(record, "prd.md", render_prd(prd))
            self._store.save(record)

            # ---------- Engineer + 机械门禁 ----------
            self._transition(record, TaskStatus.CODING)
            self._agent(record, "engineer", AgentStatus.WORKING, "正在编写游戏代码")
            game: GameArtifact = await self._call(
                record, "engineer", self._engineer_context(record.requirement, prd, None)
            )
            report = await self._apply_gate(record, game, prd)
            self._agent(record, "engineer", AgentStatus.COMPLETED, "游戏初版已生成")

            # ---------- 双层审查 + 修复循环 ----------
            self._transition(record, TaskStatus.REVIEWING)
            self._agent(record, "reviewer", AgentStatus.REVIEWING, "正在检查游戏质量")
            review = await self._review(record, prd, game, report)
            self._agent(
                record,
                "reviewer",
                AgentStatus.COMPLETED,
                "审查通过" if review.verdict == "PASS" else f"发现 {len(review.issues)} 个问题",
            )

            while review.verdict != "PASS":
                if record.fix_attempts >= record.max_fix_rounds:
                    record.error = (
                        f"审查连续未通过，已达到修复上限 {record.max_fix_rounds} 次"
                    )
                    self._transition(record, TaskStatus.NEEDS_ATTENTION)
                    self._store.save(record)
                    return record

                self._transition(record, TaskStatus.FIXING)
                self._agent(record, "engineer", AgentStatus.FIXING, "正在根据审查报告修复")
                snapshot = f"history/index.v{record.fix_attempts + 1}.html"
                self._store.snapshot(record, "index.html", snapshot)
                record.fix_attempts += 1
                self._emit(
                    record,
                    EventType.FIX_REQUESTED,
                    f"第 {record.fix_attempts} 次修复，旧版本已存入 {snapshot}",
                    agent="engineer",
                    status=AgentStatus.FIXING.value,
                    data={
                        "issues": [i.model_dump() for i in review.issues],
                        "gate_failed": report.failed_ids,
                        "snapshot": snapshot,
                    },
                )

                game = await self._call(
                    record,
                    "engineer",
                    self._engineer_context(record.requirement, prd, review),
                )
                report = await self._apply_gate(record, game, prd)
                self._agent(record, "engineer", AgentStatus.COMPLETED, "修复版本已生成")

                self._transition(record, TaskStatus.REVIEWING)
                self._agent(record, "reviewer", AgentStatus.REVIEWING, "正在复查修复版本")
                review = await self._review(record, prd, game, report)
                self._agent(
                    record,
                    "reviewer",
                    AgentStatus.COMPLETED,
                    "审查通过" if review.verdict == "PASS" else f"发现 {len(review.issues)} 个问题",
                )

            # ---------- Marketer ----------
            self._transition(record, TaskStatus.MARKETING)
            self._agent(record, "marketer", AgentStatus.WORKING, "正在生成推广方案")
            kit: MarketingKit = await self._call(
                record, "marketer", self._marketing_context(prd, game, review, report)
            )
            fabricated = find_fabricated_claims(kit)
            if fabricated:
                raise StageExecutionError(
                    "营销文案包含无法证实的数据表述：" + "、".join(dict.fromkeys(fabricated))
                )
            self._write(record, "marketing_kit.json", kit.model_dump_json(indent=2))
            self._write(record, "marketing_kit.md", render_marketing(kit))
            self._agent(record, "marketer", AgentStatus.COMPLETED, "推广方案已完成")

            self._transition(record, TaskStatus.COMPLETED)
            self._emit(
                record,
                EventType.TASK_COMPLETED,
                "任务完成，游戏与营销素材已就绪",
                status=TaskStatus.COMPLETED.value,
                data={"artifacts": sorted(record.artifacts)},
            )
            self._store.save(record)
            return record

        except (VesselError, StageExecutionError, GateUnavailableError) as exc:
            return self._fail(record, str(exc))

    # ---------- 内部方法 ----------

    async def _call(self, record: TaskRecord, talent_id: str, context: str):
        """执行一个员工，返回已通过契约校验的输出对象。"""
        result = await self._vessel.execute(
            talent_id, context, task_id=record.task_id
        )
        self._emit(
            record,
            EventType.AGENT_STATUS_CHANGED,
            f"{talent_id} 调用完成，耗时 {result.duration_ms}ms",
            agent=talent_id,
            status=None,
            data={
                "duration_ms": result.duration_ms,
                "tokens": result.input_tokens + result.output_tokens,
                "cost_usd": result.cost_usd,
            },
            save=False,
        )
        return result.output

    def _write(self, record: TaskRecord, filename: str, content: str) -> None:
        """写产物并广播 artifact.created，让前端知道有新文件。"""
        self._store.write_artifact(record, filename, content)
        self._emit(
            record,
            EventType.ARTIFACT_CREATED,
            f"生成 {filename}",
            data={"artifact": filename},
            save=False,
        )

    def _agent(
        self, record: TaskRecord, agent: str, status: AgentStatus, message: str
    ) -> None:
        """员工状态只由引擎写入，前端不做推断。"""
        if status in {AgentStatus.WORKING, AgentStatus.REVIEWING, AgentStatus.FIXING}:
            self._active_agent[record.task_id] = agent
        elif self._active_agent.get(record.task_id) == agent:
            self._active_agent.pop(record.task_id, None)
        self._emit(
            record,
            EventType.AGENT_STATUS_CHANGED,
            message,
            agent=agent,
            status=status.value,
        )

    def _emit(
        self,
        record: TaskRecord,
        event_type: EventType,
        message: str,
        *,
        agent: str | None = None,
        status: str | None = None,
        data: dict | None = None,
        save: bool = True,
    ) -> None:
        """记录事件、落盘并推送到 WebSocket 订阅者。"""
        event = TraceEvent(
            task_id=record.task_id,
            type=event_type,
            message=message,
            agent=agent,
            status=status,
            stage=record.status.value,
            data=data or {},
        )
        record.events.append(event)
        if save:
            self._store.save(record)
        if self._on_event is not None:
            self._on_event(event.as_message())

    async def _apply_gate(
        self, record: TaskRecord, game: GameArtifact, prd: GamePRD
    ) -> MechanicalReport:
        """落盘游戏代码并执行机械门禁，报告写入 gate.json。"""
        self._write(record, "index.html", game.html)
        report = await run_mechanical_gate(game.html, prd)
        self._store.write_artifact(record, "gate.json", report.model_dump_json(indent=2))
        self._emit(
            record,
            EventType.ARTIFACT_CREATED,
            f"机械门禁{'通过' if report.passed else '未通过'}："
            f"{len(report.checks)} 项检查，失败 {len(report.failed_ids)} 项",
            status=AgentStatus.REVIEWING.value,
            data={
                "artifact": "gate.json",
                "passed": report.passed,
                "failed": report.failed_ids,
                "unverified": report.unverified_ids,
            },
            save=False,
        )
        # 每轮门禁报告都留档，拒绝原因可追溯
        self._store.snapshot(
            record, "gate.json", f"history/gate.v{record.fix_attempts + 1}.json"
        )
        self._store.save(record)
        return report

    async def _review(
        self,
        record: TaskRecord,
        prd: GamePRD,
        game: GameArtifact,
        report: MechanicalReport,
    ) -> ReviewReport:
        attempt = record.fix_attempts + 1
        context = (
            f"PRD：\n{prd.model_dump_json(indent=2)}\n\n"
            f"机械门禁报告：\n{report.model_dump_json(indent=2)}\n\n"
            f"游戏代码 index.html：\n{game.html}\n\n"
            f"审查轮次: {attempt}"
        )
        try:
            review: ReviewReport = await self._call(record, "reviewer", context)
        except (OutputParseError, OutputValidationError) as exc:
            # 明确的失败策略：无法解析审查结果时不进入修复循环
            raise StageExecutionError(
                f"Reviewer 输出无法解析，按策略终止任务：{exc}"
            ) from exc

        gate_issues = [_gate_issue(c) for c in report.checks if c.status == "fail"]
        updates: dict = {}
        if gate_issues:
            updates["issues"] = review.issues + gate_issues
        if not report.passed and review.verdict == "PASS":
            updates["verdict"] = "ITERATE"
            updates["forced_by_gate"] = True
            updates["summary"] = "机械门禁未通过，禁止判定 PASS。" + review.summary
        if updates:
            review = review.model_copy(update=updates)

        # Reviewer 只写审查结果，绝不回写 index.html
        self._write(record, "review.json", review.model_dump_json(indent=2))
        self._emit(
            record,
            EventType.REVIEW_COMPLETED,
            f"第 {attempt} 次审查：{review.verdict}（{len(review.issues)} 个问题）",
            agent="reviewer",
            status=AgentStatus.REVIEWING.value,
            data={
                "verdict": review.verdict,
                "issues": [i.model_dump() for i in review.issues],
                "suggestions": review.suggestions,
                "forced_by_gate": review.forced_by_gate,
                "gate_failed": report.failed_ids,
                "gate_unverified": report.unverified_ids,
                "attempt": attempt,
            },
            save=False,
        )
        if review.verdict != "PASS":
            self._emit(
                record,
                EventType.FIX_REQUESTED,
                f"第 {attempt} 次审查未通过：{review.summary}",
                agent="reviewer",
                status=AgentStatus.REVIEWING.value,
                data={
                    "gate_failed": report.failed_ids,
                    "gate_unverified": report.unverified_ids,
                },
            )
        self._store.save(record)
        return review

    @staticmethod
    def _engineer_context(
        requirement: str, prd: GamePRD, review: ReviewReport | None
    ) -> str:
        context = f"需求：{requirement}\n\nPRD：\n{prd.model_dump_json(indent=2)}"
        if review is not None:
            issues = "\n".join(
                f"- [{issue.severity}] {issue.description} -> {issue.suggestion}"
                for issue in review.issues
            )
            suggestions = "\n".join(f"- {s}" for s in review.suggestions)
            context += (
                f"\n\n审查意见：\n{issues}"
                f"\n\n修改建议：\n{suggestions or '（无）'}"
                "\n\n请修复后输出完整游戏。"
            )
        return context

    @staticmethod
    def _marketing_context(
        prd: GamePRD,
        game: GameArtifact,
        review: ReviewReport,
        report: MechanicalReport,
    ) -> str:
        verified, unverified = _feature_summary(report)
        return (
            f"PRD：\n{prd.model_dump_json(indent=2)}\n\n"
            f"游戏文件：{game.filename}\n\n"
            f"审查结论：{review.verdict} - {review.summary}\n\n"
            "机械门禁已验证的功能（只能宣传这些）：\n"
            + "\n".join(f"- {item}" for item in verified or ["（无）"])
            + "\n\n未经自动验证、不得宣传的项：\n"
            + "\n".join(f"- {item}" for item in unverified or ["（无）"])
            + "\n\n注意：不得编造用户数、下载量、评分等任何数据；不得声称已发布到任何平台。"
        )

    def _transition(self, record: TaskRecord, target: TaskStatus) -> None:
        assert_transition(record.status, target)
        previous = record.status
        record.status = target
        self._emit(
            record,
            EventType.TASK_STATUS_CHANGED,
            f"{previous.value} -> {target.value}",
            status=target.value,
            data={"from": previous.value, "to": target.value},
        )

    def _fail(self, record: TaskRecord, message: str) -> TaskRecord:
        record.error = message
        agent = self._active_agent.pop(record.task_id, None)
        if agent is not None:
            self._emit(
                record,
                EventType.AGENT_STATUS_CHANGED,
                f"执行失败：{message}",
                agent=agent,
                status=AgentStatus.ERROR.value,
                save=False,
            )
        assert_transition(record.status, TaskStatus.FAILED)
        previous = record.status
        record.status = TaskStatus.FAILED
        self._emit(
            record,
            EventType.TASK_FAILED,
            f"{previous.value} -> failed：{message}",
            status=TaskStatus.FAILED.value,
            data={"from": previous.value, "to": "failed", "error": message},
        )
        return record
