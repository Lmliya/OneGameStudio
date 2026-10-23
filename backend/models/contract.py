"""任务数据模型：状态、记录与创建请求。

工作流状态只能由 Python 状态机推进，模型无权修改。
"""

from datetime import datetime, timezone
from enum import Enum
from uuid import uuid4

from pydantic import BaseModel, Field

from backend.models.events import TraceEvent


class TaskStatus(str, Enum):
    """任务状态。终态：completed / failed / needs_attention。"""

    PENDING = "pending"
    PLANNING = "planning"
    CODING = "coding"
    REVIEWING = "reviewing"
    FIXING = "fixing"
    MARKETING = "marketing"
    COMPLETED = "completed"
    FAILED = "failed"
    NEEDS_ATTENTION = "needs_attention"


TERMINAL_STATUSES: frozenset[TaskStatus] = frozenset(
    {TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.NEEDS_ATTENTION}
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
    created_at: datetime = Field(default_factory=_now)
    updated_at: datetime = Field(default_factory=_now)

    @property
    def is_terminal(self) -> bool:
        return self.status in TERMINAL_STATUSES

    def touch(self) -> None:
        self.updated_at = _now()


class TaskCreateRequest(BaseModel):
    """创建任务的请求体。"""

    requirement: str = Field(min_length=1, description="自然语言游戏需求")
