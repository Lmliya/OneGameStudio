"""工作流全流程与异常场景测试（Mock / 脚本化模型，真实浏览器门禁）。"""

import json
from pathlib import Path

import pytest

from backend.core.vessel import Vessel
from backend.models.contract import TaskStatus
from backend.providers.base import BaseProvider, ProviderResponse
from backend.providers.mock import MARKETING_PAYLOAD
from backend.store import TaskStore
from backend.workflow import TaskAlreadyRunningError, WorkflowEngine

TALENTS_DIR = Path(__file__).resolve().parents[1] / "talents"

PRD_JSON = """{
  "title": "贪吃蛇", "genre": "arcade",
  "core_loop": ["移动", "吃食物", "变长"],
  "features": ["计分", "随机食物"],
  "controls": ["方向键"],
  "win_condition": "获得高分", "lose_condition": "撞墙",
  "conflict_decision": {
    "decision": "simplify",
    "summary": "创意建议可行，交付要求收敛范围",
    "rationale": "保留核心反馈，同时控制实现复杂度",
    "adopted_from": "both"
  }
}"""

CREATIVE_JSON = json.dumps(
    {
        "innovation": "让背景随得分变化",
        "player_value": "强化成长反馈",
        "complexity": "low",
        "priority": "high",
        "rationale": "只改绘制层",
    },
    ensure_ascii=False,
)
DELIVERY_JSON = json.dumps(
    {
        "risk": "配色可能影响可读性",
        "feasibility": "feasible",
        "simplification": "只改背景色",
        "priority": "medium",
        "rationale": "改动局限在绘制层",
    },
    ensure_ascii=False,
)

GAME_HTML = "<html><body><canvas width='320' height='240'></canvas><script>var a=1</script></body></html>"
GAME_JSON = (
    '{"title":"贪吃蛇","filename":"snake.html","html":"'
    + GAME_HTML
    + '","notes":"初版"}'
)
GAME_JSON_FIXED = (
    '{"title":"贪吃蛇","filename":"snake.html","html":"'
    + GAME_HTML
    + '","notes":"已修复"}'
)
# 没有游戏区域，机械门禁必然失败
BROKEN_GAME_JSON = (
    '{"title":"贪吃蛇","filename":"snake.html",'
    '"html":"<html><body><script>var a=1</script></body></html>",'
    '"notes":"缺少画布"}'
)

REVIEW_FAIL_JSON = """{
  "verdict": "ITERATE",
  "issues": [{"severity": "high", "description": "缺少计分",
              "suggestion": "增加分数显示"}],
  "suggestions": ["补充计分 UI"],
  "summary": "玩法不完整"
}"""

REVIEW_PASS_JSON = '{"verdict":"PASS","issues":[],"suggestions":[],"summary":"可交付"}'

MARKETING_JSON = json.dumps(MARKETING_PAYLOAD, ensure_ascii=False)


class ScriptedProvider(BaseProvider):
    """按 schema 依次返回脚本中的响应；元素可以是字符串或异常。"""

    default_model = "scripted"

    # 旧测试只关心主流程；新增总监视为默认可用，FAST 测试通过 calls 断言其未被调用
    _DEFAULTS = {"creative_proposal": CREATIVE_JSON, "delivery_assessment": DELIVERY_JSON}

    def __init__(self, script: dict[str, list]) -> None:
        self._script = {k: list(v) for k, v in script.items()}
        self.calls: list[str] = []

    async def complete(self, system, user, *, model, schema=None, max_tokens=None):
        self.calls.append(schema or "")
        queue = self._script.get(schema or "", [])
        if not queue:
            default = self._DEFAULTS.get(schema or "")
            if default is None:
                raise AssertionError(f"脚本中没有更多 '{schema}' 响应")
            return ProviderResponse(text=default, model=model)
        item = queue.pop(0)
        if isinstance(item, Exception):
            raise item
        return ProviderResponse(text=item, model=model)


class SlowProvider(BaseProvider):
    """每次调用都阻塞一小段时间，用于测试并发保护。"""

    default_model = "slow"

    _PAYLOADS = {
        "prd": PRD_JSON,
        "game": GAME_JSON,
        "review": REVIEW_PASS_JSON,
        "marketing": MARKETING_JSON,
        "creative_proposal": CREATIVE_JSON,
        "delivery_assessment": DELIVERY_JSON,
    }

    async def complete(self, system, user, *, model, schema=None, max_tokens=None):
        import asyncio

        await asyncio.sleep(0.05)
        return ProviderResponse(text=self._PAYLOADS[schema], model=model)


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
        "gate.json",
        "review.json",
        "marketing_kit.json",
        "marketing_kit.md",
        "creative_proposal.json",
        "delivery_assessment.json",
        "conflict_decision.json",
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
    states = [
        e.stage
        for e in result.events
        if e.type.value == "task.status_changed"
    ]
    assert "fixing" in states
    assert states.count("reviewing") == 2
    # 修复前的旧版本必须保留
    assert (tmp_path / record.task_id / "history" / "index.v1.html").exists()


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
    assert (tmp_path / record.task_id / "prd.md").exists()
    assert (tmp_path / record.task_id / "index.html").exists()
    assert (tmp_path / record.task_id / "review.json").exists()
    assert not (tmp_path / record.task_id / "marketing_kit.md").exists()


