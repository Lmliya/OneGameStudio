"""阶段 9：三种 SOP、Conflict Gate、并行、版本记录与异常恢复测试。"""

import asyncio
import hashlib
import json
import time
from pathlib import Path

import pytest

from backend.core.vessel import Vessel
from backend.models.contract import TaskStatus
from backend.models.sop import SOPMode
from backend.providers.base import BaseProvider, ProviderResponse
from backend.providers.mock import MARKETING_PAYLOAD
from backend.store import TaskStore
from backend.talents import TalentConfigError, load_talent
from backend.tools import DEFAULT_REGISTRY, ToolPolicyError
from backend.workflow import WorkflowEngine

TALENTS_DIR = Path(__file__).resolve().parents[1] / "talents"

FAST_PRD_JSON = json.dumps(
    {
        "title": "贪吃蛇",
        "genre": "arcade",
        "core_loop": ["移动", "吃食物", "变长"],
        "features": ["计分", "随机食物"],
        "controls": ["方向键"],
        "win_condition": "获得高分",
        "lose_condition": "撞墙",
    },
    ensure_ascii=False,
)

DECISION_PRD_JSON = json.dumps(
    {
        "title": "贪吃蛇",
        "genre": "arcade",
        "core_loop": ["移动", "吃食物", "变长"],
        "features": ["计分", "随机食物"],
        "controls": ["方向键"],
        "win_condition": "获得高分",
        "lose_condition": "撞墙",
        "conflict_decision": {
            "decision": "simplify",
            "summary": "创意可提升反馈，交付要求收敛配色范围",
            "rationale": "用户要求优先，同时保留可验证的核心玩法",
            "adopted_from": "both",
        },
    },
    ensure_ascii=False,
)

GAME_HTML = (
    "<html><body><canvas width='320' height='240'></canvas>"
    "<script>var a=1</script></body></html>"
)
GAME_JSON = json.dumps(
    {"title": "贪吃蛇", "filename": "snake.html", "html": GAME_HTML, "notes": "初版"},
    ensure_ascii=False,
)
REVIEW_PASS = json.dumps(
    {"verdict": "PASS", "issues": [], "suggestions": [], "summary": "可交付"},
    ensure_ascii=False,
)
MARKETING_JSON = json.dumps(MARKETING_PAYLOAD, ensure_ascii=False)

CREATIVE_ROUND1 = json.dumps(
    {
        "innovation": "让背景随得分变化",
        "player_value": "强化成长反馈",
        "complexity": "low",
        "priority": "high",
        "rationale": "只改绘制层",
    },
    ensure_ascii=False,
)
CREATIVE_ROUND2 = json.dumps(
    {
        "innovation": "背景分三档变色，保留食物高对比度",
        "player_value": "保留成长反馈且不牺牲可读性",
        "complexity": "low",
        "priority": "medium",
        "rationale": "接受交付总监关于对比度的挑战",
    },
    ensure_ascii=False,
)
DELIVERY_FEASIBLE = json.dumps(
    {
        "risk": "配色可能影响可读性",
        "feasibility": "feasible",
        "simplification": "只改背景色",
        "priority": "medium",
        "rationale": "改动局限在绘制层",
    },
    ensure_ascii=False,
)
DELIVERY_RISKY = json.dumps(
    {
        "risk": "高对比配色会让食物与蛇身难以区分",
        "feasibility": "risky",
        "simplification": "限制配色档位并保留食物高对比度",
        "priority": "high",
        "rationale": "方向可行，但需要收敛颜色数量",
    },
    ensure_ascii=False,
)


