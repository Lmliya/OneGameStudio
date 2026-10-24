"""阶段 8：AI 员工自进化的测试。

覆盖：版本注册与不可变、经验证据门槛、提案安全边界、回归评估、
用户批准启用、回滚、任务记录实际 Talent 版本、经验提取与 HTTP API。
"""

from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError

from backend.core.vessel import Vessel
from backend.evolution.api import create_evolution_router
from backend.evolution.errors import (
    EvolutionError,
    EvolutionStateError,
    ImmutableFieldError,
)
from backend.evolution.models import EvolutionProposal, Lesson
from backend.evolution.service import EvolutionService
from backend.evolution.store import EvolutionStore
from backend.models.contract import TaskStatus
from backend.providers.mock import MockProvider
from backend.store import TaskStore
from backend.workflow import WorkflowEngine

TALENTS_DIR = Path(__file__).resolve().parents[1] / "talents"


@pytest.fixture()
def evo(tmp_path: Path) -> tuple[EvolutionStore, EvolutionService]:
    store = EvolutionStore(tmp_path / "evolution", TALENTS_DIR)
    store.ensure_seeded()
    return store, EvolutionService(store, mock_mode=True)


def _approved_reviewer(service: EvolutionService):
    """完整走一遍诊断 -> 提案 -> 评估 -> 批准，返回提案与 v2。"""
    _, lessons = service.diagnose("reviewer")
    proposal, _ = service.create_proposal(
        "reviewer", [item.lesson_id for item in lessons]
    )
    service.evaluate(proposal.proposal_id)
    _, activated = service.approve(proposal.proposal_id)
    return proposal, activated


# ---------- 版本 ----------


def test_seed_registers_v1_for_all_talents(evo) -> None:
    store, _ = evo
    assert store.talent_names() == ["coo", "engineer", "marketer", "reviewer"]
    for name in store.talent_names():
        versions = store.versions(name)
        assert len(versions) == 1
        assert versions[0].version == 1
        assert versions[0].status == "active"
        assert versions[0].prompt == store.baseline(name).system_prompt
        assert versions[0].checklist == store.baseline(name).checklist


def test_seed_is_idempotent(evo) -> None:
    store, _ = evo
    store.ensure_seeded()
    store.ensure_seeded()
    assert len(store.versions("reviewer")) == 1
    assert store.active_version("reviewer").version == 1


def test_verified_lesson_requires_evidence() -> None:
    with pytest.raises(ValidationError):
        Lesson(related_talent="reviewer", problem="p", improvement="i", status="verified")


def test_proposal_rejects_protected_changes() -> None:
    with pytest.raises(ValidationError):
        EvolutionProposal(
            target_talent="reviewer",
            base_version=1,
            proposed_changes={"allowed_tools": ["shell"]},
            supporting_evidence=["lesson_x"],
        )


def test_candidate_cannot_activate_without_approval(evo) -> None:
    store, service = evo
    _, lessons = service.diagnose("reviewer")
    proposal, candidate = service.create_proposal(
        "reviewer", [item.lesson_id for item in lessons]
    )
    with pytest.raises(EvolutionStateError):
        store.activate(
            "reviewer",
            candidate.version,
            reason="绕过审批",
            proposal_id=proposal.proposal_id,
        )


# ---------- 经验与诊断 ----------


def test_diagnose_creates_verified_lessons_from_regression(evo) -> None:
    _, service = evo
    report, lessons = service.diagnose("reviewer")
    assert report.engine == "mock"
    assert report.base.detection_rate < 1.0
    assert report.cases
    assert len(lessons) == 4
    for lesson in lessons:
        assert lesson.status == "verified"
        assert lesson.verification
        assert lesson.related_talent == "reviewer"
        assert lesson.source_run_id == report.evaluation_id


def test_diagnose_is_idempotent_for_lessons(evo) -> None:
    store, service = evo
    _, first = service.diagnose("reviewer")
    _, second = service.diagnose("reviewer")
    assert len(first) == 4
    assert second == []
    assert len(store.list_lessons("reviewer")) == 4


def test_proposal_requires_verified_lessons(evo) -> None:
    store, service = evo
    candidate_lesson = store.add_lesson(
        Lesson(
            related_talent="reviewer",
            problem="模型主观猜测",
            improvement="也许要检查网络",
            status="candidate",
        )
    )
    with pytest.raises(EvolutionStateError):
        service.create_proposal("reviewer", [candidate_lesson.lesson_id])


