"""SOP 选择规则。

用户手动选择永远优先；自动选择必须返回可读原因，供任务记录与前端展示。
规则只决定「编码前跑哪些角色」，不决定是否审查：任何模式都必须通过机械门禁与 AI Reviewer。
"""

from __future__ import annotations

from backend.models.sop import SOPMode

# 局部修改：短句且包含明确的改动动作/对象时走 FAST
_FAST_KEYWORDS = (
    "改成",
    "改为",
    "修改",
    "调整",
    "换个",
    "换成",
    "颜色",
    "背景",
    "文案",
    "文字",
    "字体",
    "速度",
    "数值",
    "标题",
    "按钮",
    "音效",
    "难度",
)

# 创新玩法：需要创意与交付双角色协作
_CREATIVE_KEYWORDS = (
    "创新",
    "新玩法",
    "新机制",
    "玩法分支",
    "重新设计",
    "颠覆",
    "创意",
    "分支",
    "重做玩法",
)

_FAST_MAX_LENGTH = 40


def select_sop(
    requirement: str,
    requested: SOPMode | str | None = None,
    *,
    source_version_id: str | None = None,
) -> tuple[SOPMode, str]:
    """返回 (模式, 原因)。原因会写入 task.json 与 sop.selected 事件。"""
    if requested is not None:
        mode = requested if isinstance(requested, SOPMode) else SOPMode(requested)
        return mode, f"用户手动选择 {mode.value.upper()}"

    text = requirement.strip()

    if source_version_id:
        return (
            SOPMode.CREATIVE,
            f"基于历史版本 {source_version_id} 创建创新玩法分支",
        )

    if any(keyword in text for keyword in _CREATIVE_KEYWORDS):
        return SOPMode.CREATIVE, "需求包含创新玩法关键词，需要创意与交付双角色协作"

    if len(text) <= _FAST_MAX_LENGTH and any(
        keyword in text for keyword in _FAST_KEYWORDS
    ):
        return SOPMode.FAST, "需求为短句局部修改，适用极速流程"

    return SOPMode.BALANCED, "常规游戏开发需求，走标准评审流程"
