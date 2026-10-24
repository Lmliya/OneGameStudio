"""Talent 配置加载与安全约束的测试。"""

from pathlib import Path

import pytest

from backend.schemas import OUTPUT_SCHEMAS
from backend.talents import TalentConfigError, list_talents, load_talent
from backend.tools import ROLE_TOOLS

TALENTS_DIR = Path(__file__).resolve().parents[1] / "talents"


def test_load_all_six_talents() -> None:
    talents = list_talents(TALENTS_DIR)
    assert set(talents) == {
        "coo",
        "creative",
        "delivery",
        "engineer",
        "reviewer",
        "marketer",
    }
    for talent in talents.values():
        assert talent.name
        assert talent.role
        assert talent.system_prompt
        assert talent.output_schema in OUTPUT_SCHEMAS


def test_talent_tools_match_role_policy() -> None:
    """YAML 里声明的工具必须与该角色的授权表完全一致。"""
    talents = list_talents(TALENTS_DIR)
    for talent_id, talent in talents.items():
        assert set(talent.allowed_tools) == set(ROLE_TOOLS[talent_id])


def test_talent_cannot_claim_other_role_tool(tmp_path: Path) -> None:
    (tmp_path / "coo.yaml").write_text(
        "name: COO\nrole: x\nsystem_prompt: x\noutput_schema: prd\n"
        "allowed_tools:\n  - write_game\n",
        encoding="utf-8",
    )
    with pytest.raises(TalentConfigError, match="无权使用"):
        load_talent("coo", tmp_path)


def test_expected_output_schemas() -> None:
    talents = list_talents(TALENTS_DIR)
    assert talents["coo"].output_schema == "prd"
    assert talents["engineer"].output_schema == "game"
    assert talents["reviewer"].output_schema == "review"
    assert talents["marketer"].output_schema == "marketing"
    assert talents["creative"].output_schema == "creative_proposal"
    assert talents["delivery"].output_schema == "delivery_assessment"


def test_model_is_not_hardcoded() -> None:
    """Talent 中模型留空，由 Vessel 使用全局默认模型。"""
    for talent in list_talents(TALENTS_DIR).values():
        assert talent.model is None


def test_unknown_talent_raises() -> None:
    with pytest.raises(TalentConfigError):
        load_talent("ceo", TALENTS_DIR)


def test_unauthorized_tool_rejected(tmp_path: Path) -> None:
    (tmp_path / "bad.yaml").write_text(
        "name: Bad\nrole: x\nsystem_prompt: x\noutput_schema: prd\n"
        "allowed_tools:\n  - shell_exec\n",
        encoding="utf-8",
    )
    with pytest.raises(TalentConfigError, match="未授权工具"):
        load_talent("bad", tmp_path)


def test_unknown_schema_rejected(tmp_path: Path) -> None:
    (tmp_path / "bad.yaml").write_text(
        "name: Bad\nrole: x\nsystem_prompt: x\noutput_schema: unknown\n",
        encoding="utf-8",
    )
    with pytest.raises(TalentConfigError, match="未注册"):
        load_talent("bad", tmp_path)


def test_missing_field_rejected(tmp_path: Path) -> None:
    (tmp_path / "bad.yaml").write_text("name: Bad\n", encoding="utf-8")
    with pytest.raises(TalentConfigError, match="字段校验失败"):
        load_talent("bad", tmp_path)
