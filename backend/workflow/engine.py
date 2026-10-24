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

约束（Mini-6 Harness 挂载点）：
- 状态迁移只经由 state_machine 校验后执行；每名员工只能调用自己授权的工具。
- 预算检查在 Vessel 内完成，这里只负责把预算快照与事件落盘。
- 任一阶段异常都保留已写入的产物；取消同样不删除任何文件。
- 修复前把当前 index.html 快照进 history/，保证旧版本不丢。
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone

from backend.budget import BudgetGuard
from backend.core.vessel import (
    AgentResult,
    OutputParseError,
    OutputValidationError,
    Vessel,
    VesselError,
)
from backend.gate import GateUnavailableError, run_mechanical_gate
from backend.marketing import find_fabricated_claims, render_marketing
from backend.models.contract import TaskRecord, TaskStatus
from backend.models.events import AgentStatus, EventType, TokenUsage, TraceEvent
from backend.models.sop import SOPMode
from backend.models.version import GameVersion
from backend.schemas import (
    CreativeProposal,
    DeliveryAssessment,
    GameArtifact,
    GamePRD,
    GateCheck,
    Issue,
    MarketingKit,
    MechanicalReport,
    ReviewReport,
)
from backend.store import TaskStore
from backend.tools import DEFAULT_REGISTRY, ToolPolicyError, ToolRegistry
from backend.workflow.sop import select_sop
from backend.workflow.state_machine import assert_transition


class WorkflowError(RuntimeError):
    """工作流层面的错误基类。"""


class TaskAlreadyRunningError(WorkflowError):
    """同一 task_id 已在执行，拒绝并发启动。"""


class TaskNotRunnableError(WorkflowError):
    """任务已处于终态，不能再次执行或取消。"""


class TaskCancelledError(WorkflowError):
    """任务收到取消请求，引擎在安全点退出。"""


class StageExecutionError(WorkflowError):
    """阶段执行的确定性检查失败（如产物不合法）。"""


