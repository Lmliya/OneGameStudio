"""Mini-6 Harness 测试：工具权限、恢复、预算守卫与统一事件追踪。

全部使用 Mock / 脚本化供应商，费用与模型切换结果都来自真实记账，
不伪造账单数据。
"""

import asyncio
from pathlib import Path

import pytest

from backend.budget import BudgetGuard, ModelPrice
from backend.core.vessel import BudgetExceededError, Vessel
from backend.models.contract import TaskStatus
from backend.models.events import EventType, Tracer
from backend.providers.base import BaseProvider, ProviderResponse
from backend.providers.mock import MockProvider
from backend.store import TaskStore
from backend.tools import DEFAULT_REGISTRY, ROLE_TOOLS, ToolPolicyError
from backend.workflow import TaskNotRunnableError, WorkflowEngine

TALENTS_DIR = Path(__file__).resolve().parents[1] / "talents"

PRD_JSON = """{
  "title": "贪吃蛇", "genre": "arcade",
  "core_loop": ["移动", "吃食物", "变长"],
  "features": ["计分", "随机食物"],
  "controls": ["方向键"],
  "win_condition": "获得高分", "lose_condition": "撞墙"
}"""


class CountingProvider(BaseProvider):
    """返回固定 PRD，并记录每次调用收到的模型名与 token 用量。"""

    default_model = "strong-model"

    def __init__(self, *, input_tokens: int = 2, output_tokens: int = 2) -> None:
        self.models: list[str] = []
        self._in = input_tokens
        self._out = output_tokens

    async def complete(self, system, user, *, model, schema=None, max_tokens=None):
        self.models.append(model)
        return ProviderResponse(
            text=PRD_JSON,
            model=model,
            input_tokens=self._in,
            output_tokens=self._out,
            usage_source="provider",
        )


class FlakyProvider(BaseProvider):
    """第一次调用抛异常，之后正常返回。"""

    default_model = "flaky"

    def __init__(self) -> None:
        self.calls = 0

    async def complete(self, system, user, *, model, schema=None, max_tokens=None):
        self.calls += 1
        if self.calls == 1:
            raise RuntimeError("网络抖动")
        return ProviderResponse(text=PRD_JSON, model=model, usage_source="provider")


class BlockingProvider(MockProvider):
    """Engineer 阶段阻塞，直到测试放行，用于验证运行中取消。"""

    def __init__(self) -> None:
        super().__init__()
        self.game_started = asyncio.Event()
        self.release = asyncio.Event()

    async def complete(self, system, user, *, model, schema=None, max_tokens=None):
        if schema == "game":
            self.game_started.set()
            await self.release.wait()
        return await super().complete(
            system, user, model=model, schema=schema, max_tokens=max_tokens
        )


def make_engine(
    tmp_path: Path,
    provider: BaseProvider,
    *,
    max_fix_rounds: int = 2,
    budget: BudgetGuard | None = None,
    default_model: str = "test",
    stage_min_seconds: float = 0.0,
) -> tuple[WorkflowEngine, TaskStore, object]:
    store = TaskStore(tmp_path)
    vessel = Vessel(
        provider,
        talents_dir=TALENTS_DIR,
        default_model=default_model,
        budget_usd=10.0,
        guard=budget,
    )
    engine = WorkflowEngine(
        vessel,
        store,
        max_fix_rounds=max_fix_rounds,
        budget=budget,
        stage_min_seconds=stage_min_seconds,
    )
    record = store.create("做一个贪吃蛇游戏", max_fix_rounds=max_fix_rounds)
    return engine, store, record


# ---------- Harness 2：Tool Policy ----------


def test_tool_registry_exposes_exact_role_tools() -> None:
    assert ROLE_TOOLS == {
        "coo": frozenset({"read_requirement", "write_prd", "write_decision"}),
        "creative": frozenset(
            {"read_requirement", "read_prd", "read_game", "write_creative"}
        ),
        "delivery": frozenset(
            {"read_requirement", "read_prd", "write_delivery"}
        ),
        "engineer": frozenset({"read_prd", "write_game", "read_review"}),
        "reviewer": frozenset({"read_game", "run_tests", "write_review"}),
        "marketer": frozenset({"read_prd", "read_review", "write_marketing"}),
    }


