"""Talent：定义员工身份、提示词、工具权限、模型与输出契约。

Talent 是纯数据，不知道任何模型细节；模型名留空时由 Vessel 使用全局默认模型。
"""

from pydantic import BaseModel, Field


class TalentSpec(BaseModel):
    id: str
    name: str
    role: str
    system_prompt: str
    checklist: list[str] = Field(
        default_factory=list, description="工作检查清单，会随提示词一起注入；可由进化版本替换"
    )
    version: int = Field(
        default=0, description="运行期实际使用的 Talent 版本号；0 表示基线（YAML 原样）"
    )
    model: str | None = Field(
        default=None, description="为空则使用全局 LLM_MODEL，允许不同员工用不同模型"
    )
    allowed_tools: list[str] = Field(
        default_factory=list, description="工具白名单，未授权工具会在加载时被拒绝"
    )
    output_schema: str = Field(description="输出契约名，必须是已注册的 schema")
