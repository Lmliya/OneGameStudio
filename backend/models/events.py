"""事件记录（Mini-6 第 6 项 Event Trace）。"""

from datetime import datetime, timezone
from enum import Enum

from pydantic import BaseModel, Field


class EventType(str, Enum):
    TASK_CREATED = "task_created"
    STAGE_STARTED = "stage_started"
    STAGE_COMPLETED = "stage_completed"
    STAGE_FAILED = "stage_failed"
    FIX_REQUESTED = "fix_requested"


class TraceEvent(BaseModel):
    task_id: str
    type: EventType
    stage: str
    message: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    data: dict = Field(default_factory=dict)


class Tracer:
    """内存事件记录器。阶段 3 会替换为可落盘的实现。"""

    def __init__(self) -> None:
        self.events: list[TraceEvent] = []

    def record(self, event: TraceEvent) -> None:
        self.events.append(event)
