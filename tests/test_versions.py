"""阶段 9：不可变游戏版本记录与跨任务分支测试。"""

import hashlib
from pathlib import Path

import pytest

from backend.models.sop import SOPMode
from backend.models.version import GameVersion
from backend.store import (
    TaskStore,
    VersionError,
    VersionExistsError,
    VersionNotFoundError,
)


def _version(record, number: int, *, source_version_id: str | None = None) -> GameVersion:
    return GameVersion(
        version_id=f"{record.task_id}-v{number}",
        version_number=number,
        task_id=record.task_id,
        run_id=record.run_id,
        source_version_id=source_version_id,
        sop_mode=SOPMode.BALANCED,
        sop_reason="测试",
        artifact_path=f"versions/{record.task_id}-v{number}.html",
    )


def test_versions_increment_and_never_overwrite(tmp_path: Path) -> None:
    store = TaskStore(tmp_path)
    record = store.create("版本测试")
    assert store.list_versions(record.task_id) == []

    first = _version(record, 1)
    store.save_version(record, first, "<html>v1</html>")
    loaded = store.load(record.task_id)
    assert loaded.final_version_id == first.version_id

    with pytest.raises(VersionExistsError):
        store.save_version(record, first, "<html>覆盖</html>")

    second = _version(record, 2)
    store.save_version(record, second, "<html>v2</html>")
    versions = store.list_versions(record.task_id)
    assert [item.version_number for item in versions] == [1, 2]
    # 第一版内容没有被覆盖
    assert (tmp_path / record.task_id / first.artifact_path).read_text("utf-8") == (
        "<html>v1</html>"
    )


def test_find_version_across_tasks(tmp_path: Path) -> None:
    store = TaskStore(tmp_path)
    parent = store.create("父任务")
    html = "<html><body><canvas></canvas>parent</body></html>"
    version = _version(parent, 1)
    store.save_version(parent, version, html)

    # 另一个任务也能找到父版本
    other = store.create("无关任务")
    found, path = store.find_version(version.version_id)
    assert found.task_id == parent.task_id
    assert path.read_text("utf-8") == html
    assert other.task_id != parent.task_id


def test_create_branch_copies_source_and_hash(tmp_path: Path) -> None:
    store = TaskStore(tmp_path)
    parent = store.create("父任务")
    html = "<html><body><canvas></canvas>父版本</body></html>"
    version = _version(parent, 1)
    store.save_version(parent, version, html)
    before = (tmp_path / parent.task_id / version.artifact_path).read_bytes()

    child = store.create("创新分支", source_version_id=version.version_id)

    assert child.source_version_id == version.version_id
    assert child.source_sha256 == hashlib.sha256(html.encode("utf-8")).hexdigest()
    source_path = (
        tmp_path / child.task_id / "source" / f"{version.version_id}.html"
    )
    assert source_path.exists()
    assert source_path.read_text("utf-8") == html
    assert store.source_game_html(child) == html
    # 父版本文件完全未变
    assert (tmp_path / parent.task_id / version.artifact_path).read_bytes() == before


def test_invalid_version_id_rejected(tmp_path: Path) -> None:
    store = TaskStore(tmp_path)
    for bad in ("../etc/passwd", "abc-v0", "ABCDEF-v1", "x" * 40 + "-v1"):
        with pytest.raises(VersionError):
            store.find_version(bad)


def test_missing_source_version_raises(tmp_path: Path) -> None:
    store = TaskStore(tmp_path)
    with pytest.raises(VersionNotFoundError):
        store.create("分支", source_version_id="abcdef12-v9")
