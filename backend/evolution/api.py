"""Talent 自进化 HTTP API。

所有写操作都由后端校验状态：
- 候选版本必须有“评估通过 + 用户批准”的提案才能启用；
- 启用时再次比对工具白名单/输出契约/模型，防止绕过安全边界。
本阶段没有用户系统，权限模型是“本机单用户”，文档中已明确声明。
"""

import json
from functools import wraps
from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from backend.evolution.errors import (
    EvolutionError,
    EvolutionStateError,
    ImmutableFieldError,
    VersionNotFoundError,
)
from backend.evolution.service import EvolutionService
from backend.evolution.store import EvolutionStore
from backend.models.contract import TaskStatus
from backend.store import TaskNotFoundError, TaskStore


class ProposalRequest(BaseModel):
    target_talent: str
    lesson_ids: list[str] = Field(min_length=1)


class RollbackRequest(BaseModel):
    version: int = Field(ge=1)
    reason: str = ""


class VerifyLessonRequest(BaseModel):
    verification: str = Field(min_length=1)


class SwitchTalentRequest(BaseModel):
    talent_name: str = Field(min_length=1)


# Employee 面板的岗位结构：岗位固定 6 个，角色按 Talent 归属。
# 目前只有 Engineer 岗位拥有两个角色（主工程师 + 备用工程师）。
POSITIONS: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    ("coo", "需求分析", ("coo",)),
    ("creative", "创意总监", ("creative",)),
    ("delivery", "交付总监", ("delivery",)),
    ("engineer", "工程师", ("engineer", "backup_engineer")),
    ("reviewer", "质量审查", ("reviewer",)),
    ("marketer", "营销素材", ("marketer",)),
)
POSITIONS_DIR = "positions"


def _position_members() -> dict[str, tuple[str, str, tuple[str, ...]]]:
    return {item[0]: item for item in POSITIONS}


def _active_position_talent(root: Path, position: str, members: tuple[str, ...]) -> str:
    """岗位级启用指针：同一岗位同一时间只有一个角色处于启用状态。"""
    path = root / POSITIONS_DIR / f"{position}.json"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        talent = payload.get("active_talent")
        if talent in members:
            return talent
    except (OSError, ValueError):
        pass
    return members[0]


