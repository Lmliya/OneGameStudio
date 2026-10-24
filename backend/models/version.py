"""游戏版本记录。

历史版本只增不改：每个任务完成后生成一份不可变记录，包含本次 Run 的 SOP、
冲突决策、双总监 Talent 版本与来源版本。分支任务通过 source_version_id 指向父版本。
"""

from datetime import datetime, timezone

from pydantic import BaseModel, Field

from backend.models.sop import ConflictDecision, SOPMode


def _now() -> datetime:
    return datetime.now(timezone.utc)


class GameVersion(BaseModel):
    version_id: str = Field(description="服务端生成：{task_id}-v{n}")
    version_number: int = Field(ge=1)
    task_id: str
    run_id: str
    parent_version_id: str | None = Field(
        default=None, description="同一任务内的上一版本（首个版本为 None）"
    )
    source_version_id: str | None = Field(
        default=None, description="分支任务所引用的历史版本"
    )
    source_sha256: str | None = None
    sop_mode: SOPMode
    sop_reason: str
    conflict_decision: ConflictDecision | None = None
    creative_talent_version: str | None = None
    delivery_talent_version: str | None = None
    artifact_path: str = Field(description="相对任务目录的 HTML 快照路径")
    created_at: datetime = Field(default_factory=_now)
