"""确定性工作流引擎。

流程：
  pending -> planning(COO) -> coding(Engineer) -> reviewing(Reviewer)
          -> [fixing(Engineer) -> reviewing] * max_fix_rounds
          -> marketing(Marketer) -> completed

约束：
- 状态迁移只经由 state_machine 校验后执行。
- Reviewer 不写代码，Marketer 不改游戏，二者产物分别是 review.json 与 marketing_kit.md。
- 任一阶段异常都保留已写入的产物，并落到 failed。
- 修复次数用尽仍不通过则进入 needs_attention。
"""

from __future__ import annotations

from backend.core.vessel import Vessel, VesselError
from backend.models.contract import TaskRecord, TaskStatus
from backend.models.events import EventType, TraceEvent
from backend.schemas import GameArtifact, GamePRD, MarketingKit, ReviewReport
from backend.store import TaskStore
from backend.workflow.state_machine import assert_transition


class WorkflowError(RuntimeError):
    """工作流层面的错误基类。"""


class TaskAlreadyRunningError(WorkflowError):
    """同一 task_id 已在执行，拒绝并发启动。"""


class StageExecutionError(WorkflowError):
    """阶段执行的确定性检查失败（如产物不合法）。"""


def game_quality_gate(html: str) -> list[str]:
    """确定性质量门禁：不依赖模型，纯代码检查。

    只有通过这里，Reviewer 的"通过"才被认可，才能进入 Marketing。
    """
    problems: list[str] = []
    if not html.strip():
        problems.append("index.html 为空")
        return problems
    lowered = html.lower()
    if "<html" not in lowered:
        problems.append("缺少 <html> 根标签")
    if "<script" not in lowered:
        problems.append("缺少 <script>，游戏无法交互")
    return problems


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

            # ---------- Engineer ----------
            self._transition(record, TaskStatus.CODING)
            game: GameArtifact = await self._call(
                record, "engineer", self._engineer_context(record.requirement, prd, None)
            )
            self._write_game(record, game)

            # ---------- Review / Fix 循环 ----------
            self._transition(record, TaskStatus.REVIEWING)
            review = await self._review(record, prd, game)

            while not review.passed:
                if record.fix_attempts >= record.max_fix_rounds:
                    record.error = (
                        f"审查连续未通过，已达到修复上限 {record.max_fix_rounds} 次"
                    )
                    self._transition(record, TaskStatus.NEEDS_ATTENTION)
                    self._store.save(record)
                    return record

                self._transition(record, TaskStatus.FIXING)
                record.fix_attempts += 1
                record.events.append(
                    TraceEvent(
                        task_id=record.task_id,
                        type=EventType.FIX_REQUESTED,
                        stage=TaskStatus.FIXING.value,
                        message=f"第 {record.fix_attempts} 次修复",
                        data={"issues": [i.model_dump() for i in review.issues]},
                    )
                )
                self._store.save(record)

                game = await self._call(
                    record,
                    "engineer",
                    self._engineer_context(record.requirement, prd, review),
                )
                self._write_game(record, game)

                self._transition(record, TaskStatus.REVIEWING)
                review = await self._review(record, prd, game)

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

        except (VesselError, StageExecutionError) as exc:
            return self._fail(record, str(exc))

    # ---------- 内部方法 ----------

    async def _call(self, record: TaskRecord, talent_id: str, context: str):
        """执行一个员工，返回已通过契约校验的输出对象。"""
        result = await self._vessel.execute(
            talent_id, context, task_id=record.task_id
        )
        return result.output

    def _write_game(self, record: TaskRecord, game: GameArtifact) -> None:
        problems = game_quality_gate(game.html)
        if problems:
            raise StageExecutionError("游戏质量门禁未通过：" + "；".join(problems))
        self._store.write_artifact(record, "index.html", game.html)
        self._store.save(record)

    async def _review(
        self, record: TaskRecord, prd: GamePRD, game: GameArtifact
    ) -> ReviewReport:
        attempt = record.fix_attempts + 1
        context = (
            f"PRD：\n{prd.model_dump_json(indent=2)}\n\n"
            f"游戏代码 index.html：\n{game.html}\n\n"
            f"审查轮次: {attempt}"
        )
        review: ReviewReport = await self._call(record, "reviewer", context)
        # Reviewer 只写审查结果，绝不回写 index.html
        self._store.write_artifact(
            record, "review.json", review.model_dump_json(indent=2)
        )
        self._store.save(record)
        return review

    @staticmethod
    def _engineer_context(
        requirement: str, prd: GamePRD, review: ReviewReport | None
    ) -> str:
        context = (
            f"需求：{requirement}\n\n"
            f"PRD：\n{prd.model_dump_json(indent=2)}"
        )
        if review is not None:
            issues = "\n".join(
                f"- [{issue.severity}] {issue.description} -> {issue.suggestion}"
                for issue in review.issues
            )
            context += f"\n\n审查意见：\n{issues}\n\n请修复后输出完整游戏。"
        return context

    @staticmethod
    def _marketing_context(
        prd: GamePRD, game: GameArtifact, review: ReviewReport
    ) -> str:
        return (
            f"PRD：\n{prd.model_dump_json(indent=2)}\n\n"
            f"游戏文件：{game.filename}\n"
            f"审查得分：{review.score}\n"
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
