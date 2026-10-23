"""四个员工的输出契约（Pydantic）。

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
    """Reviewer 产出：问题清单与结论。"""

    score: int = Field(ge=0, le=100)
    passed: bool
    issues: list[Issue] = Field(default_factory=list)


class MarketingKit(BaseModel):
    """Marketer 产出：营销素材。"""

    tagline: str
    description: str
    hashtags: list[str] = Field(default_factory=list)
    channels: list[str] = Field(default_factory=list)


OUTPUT_SCHEMAS: dict[str, type[BaseModel]] = {
    "prd": GamePRD,
    "game": GameArtifact,
    "review": ReviewReport,
    "marketing": MarketingKit,
}
