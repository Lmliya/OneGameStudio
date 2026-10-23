"""Talent：定义员工身份、提示词、工具权限、模型与输出契约。"""

from pydantic import BaseModel, Field


class TalentSpec(BaseModel):
    """一个 AI 员工的静态定义。Vessel 负责按此定义执行。"""

    id: str
    name: str
    role: str
    system_prompt: str
    allowed_tools: list[str] = Field(
        default_factory=list, description="允许使用的工具白名单（Tool Policy）"
    )
    model: str = "mock"
    output_artifact: str = Field(default="", description="该员工产出的文件名")
