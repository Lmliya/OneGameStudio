"""任务状态机：定义合法迁移。

任何非法迁移都会抛 InvalidTransitionError，防止模型或代码把任务带到
未定义的状态。这是"工作流由 Python 控制"的执行点。
"""

from backend.models.contract import TERMINAL_STATUSES, TaskStatus

ALLOWED_TRANSITIONS: dict[TaskStatus, frozenset[TaskStatus]] = {
    TaskStatus.PENDING: frozenset({TaskStatus.PLANNING, TaskStatus.FAILED}),
    TaskStatus.PLANNING: frozenset({TaskStatus.CODING, TaskStatus.FAILED}),
    TaskStatus.CODING: frozenset({TaskStatus.REVIEWING, TaskStatus.FAILED}),
    TaskStatus.REVIEWING: frozenset(
        {
            TaskStatus.FIXING,
            TaskStatus.MARKETING,
            TaskStatus.NEEDS_ATTENTION,
            TaskStatus.FAILED,
        }
    ),
    TaskStatus.FIXING: frozenset(
        {TaskStatus.REVIEWING, TaskStatus.NEEDS_ATTENTION, TaskStatus.FAILED}
    ),
    TaskStatus.MARKETING: frozenset({TaskStatus.COMPLETED, TaskStatus.FAILED}),
    TaskStatus.COMPLETED: frozenset(),
    TaskStatus.FAILED: frozenset(),
    TaskStatus.NEEDS_ATTENTION: frozenset(),
}


class InvalidTransitionError(RuntimeError):
    """尝试执行状态机不允许的迁移。"""


def assert_transition(current: TaskStatus, target: TaskStatus) -> None:
    allowed = ALLOWED_TRANSITIONS[current]
    if target not in allowed:
        raise InvalidTransitionError(
            f"非法状态迁移：{current.value} -> {target.value}"
            f"（允许：{sorted(s.value for s in allowed)}）"
        )
    if current in TERMINAL_STATUSES:
        raise InvalidTransitionError(f"{current.value} 是终态，不能再迁移")
