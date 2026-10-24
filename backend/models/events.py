"""事件记录（Mini-6 第 6 项 Event Trace）。

事件同时用于三处：落盘任务快照、WebSocket 实时推送、前端日志展示。
统一字段：task_id / agent / type / created_at / duration_ms / model /
token_usage / result / error，避免各调用点各自把信息塞进 data。
"""

from datetime import datetime, timezone
from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field


class EventType(str, Enum):
    """事件类型。取值直接作为 WebSocket 消息的 type 字段。"""

    TASK_CREATED = "task.created"
    TASK_STATUS_CHANGED = "task.status_changed"
    AGENT_STATUS_CHANGED = "agent.status_changed"
    TOOL_CALLED = "tool.called"
    ARTIFACT_CREATED = "artifact.created"
    FIX_REQUESTED = "fix.requested"
    REVIEW_COMPLETED = "review.completed"
    BUDGET_UPDATED = "budget.updated"
    # 阶段 9：SOP 与冲突协作
    SOP_SELECTED = "sop.selected"
    CONFLICT_OPINION = "conflict.opinion"
    CONFLICT_RESOLVED = "conflict.resolved"
    TASK_COMPLETED = "task.completed"
    TASK_FAILED = "task.failed"
    TASK_CANCELLED = "task.cancelled"

    # Vessel 内部调用轨迹（不推送给前端）
    STAGE_STARTED = "stage.started"
    STAGE_COMPLETED = "stage.completed"
    STAGE_FAILED = "stage.failed"

    @classmethod
    def _missing_(cls, value: object) -> "EventType | None":
        """兼容阶段 1–4 落盘的历史事件名，保证旧任务仍能读取。"""
        legacy = {
            "task_created": "task.created",
            "state_changed": "task.status_changed",
            "stage_started": "task.status_changed",
            "stage_completed": "task.status_changed",
            "stage_failed": "task.failed",
            "fix_requested": "fix.requested",
            "task_completed": "task.completed",
            "task_failed": "task.failed",
        }
        if isinstance(value, str) and value in legacy:
            return cls(legacy[value])
        return None


class AgentStatus(str, Enum):
    """员工状态。只由后端事件写入，前端不做任何推断。"""

    IDLE = "idle"
    WORKING = "working"
    REVIEWING = "reviewing"
    FIXING = "fixing"
    COMPLETED = "completed"
    ERROR = "error"


class TokenUsage(BaseModel):
    """一次模型调用的 token 用量。

    source 说明用量可信度：
    - provider：接口真实返回的 usage
    - estimated：按字符数估算（Mock）
    - unknown：接口没有返回用量，一律记 0 并标记未知，不做猜测
    """

    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    source: Literal["provider", "estimated", "unknown"] = "unknown"

    @classmethod
    def of(
        cls,
        input_tokens: int,
        output_tokens: int,
        source: Literal["provider", "estimated", "unknown"],
    ) -> "TokenUsage":
        return cls(
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=input_tokens + output_tokens,
            source=source,
        )


EventResult = Literal["ok", "failed", "skipped"]


class TraceEvent(BaseModel):
    task_id: str
    type: EventType
    message: str
    agent: str | None = None
    status: str | None = None
    stage: str = ""
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    data: dict = Field(default_factory=dict)

    # ---- Harness 6：统一追踪字段（可选，向后兼容历史事件） ----
    model: str | None = None
    duration_ms: int | None = None
    token_usage: TokenUsage | None = None
    result: EventResult | None = None
    error: str | None = None

    def as_message(self) -> dict:
        """转成 WebSocket 消息体。"""
        return {
            "type": self.type.value,
            "task_id": self.task_id,
            "agent": self.agent,
            "status": self.status,
            "stage": self.stage,
            "message": self.message,
            "ts": self.created_at.isoformat(),
            "data": self.data,
            "model": self.model,
            "duration_ms": self.duration_ms,
            "token_usage": (
                self.token_usage.model_dump() if self.token_usage is not None else None
            ),
            "result": self.result,
            "error": self.error,
        }


class Tracer:
    """内存事件记录器，供 Vessel 记录单次调用轨迹。"""

    def __init__(self) -> None:
        self.events: list[TraceEvent] = []

    def record(self, event: TraceEvent) -> None:
        self.events.append(event)