async def test_mechanical_gate_failure_forces_iterate(tmp_path: Path) -> None:
    """AI 一直说 PASS，但游戏没有画布，门禁必须阻止交付。"""
    provider = ScriptedProvider(
        {
            "prd": [PRD_JSON],
            "game": [BROKEN_GAME_JSON, BROKEN_GAME_JSON, BROKEN_GAME_JSON],
            "review": [REVIEW_PASS_JSON, REVIEW_PASS_JSON, REVIEW_PASS_JSON],
        }
    )
    engine, _, record = make_engine(tmp_path, provider, max_fix_rounds=2)

    result = await engine.start(record.task_id)

    assert result.status is TaskStatus.NEEDS_ATTENTION
    review = (tmp_path / record.task_id / "review.json").read_text(encoding="utf-8")
    assert '"verdict": "ITERATE"' in review
    assert '"forced_by_gate": true' in review
    gate = (tmp_path / record.task_id / "gate.json").read_text(encoding="utf-8")
    assert '"passed": false' in gate


async def test_reviewer_parse_failure_terminates_task(tmp_path: Path) -> None:
    provider = ScriptedProvider(
        {"prd": [PRD_JSON], "game": [GAME_JSON], "review": ["这不是 JSON"]}
    )
    engine, _, record = make_engine(tmp_path, provider)

    result = await engine.start(record.task_id)

    assert result.status is TaskStatus.FAILED
    assert "无法解析" in result.error


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


async def test_marketing_content_matches_game(tmp_path: Path) -> None:
    """营销素材必须结构化、完整，且与游戏本身一致。"""
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
    task_dir = tmp_path / record.task_id
    kit = json.loads((task_dir / "marketing_kit.json").read_text(encoding="utf-8"))

    assert kit["positioning"]["game_name"] == "贪吃蛇"
    assert len(kit["posts"]) == 2
    assert {post["kind"] for post in kit["posts"]} == {"fun", "challenge"}
    assert sorted(day["day"] for day in kit["plan"]) == list(range(1, 8))

    markdown = (task_dir / "marketing_kit.md").read_text(encoding="utf-8")
    assert kit["slogan"] in markdown
    for post in kit["posts"]:
        assert post["title"] in markdown


async def test_fabricated_marketing_claims_keep_game(tmp_path: Path) -> None:
    """编造数据必须被拦下，但已通过审查的游戏不能被删除。"""
    bad_kit = json.loads(MARKETING_JSON)
    bad_kit["positioning"]["one_liner"] = "已经有 10 万用户玩过的贪吃蛇"
    provider = ScriptedProvider(
        {
            "prd": [PRD_JSON],
            "game": [GAME_JSON],
            "review": [REVIEW_PASS_JSON],
            "marketing": [json.dumps(bad_kit, ensure_ascii=False)],
        }
    )
    engine, _, record = make_engine(tmp_path, provider)

    result = await engine.start(record.task_id)

    assert result.status is TaskStatus.FAILED
    assert "无法证实" in result.error
    task_dir = tmp_path / record.task_id
    assert (task_dir / "index.html").exists()
    assert (task_dir / "review.json").exists()
    assert not (task_dir / "marketing_kit.md").exists()
    assert not (task_dir / "marketing_kit.json").exists()


async def test_stage_min_seconds_paces_each_agent(tmp_path: Path) -> None:
    """stage_min_seconds > 0 时，每个员工的工作态必须至少持续该时长。"""
    import time

    provider = ScriptedProvider(
        {
            "prd": [PRD_JSON],
            "game": [GAME_JSON],
            "review": [REVIEW_PASS_JSON],
            "marketing": [MARKETING_JSON],
        }
    )
    store = TaskStore(tmp_path)
    vessel = Vessel(
        provider, talents_dir=TALENTS_DIR, default_model="test", budget_usd=10.0
    )
    engine = WorkflowEngine(vessel, store, stage_min_seconds=0.03)
    record = store.create("做一个贪吃蛇游戏")

    started = time.perf_counter()
    result = await engine.start(record.task_id)
    elapsed = time.perf_counter() - started

    # 五个阶段：Conflict（并行） / COO / Engineer / Reviewer / Marketer
    assert result.status is TaskStatus.COMPLETED
    assert elapsed >= 0.15

    durations = []
    active_at: dict[str, object] = {}
    for event in result.events:
        if event.type.value != "agent.status_changed" or not event.agent:
            continue
        if event.status in {"working", "reviewing", "fixing"}:
            active_at[event.agent] = event.created_at
        elif event.status == "completed" and event.agent in active_at:
            durations.append(
                (event.created_at - active_at.pop(event.agent)).total_seconds()
            )
    assert durations and min(durations) >= 0.02
