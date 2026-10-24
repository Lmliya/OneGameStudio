"""员工的输出契约（Pydantic）。

Vessel 解析模型输出后必须能通过这里的校验，否则任务失败。
schema 名称是 Talent YAML 与代码之间的唯一约定。
"""

from typing import Literal

from pydantic import BaseModel, Field, model_validator

from backend.models.sop import ConflictDecision


class GamePRD(BaseModel):
    """COO 产出：结构化的游戏需求文档。

    BALANCED / CREATIVE 下必须附带 conflict_decision；FAST 下为 None。
    """

    title: str
    genre: str
    core_loop: list[str] = Field(min_length=1)
    features: list[str] = Field(min_length=1)
    controls: list[str] = Field(min_length=1)
    win_condition: str
    lose_condition: str
    conflict_decision: ConflictDecision | None = None


class CreativeProposal(BaseModel):
    """Creative Director 产出：最重要的创新建议及其价值与成本。"""

    innovation: str = Field(min_length=1, description="最重要的创新建议")
    player_value: str = Field(min_length=1, description="对玩家的价值")
    complexity: Literal["low", "medium", "high"]
    priority: Literal["high", "medium", "low"]
    rationale: str = Field(min_length=1, description="提出该建议的依据")


class DeliveryAssessment(BaseModel):
    """Delivery Director 产出：最大交付风险与简化建议。"""

    risk: str = Field(min_length=1, description="最大交付风险")
    feasibility: Literal["feasible", "risky", "infeasible"]
    simplification: str = Field(min_length=1, description="简化建议")
    priority: Literal["high", "medium", "low"]
    rationale: str = Field(min_length=1, description="提出该判断的依据")


class GameArtifact(BaseModel):
    """Engineer 产出：单文件 HTML5 游戏。"""

    title: str
    filename: str
    html: str = Field(min_length=1)
    notes: str = ""


class Issue(BaseModel):
    severity: Literal["low", "medium", "high"]
    description: str
    suggestion: str


class ReviewReport(BaseModel):
    """Reviewer 产出：最终裁决。

    verdict 只能由两部分共同决定，机械门禁失败时引擎会强制改为 ITERATE。
    """

    verdict: Literal["PASS", "ITERATE"]
    issues: list[Issue] = Field(default_factory=list)
    suggestions: list[str] = Field(default_factory=list)
    summary: str
    forced_by_gate: bool = Field(
        default=False, description="是否因机械门禁失败被强制改为 ITERATE"
    )


class MarketingPositioning(BaseModel):
    """游戏定位：只说真实存在的功能。"""

    game_name: str
    core_gameplay: str
    one_liner: str
    target_players: str


class XiaohongshuPost(BaseModel):
    """小红书文案。kind 区分体验向与挑战向。"""

    kind: Literal["fun", "challenge"]
    title: str
    body: str
    emojis: list[str] = Field(min_length=1)
    hashtags: list[str] = Field(min_length=1)


class PromotionDay(BaseModel):
    """首周推广计划的一天。"""

    day: int = Field(ge=1, le=7)
    goal: str
    action: str
    assets: list[str] = Field(default_factory=list)
    metrics: list[str] = Field(default_factory=list)


class MarketingKit(BaseModel):
    """Marketer 产出：结构化营销素材，供前端渲染。

    约束：正好 2 篇小红书文案、正好 7 天计划。
    """

    positioning: MarketingPositioning
    slogan: str = Field(min_length=4, max_length=80)
    posts: list[XiaohongshuPost] = Field(min_length=2, max_length=2)
    plan: list[PromotionDay] = Field(min_length=7, max_length=7)

    @model_validator(mode="after")
    def _check_plan(self) -> "MarketingKit":
        days = sorted(item.day for item in self.plan)
        if days != list(range(1, 8)):
            raise ValueError("推广计划必须且只能覆盖 Day 1 至 Day 7")
        return self


class GateCheck(BaseModel):
    """机械门禁的单项检查结果。"""

    id: str
    title: str
    status: Literal["pass", "fail", "unverified"]
    detail: str = ""


class MechanicalReport(BaseModel):
    """第一层：由 Playwright 等确定性手段产出的检查报告。"""

    passed: bool
    checks: list[GateCheck] = Field(default_factory=list)
    blocked_requests: list[str] = Field(default_factory=list)
    duration_ms: int = 0
    engine: str = "playwright"

    @property
    def failed_ids(self) -> list[str]:
        return [c.id for c in self.checks if c.status == "fail"]

    @property
    def unverified_ids(self) -> list[str]:
        return [c.id for c in self.checks if c.status == "unverified"]


OUTPUT_SCHEMAS: dict[str, type[BaseModel]] = {
    "prd": GamePRD,
    "game": GameArtifact,
    "review": ReviewReport,
    "marketing": MarketingKit,
    "creative_proposal": CreativeProposal,
    "delivery_assessment": DeliveryAssessment,
}