def _set_active_position_talent(
    root: Path, position: str, talent: str, members: tuple[str, ...]
) -> str:
    if talent not in members:
        raise EvolutionStateError(f"{talent} 不属于岗位 {position}")
    directory = root / POSITIONS_DIR
    directory.mkdir(parents=True, exist_ok=True)
    (directory / f"{position}.json").write_text(
        json.dumps({"active_talent": talent}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return talent


def _handle(func):
    """把领域异常映射成明确的 HTTP 状态码。"""

    @wraps(func)
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except VersionNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except TaskNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ImmutableFieldError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except EvolutionStateError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except EvolutionError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    return wrapper


def _task_stats(
    task_store: TaskStore | list[TaskStore] | None,
) -> dict[str, dict]:
    """按 Talent 统计已完成的任务。

    归属依据是 `TaskRecord.talent_versions` 里真实出现的 Talent 键，
    只统计 status == completed 的任务，避免把未参与的角色算进来。
    传入多个 TaskStore 时合并统计（本地任务 + 演示历史任务）。
    """
    if task_store is None:
        return {}
    stores = task_store if isinstance(task_store, list) else [task_store]

    seen: set[str] = set()
    stats: dict[str, dict] = {}
    for active_store in stores:
        for record in active_store.list_records():
            if record.task_id in seen or record.status != TaskStatus.COMPLETED:
                continue
            seen.add(record.task_id)
            entry = {
                "task_id": record.task_id,
                "name": record.requirement,
                "final_version_id": record.final_version_id,
            }
            for talent in record.talent_versions:
                bucket = stats.setdefault(talent, {"count": 0, "tasks": []})
                bucket["count"] += 1
                bucket["tasks"].append(entry)
    return stats


def create_evolution_router(
    store: EvolutionStore,
    service: EvolutionService,
    task_store: TaskStore | list[TaskStore] | None = None,
) -> APIRouter:
    router = APIRouter()

    def talents_with_stats() -> list[dict]:
        items = service.talents()
        stats = _task_stats(task_store)
        for item in items:
            stat = stats.get(item["talent_name"], {"count": 0, "tasks": []})
            item["completed_count"] = stat["count"]
            item["completed_tasks"] = stat["tasks"]
        return items

    @router.get("/api/talents")
    def list_talents() -> list[dict]:
        return talents_with_stats()

    @router.get("/api/employees")
    def list_employees() -> list[dict]:
        """按岗位聚合员工，供 Employee 面板展示。"""
        by_talent = {item["talent_name"]: item for item in talents_with_stats()}
        positions = []
        for position_id, title, members in POSITIONS:
            active = _active_position_talent(store.root, position_id, members)
            roles = []
            for name in members:
                if name not in by_talent:
                    continue
                role = dict(by_talent[name])
                role["is_active_for_position"] = name == active
                roles.append(role)
            positions.append(
                {
                    "position": position_id,
                    "title": title,
                    "active_talent": active,
                    "roles": roles,
                }
            )
        return positions

    @router.post("/api/positions/{position}/switch")
    @_handle
    def switch_position_talent(
        position: str, payload: SwitchTalentRequest
    ) -> dict:
        """手动切换岗位当前启用的角色。"""
        entry = _position_members().get(position)
        if entry is None:
            raise HTTPException(status_code=404, detail=f"岗位不存在：{position}")
        _, title, members = entry
        active = _set_active_position_talent(
            store.root, position, payload.talent_name, members
        )
        return {"position": position, "title": title, "active_talent": active}

    @router.get("/api/talents/{talent}")
    @_handle
    def talent_detail(talent: str) -> dict:
        return service.detail(talent)

    @router.get("/api/talents/{talent}/versions")
    @_handle
    def talent_versions(talent: str) -> list[dict]:
        return [item.model_dump(mode="json") for item in store.versions(talent)]

    @router.get("/api/talents/{talent}/lessons")
    @_handle
    def talent_lessons(talent: str) -> list[dict]:
        return [item.model_dump(mode="json") for item in store.list_lessons(talent)]

    @router.post("/api/talents/{talent}/diagnose")
    @_handle
    def diagnose(talent: str) -> dict:
        report, lessons = service.diagnose(talent)
        return {
            "evaluation": report.model_dump(mode="json"),
            "created_lessons": [item.model_dump(mode="json") for item in lessons],
        }

    @router.post("/api/talents/{talent}/rollback")
    @_handle
    def rollback(talent: str, payload: RollbackRequest) -> dict:
        version = service.rollback(talent, payload.version, payload.reason)
        return {
            "talent_name": talent,
            "active_version": version.model_dump(mode="json"),
            "audit": store.audit_log(talent),
        }

    @router.get("/api/lessons")
    def all_lessons(talent: str | None = None) -> list[dict]:
        return [item.model_dump(mode="json") for item in store.list_lessons(talent)]

    @router.post("/api/lessons/{lesson_id}/verify")
    @_handle
    def verify_lesson(lesson_id: str, payload: VerifyLessonRequest) -> dict:
        return service.verify_lesson(lesson_id, payload.verification).model_dump(
            mode="json"
        )

    @router.post("/api/lessons/{lesson_id}/reject")
    @_handle
    def reject_lesson(lesson_id: str) -> dict:
        return service.reject_lesson(lesson_id).model_dump(mode="json")

    @router.post("/api/tasks/{task_id}/lessons")
    @_handle
    def lessons_from_task(task_id: str) -> dict:
        if task_store is None:
            raise EvolutionError("服务未配置任务存储，无法提取经验")
        record = task_store.load(task_id)
        if not record.is_terminal:
            raise EvolutionStateError("任务尚未结束，不能提取经验")
        artifacts = task_store.list_artifacts(task_id)
        lessons = service.lessons_from_task(record, artifacts)
        return {
            "task_id": task_id,
            "created": [item.model_dump(mode="json") for item in lessons],
            "count": len(lessons),
        }

    @router.get("/api/evolution/proposals")
    def list_proposals(target_talent: str | None = None) -> list[dict]:
        return [
            item.model_dump(mode="json")
            for item in store.list_proposals(target_talent)
        ]

    @router.get("/api/evolution/proposals/{proposal_id}")
    @_handle
    def proposal_detail(proposal_id: str) -> dict:
        proposal = store.get_proposal(proposal_id)
        evaluation = (
            store.get_evaluation(proposal.evaluation_id)
            if proposal.evaluation_id
            else None
        )
        return {
            "proposal": proposal.model_dump(mode="json"),
            "evaluation": evaluation.model_dump(mode="json") if evaluation else None,
        }

    @router.post("/api/evolution/proposals")
    @_handle
    def create_proposal(payload: ProposalRequest) -> dict:
        proposal, candidate = service.create_proposal(
            payload.target_talent, payload.lesson_ids
        )
        return {
            "proposal": proposal.model_dump(mode="json"),
            "candidate_version": candidate.model_dump(mode="json"),
        }

    @router.post("/api/evolution/proposals/{proposal_id}/evaluate")
    @_handle
    def evaluate_proposal(proposal_id: str) -> dict:
        report = service.evaluate(proposal_id)
        return {
            "evaluation": report.model_dump(mode="json"),
            "proposal": store.get_proposal(proposal_id).model_dump(mode="json"),
        }

    @router.post("/api/evolution/proposals/{proposal_id}/approve")
    @_handle
    def approve_proposal(proposal_id: str) -> dict:
        proposal, activated = service.approve(proposal_id)
        return {
            "proposal": proposal.model_dump(mode="json"),
            "active_version": activated.model_dump(mode="json"),
            "audit": store.audit_log(proposal.target_talent),
        }

    @router.post("/api/evolution/proposals/{proposal_id}/reject")
    @_handle
    def reject_proposal(proposal_id: str) -> dict:
        proposal = service.reject_proposal(proposal_id)
        return {"proposal": proposal.model_dump(mode="json")}

    @router.get("/api/evolution/evaluations/{evaluation_id}")
    @_handle
    def evaluation_detail(evaluation_id: str) -> dict:
        return store.get_evaluation(evaluation_id).model_dump(mode="json")

    return router
