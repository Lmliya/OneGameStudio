"""工作流全流程与异常场景测试（全部使用 Mock / 脚本化模型，不联网）。"""

from pathlib import Path

import pytest

from backend.core.vessel import Vessel
from backend.models.contract import TaskStatus
from backend.providers.base import BaseProvider, ProviderResponse
from backend.store import TaskStore
from backend.workflow import TaskAlreadyRunningError, WorkflowEngine

TALENTS_DIR = Path(__file__).resolve().parents[1] / "talents"

PRD_JSON = """{
  "title": "贪吃蛇", "genre": "arcade",
  "core_loop": ["移动", "吃食物", "变长"],
  "features": ["计分", "随机食物"],
  "controls": ["方向键"],
  "win_condition": "获得高分", "lose_condition": "撞墙"
}"""

GAME_HTML = "<html><body><canvas></canvas><script>console.log(1)</script></body></html>"
GAME_JSON = (
    '{"title":"贪吃蛇","filename":"snake.html","html":'
    f'"{GAME_HTML}","notes":"初版"}}'
)
GAME_JSON_FIXED = (
    '{"title":"贪吃蛇","filename":"snake.html","html":'
    f'"{GAME_HTML}","notes":"已修复"}}'
)

REVIEW_FAIL_JSON = """{
  "score": 55, "passed": false,
  "issues": [{"severity": "high", "description": "缺少计分",
              "suggestion": "增加分数显示"}]
}"""

REVIEW_PASS_JSON = '{"score": 90, "passed": true, "issues": []}'

MARKETING_JSON = """{
  "tagline": "一条蛇的冒险", "description": "经典玩法，轻松上手",
  "hashtags": ["#贪吃蛇"], "channels": ["朋友圈"]
}"""


class ScriptedProvider(BaseProvider):
    """按 schema 依次返回脚本中的响应；元素可以是字符串或异常。"""

    default_model = "scripted"

    def __init__(self, script: dict[str, list]) -> None:
        self._script = {k: list(v) for k, v in script.items()}

    async def complete(self, system, user, *, model, schema=None):
        queue = self._script.get(schema or "", [])
        if not queue:
            raise AssertionError(f"脚本中没有更多 '{schema}' 响应")
        item = queue.pop(0)
        if isinstance(item, Exception):
            raise item
        return ProviderResponse(text=item, model=model)


class SlowProvider(BaseProvider):
    """每次调用都阻塞一小段时间，用于测试并发保护。"""

    default_model = "slow"

    async def complete(self, system, user, *, model, schema=None):
        import asyncio

        await asyncio.sleep(0.05)
        return ProviderResponse(text=PRD_JSON, model=model)


def make_engine(tmp_path: Path, provider: BaseProvider, max_fix_rounds: int = 2):
    store = TaskStore(tmp_path)
    vessel = Vessel(
        provider, talents_dir=TALENTS_DIR, default_model="test", budget_usd=10.0
    )
    engine = WorkflowEngine(vessel, store, max_fix_rounds=max_fix_rounds)
    record = store.create("做一个贪吃蛇游戏", max_fix_rounds=max_fix_rounds)
    return engine, store, record


async def test_full_flow_success_first_try(tmp_path: Path) -> None:
    provider = ScriptedProvider(
        {
            "prd": [PRD_JSON],
            "game": [GAME_JSON],
            "review": [REVIEW_PASS_JSON],
            "marketing": [MARKETING_JSON],
        }
    )
    engine, _, record = make_engine(tmp_path, provider)

    result = await engine.start(record.task_id)

    assert result.status is TaskStatus.COMPLETED
    assert set(result.artifacts) == {
        "prd.md",
        "index.html",
        "review.json",
        "marketing_kit.md",
    }
    task_dir = tmp_path / record.task_id
    for name in result.artifacts:
        assert (task_dir / name).exists()
    assert (task_dir / "task.json").exists()
    assert result.fix_attempts == 0


async def test_reviewer_rejects_then_passes(tmp_path: Path) -> None:
    provider = ScriptedProvider(
        {
            "prd": [PRD_JSON],
            "game": [GAME_JSON, GAME_JSON_FIXED],
            "review": [REVIEW_FAIL_JSON, REVIEW_PASS_JSON],
            "marketing": [MARKETING_JSON],
        }
    )
    engine, _, record = make_engine(tmp_path, provider)

    result = await engine.start(record.task_id)

    assert result.status is TaskStatus.COMPLETED
    assert result.fix_attempts == 1
    states = [e.stage for e in result.events if e.type.value == "state_changed"]
    assert "fixing" in states
    assert states.count("reviewing") == 2


async def test_fix_limit_reached_goes_to_needs_attention(tmp_path: Path) -> None:
    provider = ScriptedProvider(
        {
            "prd": [PRD_JSON],
            "game": [GAME_JSON, GAME_JSON_FIXED, GAME_JSON_FIXED],
            "review": [REVIEW_FAIL_JSON, REVIEW_FAIL_JSON, REVIEW_FAIL_JSON],
        }
    )
    engine, _, record = make_engine(tmp_path, provider, max_fix_rounds=2)

    result = await engine.start(record.task_id)

    assert result.status is TaskStatus.NEEDS_ATTENTION
    assert result.fix_attempts == 2
    assert result.error
    # 已产出的文件必须保留
    assert (tmp_path / record.task_id / "prd.md").exists()
    assert (tmp_path / record.task_id / "index.html").exists()
    assert (tmp_path / record.task_id / "review.json").exists()
    assert not (tmp_path / record.task_id / "marketing_kit.md").exists()


async def test_coo_bad_output_fails(tmp_path: Path) -> None:
    provider = ScriptedProvider({"prd": ["这不是 JSON"]})
    engine, _, record = make_engine(tmp_path, provider)

    result = await engine.start(record.task_id)

    assert result.status is TaskStatus.FAILED
    assert "JSON" in result.error
    assert not (tmp_path / record.task_id / "index.html").exists()


async def test_engineer_produces_no_file_fails(tmp_path: Path) -> None:
    empty_game = '{"title":"x","filename":"a.html","html":"","notes":""}'
    provider = ScriptedProvider({"prd": [PRD_JSON], "game": [empty_game]})
    engine, _, record = make_engine(tmp_path, provider)

    result = await engine.start(record.task_id)

    assert result.status is TaskStatus.FAILED
    # PRD 已产出，index.html 未产出
    assert (tmp_path / record.task_id / "prd.md").exists()
    assert not (tmp_path / record.task_id / "index.html").exists()


async def test_marketer_failure_keeps_prior_artifacts(tmp_path: Path) -> None:
    provider = ScriptedProvider(
        {
            "prd": [PRD_JSON],
            "game": [GAME_JSON],
            "review": [REVIEW_PASS_JSON],
            "marketing": [RuntimeError("营销模型不可用")],
        }
    )
    engine, _, record = make_engine(tmp_path, provider)

    result = await engine.start(record.task_id)

    assert result.status is TaskStatus.FAILED
    assert "营销模型不可用" in result.error
    task_dir = tmp_path / record.task_id
    assert (task_dir / "prd.md").exists()
    assert (task_dir / "index.html").exists()
    assert (task_dir / "review.json").exists()
    assert not (task_dir / "marketing_kit.md").exists()


async def test_same_task_cannot_run_concurrently(tmp_path: Path) -> None:
    engine, _, record = make_engine(tmp_path, SlowProvider())

    first = __import__("asyncio").create_task(engine.start(record.task_id))
    await __import__("asyncio").sleep(0.01)

    with pytest.raises(TaskAlreadyRunningError):
        await engine.start(record.task_id)

    await first
