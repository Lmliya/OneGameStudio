"""员工的输出契约（Pydantic）。

Vessel 解析模型输出后必须能通过这里的校验，否则任务失败。
schema 名称是 Talent YAML 与代码之间的唯一约定。
"""

from typing import Literal

from pydantic import BaseModel, Field


class GamePRD(BaseModel):
    """COO 产出：结构化的游戏需求文档。"""

    title: str
    genre: str
    core_loop: list[str] = Field(min_length=1)
    features: list[str] = Field(min_length=1)
    controls: list[str] = Field(min_length=1)
    win_condition: str
    lose_condition: str


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


class MarketingKit(BaseModel):
    """Marketer 产出：营销素材。"""

    tagline: str
    description: str
    hashtags: list[str] = Field(default_factory=list)
    channels: list[str] = Field(default_factory=list)


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
}