class ScriptedProvider(BaseProvider):
    """按 schema 返回脚本响应，并记录调用顺序与上下文。"""

    default_model = "scripted"

    _DEFAULTS = {
        "prd": DECISION_PRD_JSON,
        "game": GAME_JSON,
        "review": REVIEW_PASS,
        "marketing": MARKETING_JSON,
        "creative_proposal": CREATIVE_ROUND1,
        "delivery_assessment": DELIVERY_FEASIBLE,
    }

    def __init__(self, script: dict[str, list] | None = None) -> None:
        self._script = {k: list(v) for k, v in (script or {}).items()}
        self.calls: list[str] = []
        self.user_prompts: dict[str, list[str]] = {}

    async def complete(self, system, user, *, model, schema=None, max_tokens=None):
        key = schema or ""
        self.calls.append(key)
        self.user_prompts.setdefault(key, []).append(user)
        queue = self._script.get(key, [])
        if queue:
            item = queue.pop(0)
            if isinstance(item, Exception):
                raise item
            return ProviderResponse(text=item, model=model)
        if key in self._DEFAULTS:
            return ProviderResponse(text=self._DEFAULTS[key], model=model)
        raise AssertionError(f"脚本中没有更多 '{key}' 响应")


class TrackingProvider(ScriptedProvider):
    """记录顾问调用的最大并发数，用于证明 BALANCED 的并行是真实并发。"""

    def __init__(self, *, delay: float = 0.08, script: dict[str, list] | None = None):
        super().__init__(script)
        self.delay = delay
        self.active = 0
        self.max_active = 0

    async def complete(self, system, user, *, model, schema=None, max_tokens=None):
        if schema in {"creative_proposal", "delivery_assessment"}:
            self.active += 1
            self.max_active = max(self.max_active, self.active)
            try:
                await asyncio.sleep(self.delay)
                return await super().complete(
                    system, user, model=model, schema=schema, max_tokens=max_tokens
                )
            finally:
                self.active -= 1
        return await super().complete(
            system, user, model=model, schema=schema, max_tokens=max_tokens
        )


def make_engine(
    tmp_path: Path,
    provider: BaseProvider,
    *,
    requirement: str = "做一个贪吃蛇游戏",
    sop_mode: SOPMode | None = None,
    source_version_id: str | None = None,
    max_concurrent_calls: int = 2,
):
    store = TaskStore(tmp_path)
    vessel = Vessel(
        provider,
        talents_dir=TALENTS_DIR,
        default_model="test",
        budget_usd=10.0,
        max_concurrent_calls=max_concurrent_calls,
    )
    engine = WorkflowEngine(vessel, store, max_fix_rounds=2)
    record = store.create(
        requirement, sop_mode=sop_mode, source_version_id=source_version_id
    )
    return engine, store, record


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


async def test_scenario_a_simple_change_uses_fast(tmp_path: Path) -> None:
    """A：改背景颜色进入 FAST，总监与营销不调用，但门禁与 Reviewer 必须执行。"""
    provider = ScriptedProvider(
        {"prd": [FAST_PRD_JSON], "game": [GAME_JSON], "review": [REVIEW_PASS]}
    )
    engine, store, record = make_engine(
        tmp_path, provider, requirement="把游戏背景颜色改成蓝色"
    )

    result = await engine.start(record.task_id)

    assert result.status is TaskStatus.COMPLETED
    assert result.sop_mode is SOPMode.FAST
    assert "局部修改" in result.sop_reason
    assert provider.calls == ["prd", "game", "review"]
    assert result.metrics.model_calls == 3
    assert set(result.artifacts) == {"prd.md", "index.html", "gate.json", "review.json"}
    task_dir = tmp_path / record.task_id
    assert (task_dir / "gate.json").exists()
    assert (task_dir / "review.json").exists()
    assert not (task_dir / "marketing_kit.md").exists()
    assert not (task_dir / "creative_proposal.json").exists()

    versions = store.list_versions(record.task_id)
    assert len(versions) == 1
    version = versions[0]
    assert version.sop_mode is SOPMode.FAST
    assert version.conflict_decision is None
    assert version.creative_talent_version is None
    assert version.delivery_talent_version is None
    assert version.source_version_id is None
    assert version.run_id == result.run_id
    assert result.final_version_id == version.version_id
    assert (task_dir / version.artifact_path).exists()


