"""FastAPI 入口：任务创建、查询、产物读取、WebSocket 推送与前端静态托管。"""

import asyncio
import re
from collections import defaultdict, deque
from pathlib import Path
from time import monotonic

from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse, PlainTextResponse, Response
from fastapi.staticfiles import StaticFiles

from backend.budget import BudgetGuard
from backend.bus import EventBus
from backend.config import get_settings
from backend.core.vessel import Vessel
from backend.evolution.api import create_evolution_router
from backend.evolution.service import EvolutionService
from backend.evolution.store import EvolutionStore
from backend.models.contract import (
    TERMINAL_STATUSES,
    SelectFinalVersionRequest,
    TaskCreateRequest,
    TaskRecord,
)
from backend.providers import build_provider
from backend.store import (
    TaskNotFoundError,
    TaskStore,
    VersionError,
    VersionNotFoundError,
)
from backend.workflow import TaskNotRunnableError, WorkflowEngine

ROOT_DIR = Path(__file__).resolve().parents[1]
FRONTEND_DIR = ROOT_DIR / "frontend"

app = FastAPI(title="OneGameStudio", version="0.10.0")
settings = get_settings()


@app.middleware("http")
async def require_access_token(request: Request, call_next):
    """配置 ACCESS_TOKEN 后，所有写接口都必须携带令牌。

    Talent 安全配置、岗位切换、任务创建等写操作共用同一道门禁，
    未授权请求无法消耗模型额度，也无法修改进化配置。
    """
    if (
        settings.access_token
        and request.method in {"POST", "PUT", "PATCH", "DELETE"}
        and request.url.path.startswith("/api/")
        and request.headers.get("X-OGS-Token") != settings.access_token
    ):
        return JSONResponse(status_code=401, content={"detail": "访问令牌无效"})
    return await call_next(request)


def _resolve(path: Path) -> Path:
    """相对路径按项目根目录解析，避免受启动目录影响。"""
    return path if path.is_absolute() else ROOT_DIR / path


store = TaskStore(_resolve(settings.output_dir))
# 随仓库提交的预验证历史任务，Demo 模式只读展示
demo_store = TaskStore(_resolve(settings.demo_dir))
bus = EventBus()
budget_guard = BudgetGuard.from_settings(settings)
# 阶段 8：Talent 版本库（首次启动把 talents/*.yaml 注册为 v1）
evolution_store = EvolutionStore(
    _resolve(settings.evolution_dir), _resolve(settings.talents_dir)
)
evolution_store.ensure_seeded()
evolution_service = EvolutionService(evolution_store, mock_mode=settings.mock_mode)
# Mock 模式下实际发起的是 mock 调用，预算记账也应如实使用 "mock" 作为模型名
runtime_model = "mock" if settings.mock_mode else settings.llm_model
vessel = Vessel(
    build_provider(settings),
    talents_dir=_resolve(settings.talents_dir),
    default_model=runtime_model,
    timeout_seconds=settings.request_timeout_seconds,
    budget_usd=settings.budget_usd,
    guard=budget_guard,
    max_output_tokens=settings.max_output_tokens,
    max_concurrent_calls=settings.max_concurrent_calls,
    max_retries=settings.provider_max_retries,
    retry_backoff_seconds=settings.provider_retry_backoff_seconds,
    talent_versions=evolution_store,
)
engine = WorkflowEngine(
    vessel,
    store,
    max_fix_rounds=settings.max_fix_rounds,
    on_event=bus.publish,
    stage_min_seconds=settings.stage_min_seconds,
    budget=budget_guard,
    opinion_max_output_tokens=settings.opinion_max_output_tokens,
)
app.include_router(
    create_evolution_router(
        evolution_store, evolution_service, [store, demo_store]
    )
)

# 持有后台任务引用，防止被垃圾回收
_background: set[asyncio.Task] = set()

# task_id 只允许十六进制，杜绝路径穿越
_TASK_ID = re.compile(r"^[0-9a-f]{6,32}$")
# 预览只允许交付用的游戏文件、修复历史与不可变版本快照，其余一律拒绝
_PREVIEW_FILE = re.compile(
    r"^(index\.html|history/index\.v\d+\.html|versions/[0-9a-f]{6,32}-v[1-9]\d*\.html)$"
)

# 生成物是不可信代码：禁止联网、禁止访问本站接口与存储
_PREVIEW_CSP = (
    "default-src 'none'; "
    "script-src 'unsafe-inline'; "
    "style-src 'unsafe-inline'; "
    "img-src data: blob:; "
    "media-src data: blob:; "
    "font-src data:; "
    "connect-src 'none'; "
    "form-action 'none'; "
    "base-uri 'none'; "
    "frame-ancestors 'self'"
)


def schedule(task_id: str) -> None:
    """在后台启动工作流，让 HTTP 请求立即返回。"""
    task = asyncio.create_task(engine.start(task_id))
    _background.add(task)
    task.add_done_callback(_background.discard)


# 单 IP 创建任务的滑动窗口，进程内限流；多实例部署需改用共享存储
_submissions: dict[str, deque[float]] = defaultdict(deque)


