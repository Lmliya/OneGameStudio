"""契约模型的校验测试。"""

import pytest
from pydantic import ValidationError

from onegamestudio.models.contract import Stage, TaskContract, TaskStatus


def test_contract_defaults() -> None:
    contract = TaskContract(requirement="做一个贪吃蛇游戏")
    assert contract.status is TaskStatus.PENDING
    assert contract.stage is Stage.DESIGN
    assert len(contract.task_id) == 12
    assert contract.artifacts == {}


def test_empty_requirement_rejected() -> None:
    with pytest.raises(ValidationError):
        TaskContract(requirement="")


def test_touch_updates_timestamp() -> None:
    contract = TaskContract(requirement="做一个打砖块游戏")
    before = contract.updated_at
    contract.touch()
    assert contract.updated_at >= before
