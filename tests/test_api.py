"""FastAPI 端点的测试。"""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.main import app, settings


@pytest.fixture()
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    """把产物目录指向临时目录，避免污染项目 output/。"""
    monkeypatch.setattr(settings, "output_dir", tmp_path)
    return TestClient(app)


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


def test_create_task_writes_contract(client: TestClient, tmp_path: Path) -> None:
    response = client.post("/api/tasks", json={"requirement": "做一个贪吃蛇游戏"})
    assert response.status_code == 200

    body = response.json()
    task_id = body["task_id"]
    contract_file = tmp_path / "tasks" / task_id / "contract.json"
    assert contract_file.exists()
    assert "贪吃蛇" in contract_file.read_text(encoding="utf-8")


def test_create_task_rejects_empty(client: TestClient) -> None:
    response = client.post("/api/tasks", json={"requirement": ""})
    assert response.status_code == 422
