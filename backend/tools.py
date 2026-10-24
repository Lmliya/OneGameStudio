"""Harness 2：Tool Policy（工具权限）。

规则：
- 工具必须在这里**显式注册**，注册表是唯一真相。
- 每名员工只能使用角色授权范围内的工具；加载配置时校验一次，运行时再校验一次。
- 不注册任何 shell / subprocess / 任意代码执行工具：模型输出永远不能变成命令。
"""

from __future__ import annotations

from collections.abc import Iterable

from pydantic import BaseModel, Field

# 工具名里出现这些片段一律视为危险能力，注册表构造时直接拒绝
_FORBIDDEN_PREFIXES = ("shell", "exec", "subprocess", "system", "eval")


class ToolPolicyError(RuntimeError):
    """员工申请了未注册或越权的工具。"""


class ToolSpec(BaseModel):
    """一个可被员工调用的工具及其授权角色。"""

    name: str
    description: str
    allowed_agents: frozenset[str] = Field(default_factory=frozenset)


TOOL_SPECS: tuple[ToolSpec, ...] = (
    ToolSpec(
        name="read_requirement",
        description="读取用户原始需求",
        allowed_agents=frozenset({"coo", "creative", "delivery"}),
    ),
    ToolSpec(
        name="write_prd",
        description="写入 PRD 文档 prd.md",
        allowed_agents=frozenset({"coo"}),
    ),
    ToolSpec(
        name="write_decision",
        description="写入冲突决策 conflict_decision.json",
        allowed_agents=frozenset({"coo"}),
    ),
    ToolSpec(
        name="read_prd",
        description="读取 PRD 作为上下文",
        allowed_agents=frozenset(
            {"engineer", "backup_engineer", "marketer", "creative", "delivery"}
        ),
    ),
    ToolSpec(
        name="write_game",
        description="写入游戏文件 index.html",
        allowed_agents=frozenset({"engineer", "backup_engineer"}),
    ),
    ToolSpec(
        name="read_review",
        description="读取审查报告作为修复依据",
        allowed_agents=frozenset({"engineer", "backup_engineer", "marketer"}),
    ),
    ToolSpec(
        name="read_game",
        description="读取待审查或待参考的游戏代码",
        allowed_agents=frozenset({"reviewer", "creative"}),
    ),
    ToolSpec(
        name="run_tests",
        description="运行机械门禁（Playwright 确定性检查）",
        allowed_agents=frozenset({"reviewer"}),
    ),
    ToolSpec(
        name="write_review",
        description="写入审查结论 review.json",
        allowed_agents=frozenset({"reviewer"}),
    ),
    ToolSpec(
        name="write_marketing",
        description="写入营销素材 marketing_kit.md / marketing_kit.json",
        allowed_agents=frozenset({"marketer"}),
    ),
    ToolSpec(
        name="write_creative",
        description="写入创意提案 creative_proposal.json",
        allowed_agents=frozenset({"creative"}),
    ),
    ToolSpec(
        name="write_delivery",
        description="写入交付评估 delivery_assessment.json",
        allowed_agents=frozenset({"delivery"}),
    ),
)


def _build_role_tools(specs: Iterable[ToolSpec]) -> dict[str, frozenset[str]]:
    mapping: dict[str, set[str]] = {}
    for spec in specs:
        for agent in spec.allowed_agents:
            mapping.setdefault(agent, set()).add(spec.name)
    return {agent: frozenset(tools) for agent, tools in mapping.items()}


ROLE_TOOLS: dict[str, frozenset[str]] = _build_role_tools(TOOL_SPECS)


class ToolRegistry:
    """显式工具注册表：注册、查询与运行时校验。"""

    def __init__(self, specs: Iterable[ToolSpec]) -> None:
        self._specs: dict[str, ToolSpec] = {}
        for spec in specs:
            lowered = spec.name.lower()
            if any(lowered.startswith(prefix) for prefix in _FORBIDDEN_PREFIXES):
                raise ToolPolicyError(f"禁止注册危险工具：{spec.name}")
            if spec.name in self._specs:
                raise ToolPolicyError(f"工具重复注册：{spec.name}")
            self._specs[spec.name] = spec
        self._role_tools = _build_role_tools(self._specs.values())

    def names(self) -> frozenset[str]:
        return frozenset(self._specs)

    def allowed_for(self, agent: str) -> frozenset[str]:
        return self._role_tools.get(agent, frozenset())

    def require(self, agent: str, tool: str) -> None:
        """运行时拦截：未注册工具与越权工具都直接拒绝。"""
        if tool not in self._specs:
            raise ToolPolicyError(f"未注册的工具：{tool}")
        if agent not in self._specs[tool].allowed_agents:
            raise ToolPolicyError(
                f"{agent} 无权使用工具 {tool}（授权："
                f"{sorted(self._specs[tool].allowed_agents)}）"
            )

    def tools_of(self, agent: str) -> list[ToolSpec]:
        return [spec for spec in self._specs.values() if agent in spec.allowed_agents]


DEFAULT_REGISTRY = ToolRegistry(TOOL_SPECS)