def test_tool_registry_has_no_shell_or_code_exec() -> None:
    names = " ".join(DEFAULT_REGISTRY.names()).lower()
    for forbidden in ("shell", "subprocess", "exec", "eval", "system"):
        assert forbidden not in names


def test_shell_tool_is_rejected() -> None:
    with pytest.raises(ToolPolicyError):
        DEFAULT_REGISTRY.require("engineer", "shell_exec")
    with pytest.raises(ToolPolicyError):
        DEFAULT_REGISTRY.require("coo", "write_game")


async def test_runtime_tool_policy_matches_role_events(tmp_path: Path) -> None:
    """完整跑一遍流程，四名员工实际调用的工具必须与授权表完全一致。"""
    engine, _, record = make_engine(tmp_path, MockProvider())

    result = await engine.start(record.task_id)
    assert result.status in {TaskStatus.COMPLETED, TaskStatus.NEEDS_ATTENTION}

    used: dict[str, set[str]] = {}
    for event in result.events:
        if event.type is EventType.TOOL_CALLED:
            used.setdefault(event.agent or "", set()).add(event.data["tool"])

    assert used["coo"] == set(ROLE_TOOLS["coo"])
    assert used["engineer"] == set(ROLE_TOOLS["engineer"])
    assert used["reviewer"] == set(ROLE_TOOLS["reviewer"])
    assert used["marketer"] == set(ROLE_TOOLS["marketer"])


# ---------- Harness 4：Recovery ----------


async def test_provider_retry_then_success() -> None:
    tracer = Tracer()
    provider = FlakyProvider()
    vessel = Vessel(
        provider,
        talents_dir=TALENTS_DIR,
        default_model="flaky",
        max_retries=1,
        retry_backoff_seconds=0.0,
        tracer=tracer,
    )

    result = await vessel.execute("coo", "做一个贪吃蛇游戏", task_id="retry-1")

    assert result.output.title == "贪吃蛇"
    assert provider.calls == 2
    assert [e.type for e in tracer.events] == [
        EventType.STAGE_STARTED,
        EventType.STAGE_FAILED,
        EventType.STAGE_COMPLETED,
    ]
    assert "网络抖动" in (tracer.events[1].error or "")


async def test_task_cancel_keeps_artifacts(tmp_path: Path) -> None:
    provider = BlockingProvider()
    engine, store, record = make_engine(tmp_path, provider)

    running = asyncio.create_task(engine.start(record.task_id))
    await asyncio.wait_for(provider.game_started.wait(), timeout=5)
    engine.cancel(record.task_id)
    provider.release.set()
    result = await running

    assert result.status is TaskStatus.CANCELLED
    assert result.cancel_requested_at is not None
    task_dir = tmp_path / record.task_id
    assert (task_dir / "prd.md").exists()
    assert not (task_dir / "index.html").exists()
    assert any(e.type is EventType.TASK_CANCELLED for e in result.events)
    # 落盘记录与内存结果一致
    assert store.load(record.task_id).status is TaskStatus.CANCELLED


def test_cancel_terminal_task_rejected(tmp_path: Path) -> None:
    engine, store, record = make_engine(tmp_path, MockProvider())
    record.status = TaskStatus.COMPLETED
    store.save(record)

    with pytest.raises(TaskNotRunnableError):
        engine.cancel(record.task_id)


async def test_terminal_task_cannot_rerun(tmp_path: Path) -> None:
    engine, store, record = make_engine(tmp_path, MockProvider())
    record.status = TaskStatus.FAILED
    store.save(record)

    with pytest.raises(TaskNotRunnableError):
        await engine.start(record.task_id)


# ---------- Harness 5：Budget Guard ----------


def make_guard(**kwargs) -> BudgetGuard:
    prices = {
        "strong-model": ModelPrice(input_per_1k=1.0, output_per_1k=1.0),
        "light-model": ModelPrice(input_per_1k=0.1, output_per_1k=0.1),
    }
    options = {
        "task_budget_usd": 0.01,
        "light_model": "light-model",
        "prices": prices,
        "max_output_tokens": 512,
    }
    options.update(kwargs)
    return BudgetGuard(**options)


