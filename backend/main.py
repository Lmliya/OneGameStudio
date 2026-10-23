"""FastAPI 入口：健康检查、任务创建与前端静态托管。"""

from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from backend.config import get_settings
from backend.models.contract import TaskContract, TaskCreateRequest

ROOT_DIR = Path(__file__).resolve().parents[1]
FRONTEND_DIR = ROOT_DIR / "frontend"

app = FastAPI(title="OneGameStudio", version="0.1.0")
settings = get_settings()


@app.get("/api/health")
def health() -> dict:
    """用于确认服务与运行模式是否正常。"""
    return {"status": "ok", "mock_mode": settings.mock_mode}


@app.post("/api/tasks", response_model=TaskContract)
def create_task(request: TaskCreateRequest) -> TaskContract:
    """创建任务目录并落盘契约，不启动任何员工。

    阶段 4 会在这里接入工作流调度。
    """
    contract = TaskContract(requirement=request.requirement)
    task_dir = settings.output_dir / "tasks" / contract.task_id
    task_dir.mkdir(parents=True, exist_ok=False)
    (task_dir / "contract.json").write_text(
        contract.model_dump_json(indent=2), encoding="utf-8"
    )
    return contract


# 必须放在所有 API 路由之后，否则会吞掉 /api/* 请求
app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")
