"""AI 员工自进化（阶段 8）。

闭环：任务反馈 -> 提取经验 -> 进化提案 -> 新旧 Talent 评估 -> 用户批准
      -> 启用新 Talent -> 后续任务使用新版本 -> 必要时回滚。

边界：
- 进化只能改提示词、检查清单、非安全性输出偏好；
- 工具权限、输出契约、模型、API Key、质量门禁、预算与文件系统策略不在进化范围内；
- 历史版本文件只增不改，当前启用版本由 active.json 指针决定。
"""

from backend.evolution.errors import (
    EvolutionError,
    EvolutionStateError,
    ImmutableFieldError,
    VersionNotFoundError,
)
from backend.evolution.models import (
    EvaluationReport,
    EvolutionProposal,
    Lesson,
    TalentVersion,
)
from backend.evolution.service import EvolutionService
from backend.evolution.store import EvolutionStore

__all__ = [
    "EvaluationReport",
    "EvolutionError",
    "EvolutionProposal",
    "EvolutionService",
    "EvolutionStateError",
    "EvolutionStore",
    "ImmutableFieldError",
    "Lesson",
    "TalentVersion",
    "VersionNotFoundError",
]