async def test_scenario_b_classic_game_uses_balanced_parallel(tmp_path: Path) -> None:
    """B：经典小游戏进入 BALANCED；两名总监真实并行，COO 必须给出决策。"""
    provider = TrackingProvider(
        script={
            "prd": [DECISION_PRD_JSON],
            "game": [GAME_JSON],
            "review": [REVIEW_PASS],
            "marketing": [MARKETING_JSON],
        }
    )
    engine, store, record = make_engine(
        tmp_path, provider, requirement="开发一个经典贪吃蛇小游戏"
    )

    result = await engine.start(record.task_id)

    assert result.status is TaskStatus.COMPLETED
    assert result.sop_mode is SOPMode.BALANCED
    assert "常规游戏开发" in result.sop_reason
    assert provider.max_active == 2, "两名总监必须真实并行"
    assert "creative_proposal" in provider.calls
    assert "delivery_assessment" in provider.calls
    assert result.metrics.parallel_wall_ms > 0
    assert result.metrics.model_calls == 6  # 双总监 + COO + Engineer + Reviewer + Marketer

    task_dir = tmp_path / record.task_id
    proposal = json.loads((task_dir / "creative_proposal.json").read_text("utf-8"))
    assessment = json.loads(
        (task_dir / "delivery_assessment.json").read_text("utf-8")
    )
    decision = json.loads((task_dir / "conflict_decision.json").read_text("utf-8"))
    assert proposal["innovation"]
    assert assessment["feasibility"] == "feasible"
    assert decision["decision"] == "simplify"
    assert decision["rationale"]
    assert result.conflict_decision is not None
    assert (task_dir / "marketing_kit.md").exists()

    version = store.list_versions(record.task_id)[0]
    assert version.sop_mode is SOPMode.BALANCED
    assert version.conflict_decision is not None
    assert version.creative_talent_version == "baseline"
    assert version.delivery_talent_version == "baseline"

    tool_events = [
        event.data.get("tool")
        for event in result.events
        if event.type.value == "tool.called" and event.agent == "creative"
    ]
    assert set(tool_events) == {"read_requirement", "write_creative"}


async def test_scenario_c_branch_from_history_uses_creative(tmp_path: Path) -> None:
    """C：从历史版本创建分支进入 CREATIVE；最多一轮修订，父版本不被覆盖。"""
    parent_provider = ScriptedProvider(
        {"prd": [FAST_PRD_JSON], "game": [GAME_JSON], "review": [REVIEW_PASS]}
    )
    parent_engine, parent_store, parent_record = make_engine(
        tmp_path, parent_provider, requirement="把游戏背景颜色改成蓝色"
    )
    parent = await parent_engine.start(parent_record.task_id)
    assert parent.status is TaskStatus.COMPLETED
    parent_version = parent_store.list_versions(parent_record.task_id)[0]
    parent_html = tmp_path / parent_record.task_id / parent_version.artifact_path
    before_hash = _sha256(parent_html)

    child_provider = ScriptedProvider(
        {
            "creative_proposal": [CREATIVE_ROUND1, CREATIVE_ROUND2],
            "delivery_assessment": [DELIVERY_RISKY],
            "prd": [DECISION_PRD_JSON],
            "game": [GAME_JSON],
            "review": [REVIEW_PASS],
            "marketing": [MARKETING_JSON],
        }
    )
    child_engine, child_store, child_record = make_engine(
        tmp_path,
        child_provider,
        requirement="基于历史版本做一个新玩法分支",
        source_version_id=parent_version.version_id,
    )

    child = await child_engine.start(child_record.task_id)

    assert child.status is TaskStatus.COMPLETED
    assert child.sop_mode is SOPMode.CREATIVE
    assert parent_version.version_id in child.sop_reason
    assert child_provider.calls.count("creative_proposal") == 2
    assert child_provider.calls.count("delivery_assessment") == 1
    assert child.metrics.model_calls == 7

    resolved = [
        event
        for event in child.events
        if event.type.value == "conflict.resolved"
    ]
    assert resolved and resolved[-1].data["revision_rounds"] == 1

    child_dir = tmp_path / child_record.task_id
    assert (child_dir / "history" / "creative_proposal.round1.json").exists()
    revised = json.loads((child_dir / "creative_proposal.json").read_text("utf-8"))
    assert revised["innovation"] == "背景分三档变色，保留食物高对比度"

    # 父版本完全未被修改
    assert _sha256(parent_html) == before_hash
    assert len(parent_store.list_versions(parent_record.task_id)) == 1

    version = child_store.list_versions(child_record.task_id)[0]
    assert version.source_version_id == parent_version.version_id
    assert version.source_sha256 == before_hash
    assert version.creative_talent_version == "baseline"
    assert version.delivery_talent_version == "baseline"
    assert child.source_sha256 == before_hash
    assert (child_dir / version.artifact_path).exists()

    # 增量修改：Engineer 的上下文必须包含父版本代码
    engineer_context = child_provider.user_prompts["game"][0]
    assert "历史版本参考代码" in engineer_context
    assert GAME_HTML in engineer_context


