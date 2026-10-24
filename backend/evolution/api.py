"""Talent 自进化 HTTP API。

所有写操作都由后端校验状态：
- 候选版本必须有“评估通过 + 用户批准”的提案才能启用；
- 启用时再次比对工具白名单/输出契约/模型，防止绕过安全边界。
本阶段没有用户系统，权限模型是“本机单用户”，文档中已明确声明。
"""

from functools import wraps

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
from backend.store import TaskNotFoundError, TaskStore


class ProposalRequest(BaseModel):
    target_talent: str
    lesson_ids: list[str] = Field(min_length=1)


class RollbackRequest(BaseModel):
    version: int = Field(ge=1)
    reason: str = ""


class VerifyLessonRequest(BaseModel):
    verification: str = Field(min_length=1)


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


def create_evolution_router(
    store: EvolutionStore,
    service: EvolutionService,
    task_store: TaskStore | None = None,
) -> APIRouter:
    router = APIRouter()

    @router.get("/api/talents")
    def list_talents() -> list[dict]:
        return service.talents()

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
