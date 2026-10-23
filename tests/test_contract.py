"""任务模型与状态机的测试。"""

import pytest
from pydantic import ValidationError

from backend.models.contract import TaskRecord, TaskStatus
from backend.workflow.state_machine import InvalidTransitionError, assert_transition


def test_record_defaults() -> None:
    record = TaskRecord(requirement="做一个贪吃蛇游戏")
    assert record.status is TaskStatus.PENDING
    assert len(record.task_id) == 12
    assert record.artifacts == {}
    assert record.fix_attempts == 0
    assert not record.is_terminal


def test_empty_requirement_rejected() -> None:
    with pytest.raises(ValidationError):
        TaskRecord(requirement="")


def test_legal_transition() -> None:
    assert_transition(TaskStatus.PENDING, TaskStatus.PLANNING)
    assert_transition(TaskStatus.REVIEWING, TaskStatus.FIXING)


def test_illegal_transition_rejected() -> None:
    with pytest.raises(InvalidTransitionError):
        assert_transition(TaskStatus.PENDING, TaskStatus.COMPLETED)


def test_terminal_state_cannot_move() -> None:
    with pytest.raises(InvalidTransitionError):
        assert_transition(TaskStatus.COMPLETED, TaskStatus.PLANNING)


def test_needs_attention_is_terminal() -> None:
    record = TaskRecord(requirement="x", status=TaskStatus.NEEDS_ATTENTION)
    assert record.is_terminal