@dataclass
class _ConflictOutcome:
    """Conflict Gate 的真实结果，用于后续 COO 决策与事件记录。"""

    creative: CreativeProposal | None = None
    delivery: DeliveryAssessment | None = None
    revision_rounds: int = 0
    parallel_wall_ms: int = 0


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
        stage_min_seconds: float = 0.0,
        tools: ToolRegistry = DEFAULT_REGISTRY,
        budget: BudgetGuard | None = None,
        opinion_max_output_tokens: int = 600,
    ) -> None:
        self._vessel = vessel
        self._store = store
        self._max_fix = max_fix_rounds
        self._on_event = on_event
        self._stage_min = max(0.0, stage_min_seconds)
        self._tools = tools
        self._budget_guard = budget
        self._opinion_max_tokens = max(1, opinion_max_output_tokens)
        self._running: set[str] = set()
        self._cancel_requested: set[str] = set()
        self._cancel_times: dict[str, datetime] = {}
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
        started = time.perf_counter()
        try:
            record = await self._run(task_id)
            # 真实墙钟耗时；失败与取消同样记录，便于比较不同 SOP 的实际成本
            record.metrics.elapsed_ms = int((time.perf_counter() - started) * 1000)
            self._store.save(record)
            return record
        finally:
            self._running.discard(task_id)
            self._cancel_requested.discard(task_id)
            self._cancel_times.pop(task_id, None)

    def cancel(self, task_id: str) -> TaskRecord:
        """请求取消任务。

        - 终态任务拒绝取消（TaskNotRunnableError）。
        - 正在执行：只登记标记，后台循环在下一个安全点退出，已生成产物全部保留。
        - 尚未开始（如 pending）：直接把状态迁移到 cancelled。
        """
        record = self._store.load(task_id)
        if record.is_terminal:
            raise TaskNotRunnableError(
                f"任务已是终态 {record.status.value}，不能取消"
            )

        cancelled_at = datetime.now(timezone.utc)

        if task_id in self._running:
            self._cancel_requested.add(task_id)
            self._cancel_times[task_id] = cancelled_at
            record.cancel_requested_at = cancelled_at
            self._store.save(record)
            return record

        record.cancel_requested_at = cancelled_at
        self._transition(record, TaskStatus.CANCELLED)
        self._emit(
            record,
            EventType.TASK_CANCELLED,
            "任务已取消（尚未开始执行）",
            status=TaskStatus.CANCELLED.value,
            result="skipped",
            data={"artifacts": sorted(record.artifacts)},
        )
        return record

    async def _run(self, task_id: str) -> TaskRecord:
        record = self._store.load(task_id)
        if record.status is TaskStatus.CANCELLED:
            return record
        if record.is_terminal:
            raise TaskNotRunnableError(
                f"任务已是终态 {record.status.value}，不能再次执行"
            )
        record.max_fix_rounds = self._max_fix
        if self._budget_guard is not None:
            record.budget = self._budget_guard.register(task_id)

        # 阶段 9：确定 SOP。手动选择优先；自动选择必须把原因写入任务与事件。
        requested = record.sop_mode
        mode, reason = select_sop(
            record.requirement,
            requested,
            source_version_id=record.source_version_id,
        )
        record.sop_mode = mode
        record.sop_reason = reason
        record.conflict_decision = None
        record.creative_talent_version = None
        record.delivery_talent_version = None
        self._emit(
            record,
            EventType.SOP_SELECTED,
            f"SOP：{mode.value.upper()}（{reason}）",
            data={
                "mode": mode.value,
                "reason": reason,
                "manual": requested is not None,
                "source_version_id": record.source_version_id,
            },
        )

        try:
            # ---------- Conflict Gate + COO ----------
            self._transition(record, TaskStatus.PLANNING)
            self._check_cancel(record)
            conflict = await self._conflict_stage(record)
            record.creative_talent_version = record.talent_versions.get("creative")
            record.delivery_talent_version = record.talent_versions.get("delivery")
            self._check_cancel(record)

            has_opinions = conflict.creative is not None or conflict.delivery is not None
            self._agent(
                record,
                "coo",
                AgentStatus.WORKING,
                "正在汇总双方意见并制定方案" if has_opinions else "正在制定游戏方案",
            )
            self._use_tool(record, "coo", "read_requirement")
            prd: GamePRD = await self._call(
                record, "coo", self._coo_context(record, conflict)
            )
            self._check_cancel(record)
            self._agent(record, "coo", AgentStatus.COMPLETED, "游戏方案已完成")
            self._use_tool(record, "coo", "write_prd")
            self._write(record, "prd.md", render_prd(prd))

            if has_opinions and prd.conflict_decision is None:
                raise StageExecutionError(
                    "COO 收到创意与交付意见，但没有输出 conflict_decision"
                )
            record.conflict_decision = prd.conflict_decision
            if prd.conflict_decision is not None:
                self._use_tool(record, "coo", "write_decision")
                self._write(
                    record,
                    "conflict_decision.json",
                    prd.conflict_decision.model_dump_json(indent=2),
                )
                self._emit(
                    record,
                    EventType.CONFLICT_RESOLVED,
                    "COO 裁决："
                    f"{prd.conflict_decision.decision}（{prd.conflict_decision.rationale}）",
                    agent="coo",
                    result="ok",
                    data={
                        "decision": prd.conflict_decision.model_dump(),
                        "sop_mode": mode.value,
                        "revision_rounds": conflict.revision_rounds,
                        "parallel_wall_ms": conflict.parallel_wall_ms,
                        "creative_talent_version": record.creative_talent_version,
                        "delivery_talent_version": record.delivery_talent_version,
                    },
                )
            self._store.save(record)

            # ---------- Engineer + 机械门禁 ----------
            self._transition(record, TaskStatus.CODING)
            self._check_cancel(record)
            self._agent(record, "engineer", AgentStatus.WORKING, "正在编写游戏代码")
            self._use_tool(record, "engineer", "read_prd")
            game: GameArtifact = await self._call(
                record,
                "engineer",
                self._engineer_context(
                    record.requirement, prd, None, self._store.source_game_html(record)
                ),
            )
            self._check_cancel(record)
            report = await self._apply_gate(record, game, prd)
            self._agent(record, "engineer", AgentStatus.COMPLETED, "游戏初版已生成")

            # ---------- 双层审查 + 修复循环 ----------
            self._transition(record, TaskStatus.REVIEWING)
            self._check_cancel(record)
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
                self._check_cancel(record)
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

                self._use_tool(record, "engineer", "read_review")
                game = await self._call(
                    record,
                    "engineer",
                    self._engineer_context(record.requirement, prd, review),
                )
                self._check_cancel(record)
                report = await self._apply_gate(record, game, prd)
                self._agent(record, "engineer", AgentStatus.COMPLETED, "修复版本已生成")

                self._transition(record, TaskStatus.REVIEWING)
                self._check_cancel(record)
                self._agent(record, "reviewer", AgentStatus.REVIEWING, "正在复查修复版本")
                review = await self._review(record, prd, game, report)
                self._agent(
                    record,
                    "reviewer",
                    AgentStatus.COMPLETED,
                    "审查通过" if review.verdict == "PASS" else f"发现 {len(review.issues)} 个问题",
                )

            # ---------- FAST：不调用 Marketer，直接交付 ----------
            if mode is SOPMode.FAST:
                self._finalize_version(record, mode)
                self._transition(record, TaskStatus.COMPLETED)
                self._emit(
                    record,
                    EventType.TASK_COMPLETED,
                    "任务完成（FAST）：游戏已交付，无营销阶段",
                    status=TaskStatus.COMPLETED.value,
                    result="ok",
                    data={
                        "artifacts": sorted(record.artifacts),
                        "sop_mode": mode.value,
                        "version_id": record.final_version_id,
                        "model_calls": record.metrics.model_calls,
                    },
                )
                self._store.save(record)
                return record

            # ---------- Marketer ----------
            self._transition(record, TaskStatus.MARKETING)
            self._check_cancel(record)
            self._agent(record, "marketer", AgentStatus.WORKING, "正在生成推广方案")
            self._use_tool(record, "marketer", "read_prd")
            self._use_tool(record, "marketer", "read_review")
            kit: MarketingKit = await self._call(
                record, "marketer", self._marketing_context(prd, game, review, report)
            )
            self._check_cancel(record)
            fabricated = find_fabricated_claims(kit)
            if fabricated:
                raise StageExecutionError(
                    "营销文案包含无法证实的数据表述：" + "、".join(dict.fromkeys(fabricated))
                )
            self._use_tool(record, "marketer", "write_marketing")
            self._write(record, "marketing_kit.json", kit.model_dump_json(indent=2))
            self._write(record, "marketing_kit.md", render_marketing(kit))
            self._agent(record, "marketer", AgentStatus.COMPLETED, "推广方案已完成")

            self._finalize_version(record, mode)
            self._transition(record, TaskStatus.COMPLETED)
            self._emit(
                record,
                EventType.TASK_COMPLETED,
                "任务完成，游戏与营销素材已就绪",
                status=TaskStatus.COMPLETED.value,
                result="ok",
                data={
                    "artifacts": sorted(record.artifacts),
                    "sop_mode": mode.value,
                    "version_id": record.final_version_id,
                    "model_calls": record.metrics.model_calls,
                },
            )
            self._store.save(record)
            return record

        except TaskCancelledError as exc:
            return self._cancelled(record, str(exc))
        except (
            VesselError,
            StageExecutionError,
            GateUnavailableError,
            ToolPolicyError,
        ) as exc:
            return self._fail(record, str(exc))

    # ---------- 内部方法 ----------

    async def _execute(
        self,
        record: TaskRecord,
        talent_id: str,
        context: str,
        *,
        max_output_tokens: int | None = None,
    ) -> AgentResult:
        """只执行模型调用，不写 record。

        冲突阶段的并行调用使用它，避免两个协程同时修改 task.json；
        调用结果由调用方串行提交。
        """
        record.metrics.model_calls += 1
        return await self._vessel.execute(
            talent_id,
            context,
            task_id=record.task_id,
            max_output_tokens=max_output_tokens,
        )

    def _commit_result(
        self, record: TaskRecord, talent_id: str, result: AgentResult
    ) -> None:
        """串行提交一次调用的用量、Talent 版本与事件。"""
        usage = TokenUsage.of(
            result.input_tokens, result.output_tokens, result.usage_source
        )
        if self._budget_guard is not None:
            record.budget = self._budget_guard.snapshot(record.task_id)

        # 阶段 8：记录本次 Run 实际使用的 Talent 版本，便于回溯与回滚后核对
        if result.talent_version:
            record.talent_versions[talent_id] = result.talent_version
            self._store.save(record)

        model_note = result.model or "unknown"
        self._emit(
            record,
            EventType.AGENT_STATUS_CHANGED,
            f"{talent_id} 调用完成：{model_note} · {usage.total_tokens} tokens · "
            f"{result.duration_ms}ms"
            f"{'（已降级轻量模型）' if result.downgraded else ''}",
            agent=talent_id,
            status=None,
            model=result.model,
            duration_ms=result.duration_ms,
            token_usage=usage,
            result="ok",
            data={
                "cost_usd": result.cost_usd,
                "cost_status": result.cost_status,
                "downgraded": result.downgraded,
                "talent_version": result.talent_version,
            },
            save=False,
        )
        if self._budget_guard is not None and record.budget is not None:
            self._emit(
                record,
                EventType.BUDGET_UPDATED,
                f"任务预算：估算 ${record.budget.spent_usd:.4f} / "
                f"${record.budget.budget_usd:.4f}（{record.budget.ratio:.0%}）",
                agent=talent_id,
                result="ok",
                model=result.model,
                data={
                    "spent_usd": record.budget.spent_usd,
                    "budget_usd": record.budget.budget_usd,
                    "ratio": record.budget.ratio,
                    "calls": record.budget.calls,
                    "downgraded": result.downgraded,
                    "unknown_usage_calls": record.budget.unknown_usage_calls,
                    "cost_status": record.budget.cost_status,
                },
            )

    async def _call(
        self,
        record: TaskRecord,
        talent_id: str,
        context: str,
        *,
        max_output_tokens: int | None = None,
    ):
        """执行一个员工，返回已通过契约校验的输出对象。

        stage_min_seconds > 0 时，会等待到本阶段至少持续该时长再返回，
        让驾驶舱能完整播放该员工的动画；等待期间员工状态保持 working/reviewing。
        """
        started = time.perf_counter()
        try:
            result = await self._execute(
                record, talent_id, context, max_output_tokens=max_output_tokens
            )
        except VesselError as exc:
            self._emit(
                record,
                EventType.AGENT_STATUS_CHANGED,
                f"{talent_id} 执行失败：{exc}",
                agent=talent_id,
                status=None,
                result="failed",
                error=str(exc),
            )
            raise

        self._commit_result(record, talent_id, result)
        self._check_cancel(record)
        await self._wait_stage(started)
        return result.output

    async def _wait_stage(self, started: float) -> None:
        """保证单个阶段至少展示 stage_min_seconds。"""
        remaining = self._stage_min - (time.perf_counter() - started)
        if remaining > 0:
            await asyncio.sleep(remaining)

    async def _conflict_stage(self, record: TaskRecord) -> _ConflictOutcome:
        """Conflict Gate：Creative 与 Delivery 提意见，最多一轮修订。

        FAST 不调用；BALANCED 并行；CREATIVE 顺序挑战并允许恰好一轮修订。
        并行调用只执行、不写 record，结果在这里串行提交，避免并发写坏 task.json。
        """
        mode = record.sop_mode
        if mode is SOPMode.FAST:
            return _ConflictOutcome()

        source_html = (
            self._store.source_game_html(record)
            if mode is SOPMode.CREATIVE
            else None
        )
        outcome = _ConflictOutcome()

        if mode is SOPMode.BALANCED:
            self._use_tool(record, "creative", "read_requirement")
            self._use_tool(record, "delivery", "read_requirement")
            self._agent(record, "creative", AgentStatus.WORKING, "正在评估创意方向")
            self._agent(record, "delivery", AgentStatus.WORKING, "正在评估交付风险")

            started = time.perf_counter()
            results = await asyncio.gather(
                self._execute(
                    record,
                    "creative",
                    self._creative_context(record, source_html),
                    max_output_tokens=self._opinion_max_tokens,
                ),
                self._execute(
                    record,
                    "delivery",
                    self._delivery_context(record, source_html),
                    max_output_tokens=self._opinion_max_tokens,
                ),
                return_exceptions=True,
            )
            outcome.parallel_wall_ms = int((time.perf_counter() - started) * 1000)

            errors: list[BaseException] = []
            successful: list[tuple[str, AgentResult]] = []
            for talent_id, item in zip(("creative", "delivery"), results):
                if isinstance(item, BaseException):
                    errors.append(item)
                    self._emit(
                        record,
                        EventType.AGENT_STATUS_CHANGED,
                        f"{talent_id} 执行失败：{item}",
                        agent=talent_id,
                        status=AgentStatus.ERROR.value,
                        result="failed",
                        error=str(item),
                        save=False,
                    )
                else:
                    successful.append((talent_id, item))
                    self._commit_result(record, talent_id, item)

            # 任一成功结果都先落盘：失败时也保留已经产出的意见
            for talent_id, result in successful:
                if talent_id == "creative":
                    outcome.creative = result.output
                    self._record_creative(record, outcome.creative, round_no=1)
                else:
                    outcome.delivery = result.output
                    self._record_delivery(record, outcome.delivery)

            await self._wait_stage(started)
            if errors:
                first = errors[0]
                if isinstance(first, Exception):
                    raise first
                raise StageExecutionError(str(first))

            self._agent(
                record,
                "creative",
                AgentStatus.COMPLETED,
                f"创意提案：{outcome.creative.innovation}",
            )
            self._agent(
                record,
                "delivery",
                AgentStatus.COMPLETED,
                f"交付判断：{outcome.delivery.feasibility}",
            )
            return outcome

        # CREATIVE：策划提案 → 交付挑战 → 若存在风险则最多一轮修订
        self._use_tool(record, "creative", "read_requirement")
        if source_html is not None:
            self._use_tool(record, "creative", "read_game")
        self._agent(record, "creative", AgentStatus.WORKING, "正在提出创意提案")
        creative: CreativeProposal = await self._call(
            record,
            "creative",
            self._creative_context(record, source_html),
            max_output_tokens=self._opinion_max_tokens,
        )
        self._agent(
            record, "creative", AgentStatus.COMPLETED, f"创意提案：{creative.innovation}"
        )
        self._record_creative(record, creative, round_no=1)

        self._use_tool(record, "delivery", "read_requirement")
        self._agent(record, "delivery", AgentStatus.WORKING, "正在挑战创意提案")
        delivery: DeliveryAssessment = await self._call(
            record,
            "delivery",
            self._delivery_context(record, source_html, creative),
            max_output_tokens=self._opinion_max_tokens,
        )
        self._agent(
            record,
            "delivery",
            AgentStatus.COMPLETED,
            f"交付判断：{delivery.feasibility}",
        )
        self._record_delivery(record, delivery)

        if delivery.feasibility != "feasible":
            # 整个 Run 最多只允许这一轮修订
            outcome.revision_rounds = 1
            self._agent(record, "creative", AgentStatus.WORKING, "正在回应交付挑战")
            revised: CreativeProposal = await self._call(
                record,
                "creative",
                self._revision_context(record, creative, delivery),
                max_output_tokens=self._opinion_max_tokens,
            )
            self._agent(
                record,
                "creative",
                AgentStatus.COMPLETED,
                f"修订提案：{revised.innovation}",
            )
            creative = revised
            self._record_creative(record, creative, round_no=2)

        outcome.creative = creative
        outcome.delivery = delivery
        return outcome

    def _record_creative(
        self, record: TaskRecord, proposal: CreativeProposal, *, round_no: int
    ) -> None:
        if round_no > 1:
            # 修订前的提案留档，避免被覆盖后失去审计依据
            self._store.snapshot(
                record,
                "creative_proposal.json",
                f"history/creative_proposal.round{round_no - 1}.json",
            )
        self._use_tool(record, "creative", "write_creative")
        self._write(
            record, "creative_proposal.json", proposal.model_dump_json(indent=2)
        )
        self._emit(
            record,
            EventType.CONFLICT_OPINION,
            f"创意总监：{proposal.innovation}",
            agent="creative",
            result="ok",
            data={"role": "creative", "round": round_no, "proposal": proposal.model_dump()},
        )

    def _record_delivery(
        self, record: TaskRecord, assessment: DeliveryAssessment
    ) -> None:
        self._use_tool(record, "delivery", "write_delivery")
        self._write(
            record, "delivery_assessment.json", assessment.model_dump_json(indent=2)
        )
        self._emit(
            record,
            EventType.CONFLICT_OPINION,
            f"交付总监：{assessment.feasibility} / {assessment.risk}",
            agent="delivery",
            result="ok",
            data={
                "role": "delivery",
                "assessment": assessment.model_dump(),
            },
        )

    @staticmethod
    def _creative_context(record: TaskRecord, source_html: str | None) -> str:
        context = (
            "你是创意总监。请基于以下信息提出一个最重要的创意建议。\n\n"
            f"用户需求：{record.requirement}\n\n"
            "要求：只提一个建议；说明玩家价值、实现复杂度、优先级与依据；"
            "依据不足时明确说明不确定性，不得臆造用户数据或已实现功能。"
        )
        if source_html:
            context += (
                "\n\n历史版本参考代码（分支基线，请在此基础上提出改进）：\n"
                f"{source_html}"
            )
        return context

    @staticmethod
    def _delivery_context(
        record: TaskRecord,
        source_html: str | None,
        creative: CreativeProposal | None = None,
    ) -> str:
        context = (
            "你是交付总监。请评估以下需求的交付风险，并给出可执行的简化建议。\n\n"
            f"用户需求：{record.requirement}\n\n"
            "要求：指出最大风险、可行性、简化建议、优先级与依据；"
            "若方案可以稳定交付，请明确判定 feasible，不要为了反对而反对。"
        )
        if source_html:
            context += f"\n\n历史版本参考代码：\n{source_html}"
        if creative is not None:
            context += (
                "\n\n冲突阶段：交付总监挑战创意提案。"
                f"\n创意总监提案：\n{creative.model_dump_json(indent=2)}"
            )
        return context

    @staticmethod
    def _revision_context(
        record: TaskRecord,
        creative: CreativeProposal,
        delivery: DeliveryAssessment,
    ) -> str:
        return (
            "冲突阶段：这是唯一一轮修订。请回应交付总监的挑战，"
            "给出修订后的一个最重要创意建议。\n\n"
            f"用户需求：{record.requirement}\n\n"
            f"你上一轮提案：\n{creative.model_dump_json(indent=2)}\n\n"
            f"交付总监意见：\n{delivery.model_dump_json(indent=2)}\n\n"
            "要求：最多修订一轮；若认同交付意见，请收敛方案并说明；不要重复完整需求。"
        )

    @staticmethod
    def _coo_context(record: TaskRecord, conflict: _ConflictOutcome) -> str:
        context = f"用户需求：{record.requirement}\n\n请输出 PRD。"
        if conflict.creative is not None or conflict.delivery is not None:
            if conflict.creative is not None:
                context += (
                    "\n\n创意总监意见：\n"
                    f"{conflict.creative.model_dump_json(indent=2)}"
                )
            if conflict.delivery is not None:
                context += (
                    "\n\n交付总监意见：\n"
                    f"{conflict.delivery.model_dump_json(indent=2)}"
                )
            context += (
                "\n\n决策规则：\n"
                "1. 用户明确要求优先于任何角色建议。\n"
                "2. 必须输出 conflict_decision，decision 为 adopt / simplify / reject。\n"
                "3. summary 汇总双方观点，rationale 说明决策理由，不得留空。\n"
                "4. 不得为了折中而牺牲机械门禁、审查或必要测试。"
            )
        return context

    def _finalize_version(self, record: TaskRecord, mode: SOPMode) -> GameVersion:
        """写入不可变游戏版本记录；历史版本不删除、不覆盖。"""
        versions = self._store.list_versions(record.task_id)
        number = max((item.version_number for item in versions), default=0) + 1
        version_id = f"{record.task_id}-v{number}"
        parent = versions[-1].version_id if versions else None
        html = (self._store.task_dir(record.task_id) / "index.html").read_text(
            encoding="utf-8"
        )
        version = GameVersion(
            version_id=version_id,
            version_number=number,
            task_id=record.task_id,
            run_id=record.run_id,
            parent_version_id=parent,
            source_version_id=record.source_version_id,
            source_sha256=record.source_sha256,
            sop_mode=mode,
            sop_reason=record.sop_reason,
            conflict_decision=record.conflict_decision,
            creative_talent_version=record.creative_talent_version,
            delivery_talent_version=record.delivery_talent_version,
            artifact_path=f"versions/{version_id}.html",
        )
        self._store.save_version(record, version, html)
        self._emit(
            record,
            EventType.ARTIFACT_CREATED,
            f"生成游戏版本 {version_id}",
            result="ok",
            data={
                "version_id": version_id,
                "version_number": number,
                "source_version_id": record.source_version_id,
                "sop_mode": mode.value,
            },
        )
        return version

    def _use_tool(self, record: TaskRecord, agent: str, tool: str) -> None:
        """Harness 2：运行时工具校验，并把每次工具调用写进事件流留痕。"""
        self._tools.require(agent, tool)
        self._emit(
            record,
            EventType.TOOL_CALLED,
            f"{agent} 调用工具 {tool}",
            agent=agent,
            result="ok",
            data={"tool": tool},
        )

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
        model: str | None = None,
        duration_ms: int | None = None,
        token_usage: TokenUsage | None = None,
        result: str | None = None,
        error: str | None = None,
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
            model=model,
            duration_ms=duration_ms,
            token_usage=token_usage,
            result=result,
            error=error,
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
        self._use_tool(record, "engineer", "write_game")
        self._write(record, "index.html", game.html)
        self._use_tool(record, "reviewer", "run_tests")
        report = await run_mechanical_gate(game.html, prd)
        self._store.write_artifact(record, "gate.json", report.model_dump_json(indent=2))
        self._emit(
            record,
            EventType.ARTIFACT_CREATED,
            f"机械门禁{'通过' if report.passed else '未通过'}："
            f"{len(report.checks)} 项检查，失败 {len(report.failed_ids)} 项",
            status=AgentStatus.REVIEWING.value,
            result="ok" if report.passed else "failed",
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
        self._use_tool(record, "reviewer", "read_game")
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
        self._use_tool(record, "reviewer", "write_review")
        self._write(record, "review.json", review.model_dump_json(indent=2))
        self._emit(
            record,
            EventType.REVIEW_COMPLETED,
            f"第 {attempt} 次审查：{review.verdict}（{len(review.issues)} 个问题）",
            agent="reviewer",
            status=AgentStatus.REVIEWING.value,
            result="ok" if review.verdict == "PASS" else "failed",
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

    def _check_cancel(self, record: TaskRecord) -> None:
        """Harness 4：在安全点响应取消请求。"""
        if record.task_id in self._cancel_requested:
            raise TaskCancelledError("任务已收到取消请求，停止后续阶段")

    @staticmethod
    def _engineer_context(
        requirement: str,
        prd: GamePRD,
        review: ReviewReport | None,
        source_html: str | None = None,
    ) -> str:
        context = f"需求：{requirement}\n\nPRD：\n{prd.model_dump_json(indent=2)}"
        if source_html:
            context += (
                "\n\n历史版本参考代码（请在此基础上做增量修改，只改需求相关部分，"
                "保留其余已验证逻辑）：\n"
                f"{source_html}"
            )
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
        if self._budget_guard is not None:
            record.budget = self._budget_guard.snapshot(record.task_id)
            self._emit(
                record,
                EventType.BUDGET_UPDATED,
                f"预算检查阻止了后续调用：估算 ${record.budget.spent_usd:.4f} / "
                f"预算 ${record.budget.budget_usd:.4f}",
                status=record.status.value,
                result="failed",
                error=message,
                data={
                    "spent_usd": record.budget.spent_usd,
                    "budget_usd": record.budget.budget_usd,
                    "ratio": record.budget.ratio,
                    "calls": record.budget.calls,
                    "blocked_calls": record.budget.blocked_calls,
                    "cost_status": record.budget.cost_status,
                },
                save=False,
            )
        agent = self._active_agent.pop(record.task_id, None)
        if agent is not None:
            self._emit(
                record,
                EventType.AGENT_STATUS_CHANGED,
                f"执行失败：{message}",
                agent=agent,
                status=AgentStatus.ERROR.value,
                result="failed",
                error=message,
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
            result="failed",
            error=message,
            data={
                "from": previous.value,
                "to": "failed",
                "error": message,
                "artifacts": sorted(record.artifacts),
            },
        )
        return record

    def _cancelled(self, record: TaskRecord, message: str) -> TaskRecord:
        """Harness 4：取消任务。不删除任何已生成产物，状态进入终态。"""
        record.cancel_requested_at = record.cancel_requested_at or self._cancel_times.get(
            record.task_id
        )
        if self._budget_guard is not None:
            record.budget = self._budget_guard.snapshot(record.task_id)
        agent = self._active_agent.pop(record.task_id, None)
        if agent is not None:
            self._emit(
                record,
                EventType.AGENT_STATUS_CHANGED,
                f"任务已取消：{message}",
                agent=agent,
                status=AgentStatus.IDLE.value,
                result="skipped",
                save=False,
            )
        assert_transition(record.status, TaskStatus.CANCELLED)
        previous = record.status
        record.status = TaskStatus.CANCELLED
        self._emit(
            record,
            EventType.TASK_CANCELLED,
            f"{previous.value} -> cancelled：已保留当前产物",
            status=TaskStatus.CANCELLED.value,
            result="skipped",
            data={
                "from": previous.value,
                "to": "cancelled",
                "reason": message,
                "artifacts": sorted(record.artifacts),
            },
        )
        return record
