"""FastAPI 入口：阶段 1 只有健康检查与任务创建两个端点。"""

from fastapi import FastAPI

from onegamestudio.config import get_settings
from onegamestudio.models.contract import TaskContract, TaskCreateRequest

app = FastAPI(title="OneGameStudio", version="0.1.0")
settings = get_settings()


@app.get("/health")
def health() -> dict:
    """用于确认服务与模式是否正常。"""
    return {"status": "ok", "mock_mode": settings.mock_mode}


@app.post("/api/tasks", response_model=TaskContract)
def create_task(request: TaskCreateRequest) -> TaskContract:
    """创建任务目录并落盘契约，不启动任何员工。

    阶段 4 会在这里接入工作流调度。
    """
    contract = TaskContract(requirement=request.requirement)
    task_dir = settings.data_dir / "tasks" / contract.task_id
    task_dir.mkdir(parents=True, exist_ok=False)
    (task_dir / "contract.json").write_text(
        contract.model_dump_json(indent=2), encoding="utf-8"
    )
    return contract
