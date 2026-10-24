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

from backend.core.vessel import (
    OutputParseError,
    OutputValidationError,
    Vessel,
    VesselError,
)
from backend.gate import GateUnavailableError, run_mechanical_gate
from backend.models.contract import TaskRecord, TaskStatus
from backend.models.events import EventType, TraceEvent
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
    lines += ["", f"**胜利条件**：{prd.win_condition}", f"**失败条件**：{prd.lose_condition}", ""]
    return "\n".join(lines)


def render_marketing(kit: MarketingKit) -> str:
    lines = [
        "# 营销素材",
        "",
        f"**一句话卖点**：{kit.tagline}",
        "",
        "## 介绍",
        "",
        kit.description,
        "",
        "## 话题标签",
        "",
        " ".join(kit.hashtags),
        "",
        "## 投放渠道",
        "",
    ]
    lines += [f"- {channel}" for channel in kit.channels]
    lines.append("")
    return "\n".join(lines)


def _gate_issue(check: GateCheck) -> Issue:
    return Issue(
        severity="high",
        description=f"机械门禁未通过：{check.title}（{check.detail}）",
        suggestion="修复后必须重新通过机械门禁与 AI 审查",
    )


class WorkflowEngine:
    def __init__(
        self, vessel: Vessel, store: TaskStore, *, max_fix_rounds: int = 2
    ) -> None:
        self._vessel = vessel
        self._store = store
        self._max_fix = max_fix_rounds
        self._running: set[str] = set()

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
            prd: GamePRD = await self._call(record, "coo", record.requirement)
            self._store.write_artifact(record, "prd.md", render_prd(prd))
            self._store.save(record)

            # ---------- Engineer + 机械门禁 ----------
            self._transition(record, TaskStatus.CODING)
            game: GameArtifact = await self._call(
                record, "engineer", self._engineer_context(record.requirement, prd, None)
            )
            report = await self._apply_gate(record, game, prd)

            # ---------- 双层审查 + 修复循环 ----------
            self._transition(record, TaskStatus.REVIEWING)
            review = await self._review(record, prd, game, report)

            while review.verdict != "PASS":
                if record.fix_attempts >= record.max_fix_rounds:
                    record.error = (
                        f"审查连续未通过，已达到修复上限 {record.max_fix_rounds} 次"
                    )
                    self._transition(record, TaskStatus.NEEDS_ATTENTION)
                    self._store.save(record)
                    return record

                self._transition(record, TaskStatus.FIXING)
                snapshot = f"history/index.v{record.fix_attempts + 1}.html"
                self._store.snapshot(record, "index.html", snapshot)
                record.fix_attempts += 1
                record.events.append(
                    TraceEvent(
                        task_id=record.task_id,
                        type=EventType.FIX_REQUESTED,
                        stage=TaskStatus.FIXING.value,
                        message=f"第 {record.fix_attempts} 次修复，旧版本已存入 {snapshot}",
                        data={
                            "issues": [i.model_dump() for i in review.issues],
                            "gate_failed": report.failed_ids,
                        },
                    )
                )
                self._store.save(record)

                game = await self._call(
                    record,
                    "engineer",
                    self._engineer_context(record.requirement, prd, review),
                )
                report = await self._apply_gate(record, game, prd)

                self._transition(record, TaskStatus.REVIEWING)
                review = await self._review(record, prd, game, report)

            # ---------- Marketer ----------
            self._transition(record, TaskStatus.MARKETING)
            kit: MarketingKit = await self._call(
                record, "marketer", self._marketing_context(prd, game, review)
            )
            self._store.write_artifact(
                record, "marketing_kit.md", render_marketing(kit)
            )

            self._transition(record, TaskStatus.COMPLETED)
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
        return result.output

    async def _apply_gate(
        self, record: TaskRecord, game: GameArtifact, prd: GamePRD
    ) -> MechanicalReport:
        """落盘游戏代码并执行机械门禁，报告写入 gate.json。"""
        self._store.write_artifact(record, "index.html", game.html)
        report = await run_mechanical_gate(game.html, prd)
        self._store.write_artifact(
            record, "gate.json", report.model_dump_json(indent=2)
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
        self._store.write_artifact(
            record, "review.json", review.model_dump_json(indent=2)
        )
        if review.verdict != "PASS":
            record.events.append(
                TraceEvent(
                    task_id=record.task_id,
                    type=EventType.STAGE_FAILED,
                    stage=TaskStatus.REVIEWING.value,
                    message=f"第 {attempt} 次审查未通过：{review.summary}",
                    data={
                        "gate_failed": report.failed_ids,
                        "gate_unverified": report.unverified_ids,
                        "forced_by_gate": review.forced_by_gate,
                    },
                )
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
        prd: GamePRD, game: GameArtifact, review: ReviewReport
    ) -> str:
        return (
            f"PRD：\n{prd.model_dump_json(indent=2)}\n\n"
            f"游戏文件：{game.filename}\n"
            f"审查结论：{review.verdict} - {review.summary}\n"
        )

    def _transition(self, record: TaskRecord, target: TaskStatus) -> None:
        assert_transition(record.status, target)
        previous = record.status
        record.status = target
        record.events.append(
            TraceEvent(
                task_id=record.task_id,
                type=EventType.STATE_CHANGED,
                stage=target.value,
                message=f"{previous.value} -> {target.value}",
                data={"from": previous.value, "to": target.value},
            )
        )
        self._store.save(record)

    def _fail(self, record: TaskRecord, message: str) -> TaskRecord:
        record.error = message
        assert_transition(record.status, TaskStatus.FAILED)
        previous = record.status
        record.status = TaskStatus.FAILED
        record.events.append(
            TraceEvent(
                task_id=record.task_id,
                type=EventType.TASK_FAILED,
                stage=TaskStatus.FAILED.value,
                message=f"{previous.value} -> failed：{message}",
                data={"from": previous.value, "to": "failed"},
            )
        )
        self._store.save(record)
        return record