def _rate_limited(client_ip: str) -> bool:
    limit = settings.task_rate_limit_per_minute
    if limit <= 0:
        return False
    now = monotonic()
    bucket = _submissions[client_ip]
    while bucket and now - bucket[0] > 60:
        bucket.popleft()
    if len(bucket) >= limit:
        return True
    bucket.append(now)
    return False


def _live_ready() -> bool:
    """Live 模式必须同时具备真实供应商、模型名与服务端密钥。"""
    return (
        settings.app_mode == "live"
        and not settings.mock_mode
        and bool(settings.llm_model)
        and bool(settings.llm_api_key)
    )


def _store_for(task_id: str) -> TaskStore:
    """本地任务与只读演示任务共用同一套查询接口。"""
    if not _TASK_ID.match(task_id):
        raise HTTPException(status_code=404, detail="任务不存在")
    for candidate in (store, demo_store):
        if candidate.exists(task_id):
            return candidate
    raise HTTPException(status_code=404, detail="任务不存在")


def _load_or_404(task_id: str) -> TaskRecord:
    try:
        return _store_for(task_id).load(task_id)
    except TaskNotFoundError as exc:
        raise HTTPException(status_code=404, detail="任务不存在") from exc


@app.get("/api/health")
def health() -> dict:
    return {
        "status": "ok",
        "mode": settings.app_mode,
        "mock_mode": settings.mock_mode,
        "read_only": settings.app_mode == "demo" and settings.demo_read_only,
        "live_ready": _live_ready(),
    }


@app.get("/api/demo")
def demo_info() -> dict:
    """公开演示：只返回随仓库提交的预验证历史任务。"""
    tasks = [
        {
            "task_id": record.task_id,
            "name": record.requirement,
            "status": record.status.value,
            "final_version_id": record.final_version_id,
            "sop_mode": record.sop_mode.value if record.sop_mode else None,
        }
        for record in demo_store.list_records()
    ]
    return {
        "mode": settings.app_mode,
        "read_only": settings.app_mode == "demo" and settings.demo_read_only,
        "tasks": tasks,
    }


@app.post("/api/tasks", response_model=TaskRecord, status_code=202)
async def create_task(
    payload: TaskCreateRequest, http_request: Request
) -> TaskRecord:
    """创建任务并在后台执行工作流。相同需求的运行中任务会拒绝重复提交。"""
    if settings.app_mode == "demo" and settings.demo_read_only:
        raise HTTPException(
            status_code=403,
            detail="Demo 模式为只读：只能浏览历史任务，请切换到 Live 模式后再提交。",
        )
    if settings.app_mode == "live" and not _live_ready():
        raise HTTPException(
            status_code=503,
            detail="Live 模式未配置完成：需要服务端 LLM_API_KEY、LLM_MODEL 且 MOCK_MODE=false。",
        )
    if settings.app_mode == "live" and settings.access_token:
        if http_request.headers.get("X-OGS-Token") != settings.access_token:
            raise HTTPException(status_code=401, detail="访问令牌无效")

    client_ip = http_request.client.host if http_request.client else "unknown"
    if _rate_limited(client_ip):
        raise HTTPException(
            status_code=429,
            detail=f"提交过于频繁：每分钟最多 {settings.task_rate_limit_per_minute} 次",
        )
    active = sum(
        1 for record in store.list_records() if record.status not in TERMINAL_STATUSES
    )
    if active >= settings.max_active_tasks:
        raise HTTPException(
            status_code=429,
            detail=f"并发任务已达上限（{settings.max_active_tasks}），请等待现有任务结束",
        )

    existing = store.find_active_by_requirement(payload.requirement)
    if existing is not None:
        raise HTTPException(
            status_code=409,
            detail={
                "message": "相同需求的任务正在执行",
                "task_id": existing.task_id,
                "status": existing.status.value,
            },
        )

    try:
        record = store.create(
            payload.requirement,
            max_fix_rounds=settings.max_fix_rounds,
            sop_mode=payload.sop_mode,
            source_version_id=payload.source_version_id,
        )
    except VersionNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except VersionError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    schedule(record.task_id)
    return record


@app.get("/api/tasks")
def list_tasks() -> list[dict]:
    """列出 output 下的全部任务，按更新时间降序，供选择来源版本。"""
    items = []
    for record in store.list_records():
        versions = store.list_versions(record.task_id)
        latest = versions[-1].version_id if versions else None
        items.append(
            {
                "task_id": record.task_id,
                "requirement": record.requirement,
                "status": record.status,
                "updated_at": record.updated_at,
                "final_version_id": record.final_version_id,
                "latest_version_id": latest,
            }
        )
    return items


@app.get("/api/tasks/{task_id}", response_model=TaskRecord)
def get_task(task_id: str) -> TaskRecord:
    return _load_or_404(task_id)


@app.post("/api/tasks/{task_id}/cancel", response_model=TaskRecord, status_code=202)
def cancel_task(task_id: str) -> TaskRecord:
    """请求取消任务：运行中的任务会在下一个安全点停止，已生成产物全部保留。"""
    _load_or_404(task_id)
    try:
        return engine.cancel(task_id)
    except TaskNotRunnableError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.get("/api/tasks/{task_id}/artifacts")
