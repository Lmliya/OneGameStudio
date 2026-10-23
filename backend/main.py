"""FastAPI 入口：任务创建、查询、产物读取与前端静态托管。"""

import asyncio
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles

from backend.config import get_settings
from backend.core.vessel import Vessel
from backend.models.contract import TaskCreateRequest, TaskRecord
from backend.providers import build_provider
from backend.store import TaskNotFoundError, TaskStore
from backend.workflow import WorkflowEngine

ROOT_DIR = Path(__file__).resolve().parents[1]
FRONTEND_DIR = ROOT_DIR / "frontend"

app = FastAPI(title="OneGameStudio", version="0.2.0")
settings = get_settings()


def _resolve(path: Path) -> Path:
    """相对路径按项目根目录解析，避免受启动目录影响。"""
    return path if path.is_absolute() else ROOT_DIR / path


store = TaskStore(_resolve(settings.output_dir))
vessel = Vessel(
    build_provider(settings),
    talents_dir=_resolve(settings.talents_dir),
    default_model=settings.llm_model,
    timeout_seconds=settings.request_timeout_seconds,
    budget_usd=settings.budget_usd,
)
engine = WorkflowEngine(vessel, store, max_fix_rounds=settings.max_fix_rounds)

# 持有后台任务引用，防止被垃圾回收
_background: set[asyncio.Task] = set()


def schedule(task_id: str) -> None:
    """在后台启动工作流，让 HTTP 请求立即返回。"""
    task = asyncio.create_task(engine.start(task_id))
    _background.add(task)
    task.add_done_callback(_background.discard)


@app.get("/api/health")
def health() -> dict:
    return {"status": "ok", "mock_mode": settings.mock_mode}


@app.post("/api/tasks", response_model=TaskRecord, status_code=202)
async def create_task(request: TaskCreateRequest) -> TaskRecord:
    """创建任务并在后台执行工作流。相同需求的运行中任务会拒绝重复提交。"""
    existing = store.find_active_by_requirement(request.requirement)
    if existing is not None:
        raise HTTPException(
            status_code=409,
            detail={
                "message": "相同需求的任务正在执行",
                "task_id": existing.task_id,
                "status": existing.status.value,
            },
        )

    record = store.create(request.requirement, max_fix_rounds=settings.max_fix_rounds)
    schedule(record.task_id)
    return record


@app.get("/api/tasks/{task_id}", response_model=TaskRecord)
def get_task(task_id: str) -> TaskRecord:
    try:
        return store.load(task_id)
    except TaskNotFoundError as exc:
        raise HTTPException(status_code=404, detail="任务不存在") from exc


@app.get("/api/tasks/{task_id}/artifacts")
def get_artifacts(task_id: str) -> dict[str, str]:
    try:
        return store.list_artifacts(task_id)
    except TaskNotFoundError as exc:
        raise HTTPException(status_code=404, detail="任务不存在") from exc


# 必须放在所有 API 路由之后，否则会吞掉 /api/* 请求
app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")
