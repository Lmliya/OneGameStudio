"""任务契约：员工之间传递数据的统一结构（Mini-6 第 1 项 Task Contract）。"""

from datetime import datetime, timezone
from enum import Enum
from uuid import uuid4

from pydantic import BaseModel, Field


class Stage(str, Enum):
    """工作流阶段。由 Python 代码推进，模型无权修改。"""

    DESIGN = "design"
    CODING = "coding"
    REVIEW = "review"
    MARKETING = "marketing"


class TaskStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


def _now() -> datetime:
    return datetime.now(timezone.utc)


class TaskContract(BaseModel):
    """一份任务的完整契约，落盘为 <task_dir>/contract.json。"""

    task_id: str = Field(default_factory=lambda: uuid4().hex[:12])
    requirement: str = Field(min_length=1, description="用户输入的原始游戏需求")
    status: TaskStatus = TaskStatus.PENDING
    stage: Stage = Stage.DESIGN
    artifacts: dict[str, str] = Field(
        default_factory=dict, description="阶段名 -> 产物相对路径"
    )
    created_at: datetime = Field(default_factory=_now)
    updated_at: datetime = Field(default_factory=_now)

    def touch(self) -> None:
        self.updated_at = _now()


class TaskCreateRequest(BaseModel):
    """创建任务的请求体。"""

    requirement: str = Field(min_length=1, description="自然语言游戏需求")