async def test_budget_downgrades_to_light_model() -> None:
    guard = make_guard()
    provider = CountingProvider()
    vessel = Vessel(
        provider,
        talents_dir=TALENTS_DIR,
        default_model="strong-model",
        guard=guard,
        max_output_tokens=guard.max_output_tokens,
    )

    await vessel.execute("coo", "需求 1", task_id="budget-1")  # 4 tokens -> $0.004
    await vessel.execute("coo", "需求 2", task_id="budget-1")  # -> $0.008
    result = await vessel.execute("coo", "需求 3", task_id="budget-1")

    assert provider.models == ["strong-model", "strong-model", "light-model"]
    assert result.downgraded is True
    assert result.model == "light-model"
    snapshot = guard.snapshot("budget-1")
    assert snapshot.downgraded_calls == 1
    assert snapshot.ratio >= 0.7


async def test_budget_blocks_when_exhausted(tmp_path: Path) -> None:
    guard = make_guard(task_budget_usd=0.001)
    provider = CountingProvider()
    vessel = Vessel(
        provider,
        talents_dir=TALENTS_DIR,
        default_model="strong-model",
        guard=guard,
    )
    await vessel.execute("coo", "需求", task_id="budget-2")

    with pytest.raises(BudgetExceededError):
        await vessel.execute("coo", "需求", task_id="budget-2")

    snapshot = guard.snapshot("budget-2")
    assert snapshot.blocked_calls == 1
    assert snapshot.ratio >= 1.0
    # 被拒后不应再发起模型调用
    assert len(provider.models) == 1


async def test_engine_budget_exhaustion_fails_task(tmp_path: Path) -> None:
    guard = BudgetGuard(task_budget_usd=0.0)
    engine, _, record = make_engine(tmp_path, MockProvider(), budget=guard)

    result = await engine.start(record.task_id)

    assert result.status is TaskStatus.FAILED
    assert "预算" in (result.error or "")
    assert result.budget is not None
    # 冲突阶段会同时发起 creative 与 delivery 两次调用，都被预算拦截
    assert result.budget.blocked_calls == 2
    budget_events = [e for e in result.events if e.type is EventType.BUDGET_UPDATED]
    assert budget_events and budget_events[-1].data["blocked_calls"] == 2


async def test_unknown_cost_is_marked_unknown() -> None:
    """没有配置价格时，费用只能标记未知，不能假装是 0。"""
    guard = BudgetGuard(task_budget_usd=1.0)  # 无价格表
    vessel = Vessel(
        MockProvider(),
        talents_dir=TALENTS_DIR,
        default_model="mock",
        guard=guard,
    )

    result = await vessel.execute("coo", "需求", task_id="unknown-1")

    assert result.usage_source == "estimated"
    assert result.cost_status == "unknown"
    snapshot = guard.snapshot("unknown-1")
    assert snapshot.cost_status == "unknown"
    assert snapshot.unknown_cost_calls == 1


# ---------- Harness 6：Event Trace ----------


async def test_event_trace_unified_fields(tmp_path: Path) -> None:
    engine, _, record = make_engine(tmp_path, MockProvider())

    result = await engine.start(record.task_id)

    calls = [
        e
        for e in result.events
        if e.type is EventType.AGENT_STATUS_CHANGED
        and e.agent == "engineer"
        and e.model is not None
    ]
    assert calls, "应存在带模型信息的员工调用事件"
    event = calls[0]
    assert event.task_id == record.task_id
    assert event.duration_ms is not None
    assert event.token_usage is not None
    assert event.token_usage.total_tokens > 0
    assert event.result == "ok"
    assert event.error is None

    message = event.as_message()
    assert message["model"] == event.model
    assert message["token_usage"]["total_tokens"] == event.token_usage.total_tokens

    failed = [e for e in result.events if e.type is EventType.TASK_FAILED]
    assert failed == []  # 成功流程不应有失败事件


async def test_trace_records_error_on_failure(tmp_path: Path) -> None:
    class BadProvider(BaseProvider):
        default_model = "bad"

        async def complete(self, system, user, *, model, schema=None, max_tokens=None):
            return ProviderResponse(text="这不是 JSON", model=model)

    engine, _, record = make_engine(tmp_path, BadProvider())

    result = await engine.start(record.task_id)

    assert result.status is TaskStatus.FAILED
    failures = [e for e in result.events if e.type is EventType.TASK_FAILED]
    assert failures and failures[0].result == "failed"
    assert failures[0].error and "JSON" in failures[0].error
    # 失败也必须保留日志与已生成产物
    assert (tmp_path / record.task_id / "task.json").exists()
    assert "prd.md" not in result.artifacts
