"""FastAPI 端点测试（后台执行被替换为空操作，保证测试确定性）。"""

import asyncio
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import backend.main as main
from backend.core.vessel import Vessel
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