async def test_delivery_failure_keeps_creative_artifact(tmp_path: Path) -> None:
    """异常恢复：交付总监失败时任务失败，但已产出的创意提案必须保留。"""
    provider = ScriptedProvider(
        {
            "creative_proposal": [CREATIVE_ROUND1],
            "delivery_assessment": [RuntimeError("交付模型不可用")],
        }
    )
    engine, store, record = make_engine(
        tmp_path, provider, requirement="开发一个经典小游戏"
    )

    result = await engine.start(record.task_id)

    assert result.status is TaskStatus.FAILED
    assert "交付模型不可用" in (result.error or "")
    task_dir = tmp_path / record.task_id
    assert (task_dir / "creative_proposal.json").exists()
    assert not (task_dir / "delivery_assessment.json").exists()
    assert not (task_dir / "prd.md").exists()
    assert store.load(record.task_id).status is TaskStatus.FAILED


def test_new_roles_cannot_use_engineering_tools(tmp_path: Path) -> None:
    """角色权限：两名总监不得写游戏或营销文件。"""
    with pytest.raises(ToolPolicyError):
        DEFAULT_REGISTRY.require("creative", "write_game")
    with pytest.raises(ToolPolicyError):
        DEFAULT_REGISTRY.require("delivery", "write_marketing")

    (tmp_path / "creative.yaml").write_text(
        "name: Creative\nrole: x\nsystem_prompt: x\n"
        "output_schema: creative_proposal\n"
        "allowed_tools:\n  - write_game\n",
        encoding="utf-8",
    )
    with pytest.raises(TalentConfigError, match="无权使用"):
        load_talent("creative", tmp_path)


async def test_sop_call_count_comparison(tmp_path: Path) -> None:
    """对比实际调用次数与耗时；Mock/脚本耗时不代表真实网络延迟。"""
    fast_provider = ScriptedProvider(
        {"prd": [FAST_PRD_JSON], "game": [GAME_JSON], "review": [REVIEW_PASS]}
    )
    fast_engine, _, fast_record = make_engine(
        tmp_path, fast_provider, requirement="把背景颜色改成蓝色"
    )
    started = time.perf_counter()
    fast = await fast_engine.start(fast_record.task_id)
    fast_wall = int((time.perf_counter() - started) * 1000)

    balanced_provider = ScriptedProvider(
        {
            "prd": [DECISION_PRD_JSON],
            "game": [GAME_JSON],
            "review": [REVIEW_PASS],
            "marketing": [MARKETING_JSON],
        }
    )
    balanced_engine, _, balanced_record = make_engine(
        tmp_path, balanced_provider, requirement="开发一个经典小游戏"
    )
    started = time.perf_counter()
    balanced = await balanced_engine.start(balanced_record.task_id)
    balanced_wall = int((time.perf_counter() - started) * 1000)

    assert fast.status is TaskStatus.COMPLETED
    assert balanced.status is TaskStatus.COMPLETED
    assert fast.metrics.model_calls == 3
    assert balanced.metrics.model_calls == 6
    # 只记录实际值，不断言新 SOP 一定更快
    assert fast_wall >= 0 and balanced_wall >= 0
    assert fast.metrics.elapsed_ms >= 0 and balanced.metrics.elapsed_ms >= 0
