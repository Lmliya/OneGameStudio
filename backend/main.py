"""FastAPI 入口：任务创建、查询、产物读取、WebSocket 推送与前端静态托管。"""

import asyncio
import re
from pathlib import Path

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import PlainTextResponse, Response
from fastapi.staticfiles import StaticFiles

from backend.budget import BudgetGuard
from backend.bus import EventBus
from backend.config import get_settings
from backend.core.vessel import Vessel
from backend.models.contract import TaskCreateRequest, TaskRecord
from backend.providers import build_provider
from backend.store import TaskNotFoundError, TaskStore
from backend.workflow import TaskNotRunnableError, WorkflowEngine

ROOT_DIR = Path(__file__).resolve().parents[1]
FRONTEND_DIR = ROOT_DIR / "frontend"

app = FastAPI(title="OneGameStudio", version="0.7.0")
settings = get_settings()


def _resolve(path: Path) -> Path:
    """相对路径按项目根目录解析，避免受启动目录影响。"""
    return path if path.is_absolute() else ROOT_DIR / path


store = TaskStore(_resolve(settings.output_dir))
bus = EventBus()
budget_guard = BudgetGuard.from_settings(settings)
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
)
engine = WorkflowEngine(
    vessel,
    store,
    max_fix_rounds=settings.max_fix_rounds,
    on_event=bus.publish,
    stage_min_seconds=settings.stage_min_seconds,
    budget=budget_guard,
)

# 持有后台任务引用，防止被垃圾回收
_background: set[asyncio.Task] = set()

# task_id 只允许十六进制，杜绝路径穿越
_TASK_ID = re.compile(r"^[0-9a-f]{6,32}$")
# 预览只允许交付用的游戏文件及其历史版本，其余一律拒绝
_PREVIEW_FILE = re.compile(r"^(index\.html|history/index\.v\d+\.html)$")

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


def _load_or_404(task_id: str) -> TaskRecord:
    if not _TASK_ID.match(task_id):
        raise HTTPException(status_code=404, detail="任务不存在")
    try:
        return store.load(task_id)
    except TaskNotFoundError as exc:
        raise HTTPException(status_code=404, detail="任务不存在") from exc


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
    r"|history/index\.v\d+\.html|history/gate\.v\d+\.json)$"
)


@app.get("/api/tasks/{task_id}/artifacts/{filename:path}")
def get_artifact_file(task_id: str, filename: str) -> PlainTextResponse:
    """按文件名读取单个产物，避免一次拉取全部内容。"""
    _load_or_404(task_id)
    if not _ARTIFACT_FILE.match(filename):
        raise HTTPException(status_code=404, detail="产物不存在")
    path = store.task_dir(task_id) / filename
    if not path.exists():
        raise HTTPException(status_code=404, detail="产物不存在")
    return PlainTextResponse(path.read_text(encoding="utf-8"))


@app.get("/api/tasks/{task_id}/history")
def list_history(task_id: str) -> list[str]:
    """返回历史版本快照文件名，供 Review 标签页展示 V1/V2/V3。"""
    _load_or_404(task_id)
    history_dir = store.task_dir(task_id) / "history"
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
    path = store.task_dir(task_id) / filename
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
        record = store.load(task_id)
    except TaskNotFoundError:
        await websocket.close(code=4404)
        return

    queue = bus.subscribe(task_id)
    try:
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