def test_candidate_lesson_can_be_verified_manually(evo) -> None:
    store, service = evo
    lesson = store.add_lesson(
        Lesson(
            related_talent="engineer",
            problem="暂停失效",
            improvement="补充暂停逻辑",
            status="candidate",
        )
    )
    with pytest.raises(EvolutionError):
        service.verify_lesson(lesson.lesson_id, "  ")
    verified = service.verify_lesson(
        lesson.lesson_id, "任务 t123 的 review.json 记录 high 级问题"
    )
    assert verified.status == "verified"


# ---------- 评估 ----------


def test_evaluation_passes_and_reports_simulation(evo) -> None:
    _, service = evo
    _, lessons = service.diagnose("reviewer")
    proposal, _ = service.create_proposal(
        "reviewer", [item.lesson_id for item in lessons]
    )
    report = service.evaluate(proposal.proposal_id)
    assert report.passed is True
    assert report.candidate.detection_rate >= 0.9
    assert report.candidate.detection_rate > report.base.detection_rate
    assert all(item.passed for item in report.acceptance)
    assert report.engine == "mock"
    assert any("模拟" in note for note in report.notes)
    assert report.base.token_source == "estimated"


def test_approve_activates_and_rollback_restores(evo) -> None:
    store, service = evo
    proposal, candidate = _approved_reviewer(service)
    assert candidate.status == "active"
    assert store.active_version("reviewer").version == candidate.version
    assert store.version("reviewer", 1).status == "inactive"
    assert store.effective_spec("reviewer").version == candidate.version
    assert store.audit_log("reviewer")[-1]["proposal_id"] == proposal.proposal_id

    rolled = service.rollback("reviewer", 1)
    assert rolled.version == 1
    assert store.active_version("reviewer").version == 1
    assert store.version("reviewer", candidate.version).status == "inactive"
    assert store.audit_log("reviewer")[-1]["action"] == "rollback"
    assert store.effective_spec("reviewer").version == 1


def test_reject_proposal_marks_candidate_rejected(evo) -> None:
    store, service = evo
    _, lessons = service.diagnose("reviewer")
    proposal, candidate = service.create_proposal(
        "reviewer", [item.lesson_id for item in lessons]
    )
    rejected = service.reject_proposal(proposal.proposal_id)
    assert rejected.approval_status == "rejected"
    assert store.version("reviewer", candidate.version).status == "rejected"
    with pytest.raises(EvolutionStateError):
        store.activate(
            "reviewer",
            candidate.version,
            reason="已拒绝",
            proposal_id=proposal.proposal_id,
        )


def test_tampered_tool_whitelist_is_refused(evo) -> None:
    store, service = evo
    _, candidate = _approved_reviewer(service)
    path = (
        store.root
        / "talents"
        / "reviewer"
        / "versions"
        / f"v{candidate.version}.json"
    )
    payload = path.read_text(encoding="utf-8")
    payload = payload.replace('"read_game"', '"shell"')
    path.write_text(payload, encoding="utf-8")
    with pytest.raises(ImmutableFieldError):
        service.rollback("reviewer", candidate.version)


def test_live_engine_is_explicitly_unavailable(tmp_path: Path) -> None:
    store = EvolutionStore(tmp_path / "evolution", TALENTS_DIR)
    store.ensure_seeded()
    service = EvolutionService(store, mock_mode=False)
    with pytest.raises(EvolutionError):
        service.diagnose("reviewer")


# ---------- 与工作流集成 ----------


def test_run_records_actual_talent_version(tmp_path: Path) -> None:
    store = EvolutionStore(tmp_path / "evolution", TALENTS_DIR)
    store.ensure_seeded()
    service = EvolutionService(store, mock_mode=True)
    _approved_reviewer(service)

    vessel = Vessel(
        MockProvider(),
        talents_dir=TALENTS_DIR,
        default_model="mock",
        budget_usd=10.0,
        talent_versions=store,
    )
    task_store = TaskStore(tmp_path / "tasks")
    engine = WorkflowEngine(vessel, task_store, stage_min_seconds=0)
    record = task_store.create("做一个能计分的贪吃蛇小游戏")
    import asyncio

    asyncio.run(engine.start(record.task_id))
    loaded = task_store.load(record.task_id)
    assert loaded.status is TaskStatus.COMPLETED
    assert loaded.talent_versions["reviewer"] == "reviewer@v2"
    assert loaded.talent_versions["coo"] == "coo@v1"


# ---------- 经验提取 ----------


