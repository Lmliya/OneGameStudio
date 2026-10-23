"""Mock 供应商与 Vessel 封装的行为测试。"""

import pytest

from backend.core.vessel import BudgetExceededError, Vessel
from backend.models.events import EventType, Tracer
from backend.models.talent import TalentSpec
from backend.providers.base import BaseProvider
from backend.providers.mock import MockProvider


def _talent() -> TalentSpec:
    return TalentSpec(
        id="coo",
        name="COO",
        role="需求分析",
        system_prompt="你是 COO",
        allowed_tools=[],
        model="mock",
    )


def test_mock_provider_implements_base() -> None:
    assert isinstance(MockProvider(), BaseProvider)


async def test_mock_is_deterministic_and_free() -> None:
    provider = MockProvider()
    first = await provider.complete("sys", "做一个贪吃蛇游戏", model="mock")
    second = await provider.complete("sys", "做一个贪吃蛇游戏", model="mock")
    assert first.text == second.text
    assert first.cost_usd == 0.0
    assert first.model == "mock"


async def test_mock_differs_by_keyword() -> None:
    provider = MockProvider()
    snake = await provider.complete("sys", "做一个贪吃蛇游戏", model="mock")
    brick = await provider.complete("sys", "做一个打砖块游戏", model="mock")
    assert snake.text != brick.text


async def test_vessel_records_start_and_complete() -> None:
    tracer = Tracer()
    vessel = Vessel(MockProvider(), tracer, budget_usd=1.0)

    result = await vessel.run(
        talent=_talent(), task_id="t1", stage="design", prompt="做一个贪吃蛇游戏"
    )

    assert "贪吃蛇" in result.text
    assert result.cost_usd == 0.0
    assert [e.type for e in tracer.events] == [
        EventType.STAGE_STARTED,
        EventType.STAGE_COMPLETED,
    ]


async def test_vessel_budget_guard() -> None:
    tracer = Tracer()
    vessel = Vessel(MockProvider(), tracer, budget_usd=0.0)

    with pytest.raises(BudgetExceededError):
        await vessel.run(
            talent=_talent(), task_id="t1", stage="design", prompt="做一个贪吃蛇游戏"
        )
