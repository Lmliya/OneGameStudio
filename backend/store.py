"""任务持久化：所有产物都落在 output/{task_id}/ 下。

规则：只新增文件，不删除已有文件，保证任一阶段失败时已产出的内容不丢失。
"""

from __future__ import annotations

from pathlib import Path

from backend.models.contract import TaskRecord, TaskStatus
from backend.models.events import EventType, TraceEvent

TASK_FILE = "task.json"


class TaskNotFoundError(RuntimeError):
    """任务目录或 task.json 不存在。"""


class TaskStore:
    def __init__(self, root: Path) -> None:
        self.root = root

    def task_dir(self, task_id: str) -> Path:
        return self.root / task_id

    def exists(self, task_id: str) -> bool:
        return (self.task_dir(task_id) / TASK_FILE).exists()

    def create(self, requirement: str, *, max_fix_rounds: int = 2) -> TaskRecord:
        record = TaskRecord(requirement=requirement, max_fix_rounds=max_fix_rounds)
        self.task_dir(record.task_id).mkdir(parents=True, exist_ok=False)
        record.events.append(
            TraceEvent(
                task_id=record.task_id,
                type=EventType.TASK_CREATED,
                stage=record.status.value,
                message="任务已创建",
            )
        )
        self.save(record)
        return record

    def save(self, record: TaskRecord) -> None:
        record.touch()
        directory = self.task_dir(record.task_id)
        directory.mkdir(parents=True, exist_ok=True)
        (directory / TASK_FILE).write_text(
            record.model_dump_json(indent=2), encoding="utf-8"
        )

    def load(self, task_id: str) -> TaskRecord:
        path = self.task_dir(task_id) / TASK_FILE
        if not path.exists():
            raise TaskNotFoundError(f"任务不存在：{task_id}")
        return TaskRecord.model_validate_json(path.read_text(encoding="utf-8"))

    def write_artifact(self, record: TaskRecord, filename: str, content: str) -> str:
        """写入产物并把相对路径登记到 record.artifacts。"""
        directory = self.task_dir(record.task_id)
        directory.mkdir(parents=True, exist_ok=True)
        (directory / filename).write_text(content, encoding="utf-8")
        record.artifacts[filename] = filename
        return filename

    def snapshot(self, record: TaskRecord, source: str, target: str) -> str | None:
        """把已有产物复制到子路径（如 history/index.v1.html），不登记为交付产物。"""
        source_path = self.task_dir(record.task_id) / source
        if not source_path.exists():
            return None
        target_path = self.task_dir(record.task_id) / target
        target_path.parent.mkdir(parents=True, exist_ok=True)
        target_path.write_text(source_path.read_text(encoding="utf-8"), encoding="utf-8")
        return target

    def list_artifacts(self, task_id: str) -> dict[str, str]:
        """返回产物文件名到内容的映射（不含 task.json）。"""
        record = self.load(task_id)
        result: dict[str, str] = {}
        for name in record.artifacts:
            path = self.task_dir(task_id) / name
            if path.exists():
                result[name] = path.read_text(encoding="utf-8")
        return result

    def find_active_by_requirement(self, requirement: str) -> TaskRecord | None:
        """查找同需求且仍在运行的任务，用于拒绝重复提交。"""
        if not self.root.exists():
            return None
        for directory in sorted(self.root.iterdir()):
            if not (directory / TASK_FILE).exists():
                continue
            record = self.load(directory.name)
            if record.requirement == requirement and record.status not in {
                TaskStatus.COMPLETED,
                TaskStatus.FAILED,
                TaskStatus.NEEDS_ATTENTION,
            }:
                return record
        return None
