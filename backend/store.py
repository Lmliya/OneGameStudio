"""任务持久化：所有产物都落在 output/{task_id}/ 下。

规则：只新增文件，不删除已有文件，保证任一阶段失败时已产出的内容不丢失。
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

from backend.models.contract import TERMINAL_STATUSES, TaskRecord
from backend.models.events import EventType, TraceEvent
from backend.models.sop import SOPMode
from backend.models.version import GameVersion

TASK_FILE = "task.json"
VERSIONS_DIR = "versions"
SOURCE_DIR = "source"
_VERSION_ID_RE = re.compile(r"^[0-9a-f]{6,32}-v[1-9]\d*$")


class TaskNotFoundError(RuntimeError):
    """任务目录或 task.json 不存在。"""


class VersionError(RuntimeError):
    """游戏版本记录非法。"""


class VersionNotFoundError(VersionError):
    """请求的游戏版本不存在。"""


class VersionExistsError(VersionError):
    """目标版本已存在；历史版本不可覆盖。"""


class TaskStore:
    def __init__(self, root: Path) -> None:
        self.root = root

    def task_dir(self, task_id: str) -> Path:
        return self.root / task_id

    def exists(self, task_id: str) -> bool:
        return (self.task_dir(task_id) / TASK_FILE).exists()

    def create(
        self,
        requirement: str,
        *,
        max_fix_rounds: int = 2,
        sop_mode: SOPMode | None = None,
        source_version_id: str | None = None,
    ) -> TaskRecord:
        record = TaskRecord(
            requirement=requirement,
            max_fix_rounds=max_fix_rounds,
            sop_mode=sop_mode,
            source_version_id=source_version_id,
        )
        self.task_dir(record.task_id).mkdir(parents=True, exist_ok=False)

        if source_version_id:
            version, source_path = self.find_version(source_version_id)
            html = source_path.read_text(encoding="utf-8")
            record.source_sha256 = _sha256(html)
            source_dir = self.task_dir(record.task_id) / SOURCE_DIR
            source_dir.mkdir(parents=True, exist_ok=True)
            (source_dir / f"{version.version_id}.html").write_text(
                html, encoding="utf-8"
            )

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
        """原子写入 task.json，避免进程中断留下半截文件。"""
        record.touch()
        directory = self.task_dir(record.task_id)
        directory.mkdir(parents=True, exist_ok=True)
        target = directory / TASK_FILE
        tmp = directory / f"{TASK_FILE}.tmp"
        tmp.write_text(record.model_dump_json(indent=2), encoding="utf-8")
        tmp.replace(target)

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

    # ---------- 阶段 9：游戏版本 ----------

    def versions_dir(self, task_id: str) -> Path:
        return self.task_dir(task_id) / VERSIONS_DIR

    def list_versions(self, task_id: str) -> list[GameVersion]:
        directory = self.versions_dir(task_id)
        if not directory.exists():
            return []
        versions: list[GameVersion] = []
        for path in sorted(directory.glob("*.json")):
            if path.is_symlink() or not path.is_file():
                raise VersionError(f"非法版本文件：{path}")
            version = GameVersion.model_validate_json(path.read_text(encoding="utf-8"))
            if version.task_id != task_id:
                raise VersionError(f"版本 {version.version_id} 与任务目录不一致")
            versions.append(version)
        return sorted(versions, key=lambda item: item.version_number)

    def next_version_number(self, task_id: str) -> int:
        versions = self.list_versions(task_id)
        return max((item.version_number for item in versions), default=0) + 1

    def save_version(
        self, record: TaskRecord, version: GameVersion, html: str
    ) -> GameVersion:
        """写入不可变版本快照；目标已存在时拒绝覆盖。"""
        if version.task_id != record.task_id:
            raise VersionError("版本记录与任务不匹配")
        if not _VERSION_ID_RE.match(version.version_id):
            raise VersionError(f"非法版本 ID：{version.version_id}")

        directory = self.versions_dir(record.task_id)
        directory.mkdir(parents=True, exist_ok=True)
        html_path = directory / f"{version.version_id}.html"
        json_path = directory / f"{version.version_id}.json"
        if html_path.exists() or json_path.exists():
            raise VersionExistsError(f"版本已存在，拒绝覆盖：{version.version_id}")

        html_path.write_text(html, encoding="utf-8")
        json_path.write_text(version.model_dump_json(indent=2), encoding="utf-8")
        record.final_version_id = version.version_id
        self.save(record)
        return version

    def find_version(self, version_id: str) -> tuple[GameVersion, Path]:
        """跨任务查找版本，返回记录与 HTML 快照路径。"""
        if not _VERSION_ID_RE.match(version_id):
            raise VersionError(f"非法版本 ID：{version_id}")
        if not self.root.exists():
            raise VersionNotFoundError(f"版本不存在：{version_id}")

        for directory in sorted(self.root.iterdir()):
            if not directory.is_dir() or directory.is_symlink():
                continue
            json_path = directory / VERSIONS_DIR / f"{version_id}.json"
            if not json_path.is_file() or json_path.is_symlink():
                continue
            version = GameVersion.model_validate_json(
                json_path.read_text(encoding="utf-8")
            )
            if version.task_id != directory.name:
                raise VersionError(f"版本 {version_id} 与任务目录不一致")
            html_path = directory / VERSIONS_DIR / f"{version_id}.html"
            if not html_path.is_file() or html_path.is_symlink():
                raise VersionNotFoundError(f"版本快照缺失：{version_id}")
            if not _inside_root(html_path, self.root):
                raise VersionError(f"版本快照越界：{version_id}")
            return version, html_path

        raise VersionNotFoundError(f"版本不存在：{version_id}")

    def source_game_html(self, record: TaskRecord) -> str | None:
        """读取分支任务在创建时复制的父版本 HTML。"""
        if not record.source_version_id:
            return None
        path = self.task_dir(record.task_id) / SOURCE_DIR / (
            f"{record.source_version_id}.html"
        )
        if not path.is_file():
            return None
        return path.read_text(encoding="utf-8")

    def find_active_by_requirement(self, requirement: str) -> TaskRecord | None:
        """查找同需求且仍在运行的任务，用于拒绝重复提交。"""
        if not self.root.exists():
            return None
        for directory in sorted(self.root.iterdir()):
            if not (directory / TASK_FILE).exists():
                continue
            record = self.load(directory.name)
            if (
                record.requirement == requirement
                and record.status not in TERMINAL_STATUSES
            ):
                return record
        return None


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _inside_root(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
    except ValueError:
        return False
    return True
