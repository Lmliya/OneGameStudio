"""Vessel 统一执行容器的测试。

覆盖：四个员工独立执行、模型选择、解析失败、校验失败、超时、预算、事件记录。
"""

import asyncio
from pathlib import Path

import pytest

from backend.core.vessel import (
    AgentResult,
    BudgetExceededError,
    OutputParseError,
    OutputValidationError,
    ProviderTimeoutError,
    Vessel,
)
from backend.models.events import EventType, Tracer
from backend.providers.base import BaseProvider, ProviderResponse
from backend.providers.mock import MockProvider
from backend.schemas import GameArtifact, GamePRD, MarketingKit, ReviewReport

TALENTS_DIR = Path(__file__).resolve().parents[1] / "talents"


def make_vessel(provider: BaseProvider, **kwargs) -> Vessel:
    return Vessel(
        provider,
        talents_dir=TALENTS_DIR,
        default_model="test-model",
        **kwargs,
    )


class StaticProvider(BaseProvider):
    """返回固定文本，用于构造异常场景。"""

    default_model = "static"

    def __init__(self, text: str) -> None:
        self._text = text

    async def complete(self, system, user, *, model, schema=None):
        return ProviderResponse(text=self._text, model=model)


class SlowProvider(BaseProvider):
    default_model = "slow"

    async def complete(self, system, user, *, model, schema=None):
        await asyncio.sleep(0.5)
        return ProviderResponse(text="{}", model=model)


@pytest.mark.parametrize(
    ("talent_id", "schema_cls"),
    [
        ("coo", GamePRD),
        ("engineer", GameArtifact),
        ("reviewer", ReviewReport),
        ("marketer", MarketingKit),
    ],
)
async def test_all_talents_run_through_one_vessel(talent_id: str, schema_cls: type) -> None:
    vessel = make_vessel(MockProvider())

    result = await vessel.execute(talent_id, "做一个贪吃蛇游戏")

    assert isinstance(result, AgentResult)
    assert result.talent == talent_id
    assert isinstance(result.output, schema_cls)
    assert result.duration_ms >= 0


async def test_uses_default_model_when_talent_model_empty() -> None:
    # MockProvider 固定返回 model="mock"，这里用 Recorder 验证传入参数
    seen: dict[str, str] = {}

    class Recorder(BaseProvider):
        default_model = "recorder"

        async def complete(self, system, user, *, model, schema=None):
            seen["model"] = model
            seen["schema"] = schema or ""
            return ProviderResponse(text='{"title":"x","genre":"y","core_loop":["a"],'
                                    '"features":["b"],"controls":["c"],'
                                    '"win_condition":"d","lose_condition":"e"}',
                                    model=model)

    result = await make_vessel(Recorder()).execute("coo", "做一个游戏")
    assert seen["model"] == "test-model"
    assert seen["schema"] == "prd"
    assert result.model == "test-model"


async def test_invalid_json_raises_parse_error() -> None:
    vessel = make_vessel(StaticProvider("这不是 JSON"))
    with pytest.raises(OutputParseError):
        await vessel.execute("coo", "需求")


async def test_wrong_shape_raises_validation_error() -> None:
    vessel = make_vessel(StaticProvider('{"title": "缺少必填字段"}'))
    with pytest.raises(OutputValidationError):
        await vessel.execute("coo", "需求")


async def test_json_in_code_fence_is_tolerated() -> None:
    text = (
        "```json\n"
        '{"title":"t","genre":"g","core_loop":["a"],"features":["b"],'
        '"controls":["c"],"win_condition":"d","lose_condition":"e"}\n'
        "```"
    )
    result = await make_vessel(StaticProvider(text)).execute("coo", "需求")
    assert isinstance(result.output, GamePRD)


async def test_timeout_raises_provider_timeout() -> None:
    vessel = make_vessel(SlowProvider(), timeout_seconds=0.05)
    with pytest.raises(ProviderTimeoutError):
        await vessel.execute("coo", "需求")


async def test_budget_guard() -> None:
    vessel = make_vessel(MockProvider(), budget_usd=0.0)
    with pytest.raises(BudgetExceededError):
        await vessel.execute("coo", "需求")


async def test_tracer_records_events() -> None:
    tracer = Tracer()
    vessel = make_vessel(MockProvider(), tracer=tracer)
    await vessel.execute("coo", "需求", task_id="t1")

    assert [e.type for e in tracer.events] == [
        EventType.STAGE_STARTED,
        EventType.STAGE_COMPLETED,
    ]
    assert all(e.task_id == "t1" for e in tracer.events)