def get_artifacts(task_id: str) -> dict[str, str]:
    _load_or_404(task_id)
    return store.list_artifacts(task_id)


# 可读取的产物白名单；history/ 下只放行受控命名的快照
_ARTIFACT_FILE = re.compile(
    r"^(prd\.md|index\.html|gate\.json|review\.json"
    r"|marketing_kit\.md|marketing_kit\.json"
    r"|creative_proposal\.json|delivery_assessment\.json|conflict_decision\.json"
    r"|history/index\.v\d+\.html|history/gate\.v\d+\.json"
    r"|history/creative_proposal\.round\d+\.json)$"
)


@app.get("/api/tasks/{task_id}/artifacts/{filename:path}")
def get_artifact_file(task_id: str, filename: str) -> PlainTextResponse:
    """按文件名读取单个产物，避免一次拉取全部内容。"""
    _load_or_404(task_id)
    if not _ARTIFACT_FILE.match(filename):
        raise HTTPException(status_code=404, detail="产物不存在")
    path = _store_for(task_id).task_dir(task_id) / filename
    if not path.exists():
        raise HTTPException(status_code=404, detail="产物不存在")
    return PlainTextResponse(path.read_text(encoding="utf-8"))


@app.get("/api/tasks/{task_id}/versions")
def list_versions(task_id: str) -> list[dict]:
    """返回该任务的全部不可变游戏版本记录。"""
    return [
        item.model_dump(mode="json")
        for item in _store_for(task_id).list_versions(task_id)
    ]


@app.post("/api/tasks/{task_id}/final-version")
def rollback_version(task_id: str, payload: SelectFinalVersionRequest) -> dict:
    """CEO 回退：把当前交付物恢复到指定历史快照，快照本身不变。"""
    task_store = _store_for(task_id)
    if settings.app_mode == "demo" and settings.demo_read_only:
        raise HTTPException(
            status_code=403, detail="Demo 模式为只读：不能修改最终版本。"
        )
    try:
        version_id = task_store.rollback_artifact(task_id, payload.filename)
    except VersionNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except VersionError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except TaskNotFoundError as exc:
        raise HTTPException(status_code=404, detail="任务不存在") from exc
    return {
        "final_version_id": version_id,
        "filename": payload.filename,
    }


@app.get("/api/tasks/{task_id}/history")
def list_history(task_id: str) -> list[str]:
    """返回历史版本快照文件名，供 Review 标签页展示 V1/V2/V3。"""
    history_dir = _store_for(task_id).task_dir(task_id) / "history"
    if not history_dir.exists():
        return []
    return sorted(
        f"history/{item.name}" for item in history_dir.iterdir() if item.is_file()
    )


@app.get("/preview/{task_id}/{filename:path}")
def preview(task_id: str, filename: str) -> Response:
    """隔离预览：只回放游戏 HTML，并用 CSP 切断一切外部访问。"""
    if not _TASK_ID.match(task_id) or not _PREVIEW_FILE.match(filename):
        raise HTTPException(status_code=404, detail="预览文件不存在")
    path = _store_for(task_id).task_dir(task_id) / filename
    if not path.exists():
        raise HTTPException(status_code=404, detail="预览文件不存在")
    return Response(
        path.read_text(encoding="utf-8"),
        media_type="text/html; charset=utf-8",
        headers={
            "Content-Security-Policy": _PREVIEW_CSP,
            "X-Content-Type-Options": "nosniff",
            "Cache-Control": "no-store",
        },
    )


@app.websocket("/ws/tasks/{task_id}")
async def task_stream(websocket: WebSocket, task_id: str) -> None:
    """先下发任务快照（断线重连可完整恢复），再持续推送增量事件。"""
    await websocket.accept()
    if not _TASK_ID.match(task_id):
        await websocket.close(code=4404)
        return
    try:
        task_store = _store_for(task_id)
        record = task_store.load(task_id)
    except (TaskNotFoundError, HTTPException):
        await websocket.close(code=4404)
        return

    queue = bus.subscribe(task_id)
    try:
        # Demo 历史任务：先给空事件快照，再按顺序回放，避免日志重复
        if settings.app_mode == "demo" and task_store is demo_store:
            payload = record.model_dump(mode="json")
            payload["events"] = []
            await websocket.send_json({"type": "task.snapshot", "task": payload})
            for event in record.events:
                await websocket.send_json(event.model_dump(mode="json"))
                await asyncio.sleep(settings.demo_replay_ms / 1000)
        else:
            await websocket.send_json(
                {"type": "task.snapshot", "task": record.model_dump(mode="json")}
            )
        while True:
            try:
                message = await asyncio.wait_for(queue.get(), timeout=20)
            except asyncio.TimeoutError:
                await websocket.send_json({"type": "ping"})
                continue
            await websocket.send_json(message)
    except (WebSocketDisconnect, RuntimeError):
        pass
    finally:
        bus.unsubscribe(task_id, queue)


# 必须放在所有 API 路由之后，否则会吞掉 /api/* 请求
app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")
