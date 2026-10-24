"""任务数据模型：状态、记录与创建请求。

工作流状态只能由 Python 状态机推进，模型无权修改。
"""

from datetime import datetime, timezone
from enum import Enum
from uuid import uuid4

from pydantic import BaseModel, Field

from backend.budget import TaskBudget
from backend.models.events import TraceEvent
from backend.models.sop import ConflictDecision, RunMetrics, SOPMode


class TaskStatus(str, Enum):
    """任务状态。终态：completed / failed / needs_attention / cancelled。"""

    PENDING = "pending"
    PLANNING = "planning"
    CODING = "coding"
    REVIEWING = "reviewing"
    FIXING = "fixing"
    MARKETING = "marketing"
    COMPLETED = "completed"
    FAILED = "failed"
    NEEDS_ATTENTION = "needs_attention"
    CANCELLED = "cancelled"


TERMINAL_STATUSES: frozenset[TaskStatus] = frozenset(
    {
        TaskStatus.COMPLETED,
        TaskStatus.FAILED,
        TaskStatus.NEEDS_ATTENTION,
        TaskStatus.CANCELLED,
    }
)


def _now() -> datetime:
    return datetime.now(timezone.utc)


class TaskRecord(BaseModel):
    """一个任务的完整记录，落盘为 output/{task_id}/task.json。"""

    task_id: str = Field(default_factory=lambda: uuid4().hex[:12])
    requirement: str = Field(min_length=1, description="用户输入的原始游戏需求")
    status: TaskStatus = TaskStatus.PENDING
    fix_attempts: int = Field(default=0, description="已执行的修复轮次")
    max_fix_rounds: int = Field(default=2, description="允许的最大修复轮次")
    artifacts: dict[str, str] = Field(
        default_factory=dict, description="文件名 -> 相对路径"
    )
    events: list[TraceEvent] = Field(default_factory=list)
    error: str | None = None
    # Harness 5：本任务预算快照（估算，不是账单）
    budget: TaskBudget | None = None
    # Harness 4：取消请求时间，便于追溯「谁在什么时候取消了任务」
    cancel_requested_at: datetime | None = None
    # 阶段 8：本次 Run 实际使用的 Talent 版本（agent -> "reviewer@v2"）
    talent_versions: dict[str, str] = Field(default_factory=dict)
    # 阶段 9：SOP、冲突决策、版本与真实执行指标
    sop_mode: SOPMode | None = Field(
        default=None, description="运行开始时由手动选择或后端规则确定"
    )
    sop_reason: str = Field(default="", description="为什么选择该 SOP")
    source_version_id: str | None = Field(
        default=None, description="分支任务所引用的历史游戏版本"
    )
    source_sha256: str | None = None
    run_id: str = Field(
        default_factory=lambda: uuid4().hex[:12], description="一次执行 Run 的唯一标识"
    )
    final_version_id: str | None = None
    conflict_decision: ConflictDecision | None = None
    creative_talent_version: str | None = None
    delivery_talent_version: str | None = None
    metrics: RunMetrics = Field(default_factory=RunMetrics)
    created_at: datetime = Field(default_factory=_now)
    updated_at: datetime = Field(default_factory=_now)

    @property
    def is_terminal(self) -> bool:
        return self.status in TERMINAL_STATUSES

    def touch(self) -> None:
        self.updated_at = _now()


class TaskCreateRequest(BaseModel):
    """创建任务的请求体。

    sop_mode 为空时由后端规则自动选择；source_version_id 用于从历史版本创建创新分支。
    """

    requirement: str = Field(min_length=1, description="自然语言游戏需求")
    sop_mode: SOPMode | None = Field(
        default=None, description="手动指定 FAST/BALANCED/CREATIVE；为空则自动选择"
    )
    source_version_id: str | None = Field(
        default=None, description="可选：父游戏版本 ID，用于增量分支"
    )
