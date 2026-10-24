"""阶段 10：Demo / Live 双模式与公开访问安全限制。"""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend import main
from backend.core.vessel import Vessel
from backend.providers.mock import MockProvider
from backend.store import TaskStore
from backend.workflow import WorkflowEngine


@pytest.fixture()
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    store = TaskStore(tmp_path)
    engine = WorkflowEngine(
        Vessel(
            MockProvider(),
            talents_dir=main._resolve(main.settings.talents_dir),
            default_model="mock",
            budget_usd=10.0,
        ),
        store,
        max_fix_rounds=2,
    )
    monkeypatch.setattr(main, "store", store)
    monkeypatch.setattr(main, "engine", engine)
    monkeypatch.setattr(main, "schedule", lambda task_id: None)
    main._submissions.clear()
    yield TestClient(main.app)
    main._submissions.clear()


def test_demo_read_only_blocks_new_tasks(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(main.settings, "app_mode", "demo")
    monkeypatch.setattr(main.settings, "demo_read_only", True)

    response = client.post("/api/tasks", json={"requirement": "演示期间不应新建"})

    assert response.status_code == 403
    assert "只读" in response.json()["detail"]


def test_live_without_key_refuses_task(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(main.settings, "app_mode", "live")
    monkeypatch.setattr(main.settings, "mock_mode", False)
    monkeypatch.setattr(main.settings, "llm_api_key", "")
    monkeypatch.setattr(main.settings, "llm_model", "test-model")

    response = client.post("/api/tasks", json={"requirement": "真实模型任务"})

    assert response.status_code == 503
    assert "LLM_API_KEY" in response.json()["detail"]


def test_live_requires_access_token(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(main.settings, "app_mode", "live")
    monkeypatch.setattr(main.settings, "mock_mode", False)
    monkeypatch.setattr(main.settings, "llm_api_key", "server-side-key")
    monkeypatch.setattr(main.settings, "llm_model", "test-model")
    monkeypatch.setattr(main.settings, "access_token", "secret-token")

    denied = client.post("/api/tasks", json={"requirement": "未授权任务"})
    assert denied.status_code == 401

    allowed = client.post(
        "/api/tasks",
        json={"requirement": "已授权任务"},
        headers={"X-OGS-Token": "secret-token"},
    )
    assert allowed.status_code == 202
    assert allowed.json()["requirement"] == "已授权任务"


def test_access_token_protects_evolution_writes(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """公开部署时，未授权请求不能修改 Talent 安全配置。"""
    monkeypatch.setattr(main.settings, "access_token", "secret-token")

    denied = client.post("/api/evolution/proposals", json={})
    assert denied.status_code == 401

    allowed = client.post(
        "/api/evolution/proposals",
        json={},
        headers={"X-OGS-Token": "secret-token"},
    )
    # 通过鉴权后由业务层校验参数，不应再返回 401
    assert allowed.status_code != 401


def test_health_reports_mode(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(main.settings, "app_mode", "demo")
    monkeypatch.setattr(main.settings, "demo_read_only", True)

    body = client.get("/api/health").json()

    assert body["mode"] == "demo"
    assert body["read_only"] is True
    assert body["live_ready"] is False


def test_demo_endpoint_lists_committed_tasks(client: TestClient) -> None:
    """Demo 数据来自随仓库提交的 demo/tasks，而不是用户本地 output。"""
    body = client.get("/api/demo").json()

    assert body["tasks"], "仓库必须包含至少一个预验证演示任务"
    task = body["tasks"][0]
    assert task["status"] == "completed"
    assert task["task_id"] and task["name"]
    # 演示任务可以被只读查询
    detail = client.get(f"/api/tasks/{task['task_id']}")
    assert detail.status_code == 200
    versions = client.get(f"/api/tasks/{task['task_id']}/versions").json()
    assert versions