def _completed_task_with_evidence(task_store: TaskStore) -> str:
    record = task_store.create("做一个带暂停的贪吃蛇")
    record.status = TaskStatus.COMPLETED
    task_store.save(record)
    task_store.write_artifact(
        record,
        "gate.json",
        (
            '{"passed": false, "checks": ['
            '{"id": "restart_after_gameover", "title": "重新开始", '
            '"status": "fail", "detail": "点击重新开始无响应"}], '
            '"blocked_requests": [], "duration_ms": 10}'
        ),
    )
    task_store.write_artifact(
        record,
        "review.json",
        (
            '{"verdict": "ITERATE", "issues": [{"severity": "high", '
            '"description": "暂停失效", "suggestion": "补充暂停逻辑"}], '
            '"suggestions": [], "summary": "需修复"}'
        ),
    )
    record.artifacts["gate.json"] = "gate.json"
    record.artifacts["review.json"] = "review.json"
    task_store.save(record)
    return record.task_id


def test_extract_lessons_separates_verified_and_candidate(tmp_path: Path) -> None:
    task_store = TaskStore(tmp_path / "tasks")
    task_id = _completed_task_with_evidence(task_store)
    store = EvolutionStore(tmp_path / "evolution", TALENTS_DIR)
    store.ensure_seeded()
    service = EvolutionService(store, mock_mode=True)

    record = task_store.load(task_id)
    lessons = service.lessons_from_task(record, task_store.list_artifacts(task_id))

    by_talent = {item.related_talent: item for item in lessons}
    assert by_talent["reviewer"].status == "verified"
    assert "gate.json" in by_talent["reviewer"].verification
    assert by_talent["engineer"].status == "candidate"
    assert by_talent["engineer"].verification == ""
    assert by_talent["reviewer"].source_project_id == task_id


# ---------- HTTP API ----------


@pytest.fixture()
def api(tmp_path: Path):
    store = EvolutionStore(tmp_path / "evolution", TALENTS_DIR)
    store.ensure_seeded()
    service = EvolutionService(store, mock_mode=True)
    task_store = TaskStore(tmp_path / "tasks")
    app = FastAPI()
    app.include_router(create_evolution_router(store, service, task_store))
    return TestClient(app), store, task_store


def test_api_full_evolution_flow(api) -> None:
    client, store, _ = api
    talents = client.get("/api/talents").json()
    assert {item["talent_name"] for item in talents} == {
        "coo",
        "engineer",
        "marketer",
        "reviewer",
    }

    diagnosed = client.post("/api/talents/reviewer/diagnose").json()
    lesson_ids = [item["lesson_id"] for item in diagnosed["created_lessons"]]
    assert len(lesson_ids) == 4

    created = client.post(
        "/api/evolution/proposals",
        json={"target_talent": "reviewer", "lesson_ids": lesson_ids},
    )
    assert created.status_code == 200
    proposal_id = created.json()["proposal"]["proposal_id"]

    # 未评估就批准 -> 409
    early = client.post(f"/api/evolution/proposals/{proposal_id}/approve")
    assert early.status_code == 409

    evaluated = client.post(f"/api/evolution/proposals/{proposal_id}/evaluate").json()
    assert evaluated["evaluation"]["passed"] is True

    approved = client.post(f"/api/evolution/proposals/{proposal_id}/approve").json()
    assert approved["active_version"]["version"] == 2

    detail = client.get("/api/talents/reviewer").json()
    assert detail["active_version"]["version"] == 2
    assert len(detail["versions"]) == 2
    assert detail["audit"][-1]["action"] == "activate"

    rolled = client.post(
        "/api/talents/reviewer/rollback", json={"version": 1, "reason": "演示回滚"}
    )
    assert rolled.status_code == 200
    assert rolled.json()["active_version"]["version"] == 1
    assert store.active_version("reviewer").version == 1


def test_api_lessons_from_task(api) -> None:
    client, _, task_store = api
    task_id = _completed_task_with_evidence(task_store)
    response = client.post(f"/api/tasks/{task_id}/lessons")
    assert response.status_code == 200
    assert response.json()["count"] == 2

    pending = task_store.create("仍在运行的任务")
    rejected = client.post(f"/api/tasks/{pending.task_id}/lessons")
    assert rejected.status_code == 409


def test_api_reject_lesson_and_proposal(api) -> None:
    client, store, _ = api
    lesson = store.add_lesson(
        Lesson(
            related_talent="reviewer",
            problem="待确认的猜测",
            improvement="增加网络检查",
            status="candidate",
        )
    )
    rejected = client.post(f"/api/lessons/{lesson.lesson_id}/reject")
    assert rejected.status_code == 200
    assert rejected.json()["status"] == "rejected"
