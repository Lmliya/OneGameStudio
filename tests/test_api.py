"""FastAPI 端点测试（后台执行被替换为空操作，保证测试确定性）。"""

import asyncio
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import backend.main as main
from backend.core.vessel import Vessel
from backend.models.contract import TaskStatus
from backend.providers.mock import MockProvider
from backend.store import TaskStore
from backend.workflow import WorkflowEngine


@pytest.fixture()
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    store = TaskStore(tmp_path)
    engine = WorkflowEngine(
        Vessel(MockProvider(), talents_dir=main._resolve(main.settings.talents_dir),
               default_model="mock", budget_usd=10.0),
        store,
        max_fix_rounds=2,
    )
    monkeypatch.setattr(main, "store", store)
    monkeypatch.setattr(main, "engine", engine)
    monkeypatch.setattr(main, "schedule", lambda task_id: None)
    return TestClient(main.app)


def test_health(client: TestClient) -> None:
    response = client.get("/api/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["mock_mode"] is True


def test_frontend_served(client: TestClient) -> None:
    response = client.get("/")
    assert response.status_code == 200
    assert "OneGameStudio" in response.text


def test_create_task_writes_task_json(client: TestClient, tmp_path: Path) -> None:
    response = client.post("/api/tasks", json={"requirement": "做一个贪吃蛇游戏"})
    assert response.status_code == 202

    body = response.json()
    task_id = body["task_id"]
    assert body["status"] == "pending"
    task_file = tmp_path / task_id / "task.json"
    assert task_file.exists()
    assert "贪吃蛇" in task_file.read_text(encoding="utf-8")


def test_create_task_rejects_empty(client: TestClient) -> None:
    response = client.post("/api/tasks", json={"requirement": ""})
    assert response.status_code == 422


def test_duplicate_active_task_rejected(client: TestClient) -> None:
    first = client.post("/api/tasks", json={"requirement": "做一个贪吃蛇游戏"})
    assert first.status_code == 202
    second = client.post("/api/tasks", json={"requirement": "做一个贪吃蛇游戏"})
    assert second.status_code == 409
    assert second.json()["detail"]["task_id"] == first.json()["task_id"]


def test_get_unknown_task_returns_404(client: TestClient) -> None:
    assert client.get("/api/tasks/not-exist").status_code == 404


def test_get_artifacts_of_new_task_is_empty(client: TestClient) -> None:
    created = client.post("/api/tasks", json={"requirement": "做一个打砖块游戏"})
    task_id = created.json()["task_id"]
    response = client.get(f"/api/tasks/{task_id}/artifacts")
    assert response.status_code == 200
    assert response.json() == {}


def test_background_execution_can_be_scheduled(tmp_path: Path) -> None:
    """不依赖 TestClient，直接验证后台调度能跑完整流程。"""
    store = TaskStore(tmp_path)
    engine = WorkflowEngine(
        Vessel(MockProvider(), talents_dir=main._resolve(main.settings.talents_dir),
               default_model="mock", budget_usd=10.0),
        store,
        max_fix_rounds=2,
    )
    record = store.create("做一个贪吃蛇游戏")

    async def run() -> None:
        await engine.start(record.task_id)

    asyncio.run(run())
    loaded = store.load(record.task_id)
    assert loaded.status.value in {"completed", "needs_attention"}


def test_preview_serves_game_with_isolation_headers(client: TestClient) -> None:
    """预览必须带 CSP，禁止页面联网与访问本站接口。"""
    created = client.post("/api/tasks", json={"requirement": "预览安全测试"})
    task_id = created.json()["task_id"]
    record = main.store.load(task_id)
    main.store.write_artifact(
        record, "index.html", "<html><body><canvas id='c'></canvas></body></html>"
    )

    response = client.get(f"/preview/{task_id}/index.html")

    assert response.status_code == 200
    assert "<canvas" in response.text
    csp = response.headers["content-security-policy"]
    assert "connect-src 'none'" in csp
    assert "default-src 'none'" in csp
    assert response.headers["x-content-type-options"] == "nosniff"


def test_preview_rejects_unlisted_files(client: TestClient) -> None:
    created = client.post("/api/tasks", json={"requirement": "越权读取测试"})
    task_id = created.json()["task_id"]
    record = main.store.load(task_id)
    main.store.write_artifact(record, "task.json", "{}")

    assert client.get(f"/preview/{task_id}/task.json").status_code == 404
    assert client.get(f"/preview/{task_id}/index.html").status_code == 404
    assert client.get("/preview/../etc/passwd").status_code == 404


def test_single_artifact_endpoint(client: TestClient) -> None:
    created = client.post("/api/tasks", json={"requirement": "单文件读取测试"})
    task_id = created.json()["task_id"]
    record = main.store.load(task_id)
    main.store.write_artifact(record, "prd.md", "# 测试 PRD")

    response = client.get(f"/api/tasks/{task_id}/artifacts/prd.md")

    assert response.status_code == 200
    assert "测试 PRD" in response.text
    assert client.get(f"/api/tasks/{task_id}/artifacts/none.md").status_code == 404


def test_history_lists_snapshots(client: TestClient) -> None:
    created = client.post("/api/tasks", json={"requirement": "历史版本测试"})
    task_id = created.json()["task_id"]
    record = main.store.load(task_id)
    main.store.write_artifact(record, "index.html", "<html></html>")
    main.store.snapshot(record, "index.html", "history/index.v1.html")

    response = client.get(f"/api/tasks/{task_id}/history")

    assert response.status_code == 200
    assert response.json() == ["history/index.v1.html"]


def test_websocket_sends_task_snapshot(client: TestClient) -> None:
    """连上即收到快照，断线重连后前端可据此完整恢复界面。"""
    created = client.post("/api/tasks", json={"requirement": "快照测试"})
    task_id = created.json()["task_id"]

    with client.websocket_connect(f"/ws/tasks/{task_id}") as websocket:
        message = websocket.receive_json()

    assert message["type"] == "task.snapshot"
    assert message["task"]["task_id"] == task_id
    assert message["task"]["status"] == "pending"


def test_websocket_rejects_unknown_task(client: TestClient) -> None:
    with client.websocket_connect("/ws/tasks/ffffffffffff") as websocket:
        with pytest.raises(Exception):
            message = websocket.receive_json()
            raise AssertionError(f"不应收到消息：{message}")


def test_websocket_snapshot_has_unified_trace_fields(client: TestClient) -> None:
    created = client.post("/api/tasks", json={"requirement": "字段契约测试"})
    task_id = created.json()["task_id"]

    with client.websocket_connect(f"/ws/tasks/{task_id}") as websocket:
        snapshot = websocket.receive_json()["task"]

    # Harness 5：预算快照字段存在（未执行时为 null）
    assert "budget" in snapshot
    # Harness 1：取消时间字段存在
    assert "cancel_requested_at" in snapshot


def test_cancel_pending_task_sets_cancelled(client: TestClient) -> None:
    """尚未开始执行的任务可直接取消，且状态通过 WS 快照可见。"""
    created = client.post("/api/tasks", json={"requirement": "取消测试"})
    task_id = created.json()["task_id"]

    response = client.post(f"/api/tasks/{task_id}/cancel")

    assert response.status_code == 202
    assert response.json()["status"] == "cancelled"
    with client.websocket_connect(f"/ws/tasks/{task_id}") as websocket:
        snapshot = websocket.receive_json()["task"]
    assert snapshot["status"] == "cancelled"
    assert any(e["type"] == "task.cancelled" for e in snapshot["events"])


def test_cancel_terminal_task_returns_409(client: TestClient) -> None:
    created = client.post("/api/tasks", json={"requirement": "终态取消测试"})
    task_id = created.json()["task_id"]
    record = main.store.load(task_id)
    record.status = TaskStatus.COMPLETED
    main.store.save(record)

    assert client.post(f"/api/tasks/{task_id}/cancel").status_code == 409
