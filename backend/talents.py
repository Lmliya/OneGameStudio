"""Talent 加载器：从 talents/*.yaml 读取并校验员工配置。

安全约束：
- allowed_tools 必须属于系统预定义的白名单，未授权工具直接拒绝加载。
- output_schema 必须已注册，避免模型输出无人校验。
"""

from pathlib import Path

import yaml

from backend.models.talent import TalentSpec
from backend.schemas import OUTPUT_SCHEMAS

# 系统当前真正提供的工具。没有 shell、没有文件写入之外的能力。
# 阶段 3 接入 Tool Policy 后，Vessel 会再次按此白名单拦截实际调用。
ALLOWED_TOOLS: frozenset[str] = frozenset({"read_contract", "write_artifact"})


class TalentConfigError(RuntimeError):
    """Talent 配置非法（缺字段、未知工具、未知 schema 等）。"""


def load_talent(talent_id: str, talents_dir: Path) -> TalentSpec:
    """按文件名（不含扩展名）加载单个 Talent。"""
    path = talents_dir / f"{talent_id}.yaml"
    if not path.exists():
        raise TalentConfigError(f"未找到 Talent 配置：{path}")

    with path.open(encoding="utf-8") as handle:
        data = yaml.safe_load(handle) or {}

    if not isinstance(data, dict):
        raise TalentConfigError(f"{path} 的内容必须是映射结构")

    try:
        talent = TalentSpec(id=talent_id, **data)
    except Exception as exc:  # noqa: BLE001 - 统一转为配置错误
        raise TalentConfigError(f"{path} 字段校验失败：{exc}") from exc

    unknown_tools = set(talent.allowed_tools) - ALLOWED_TOOLS
    if unknown_tools:
        raise TalentConfigError(
            f"{path} 申请了未授权工具：{sorted(unknown_tools)}"
            f"（可用工具：{sorted(ALLOWED_TOOLS)}）"
        )

    if talent.output_schema not in OUTPUT_SCHEMAS:
        raise TalentConfigError(
            f"{path} 的 output_schema='{talent.output_schema}' 未注册"
            f"（可用：{sorted(OUTPUT_SCHEMAS)}）"
        )

    return talent


def list_talents(talents_dir: Path) -> dict[str, TalentSpec]:
    """加载目录下全部 Talent，按文件名排序。"""
    talents: dict[str, TalentSpec] = {}
    for path in sorted(talents_dir.glob("*.yaml")):
        talents[path.stem] = load_talent(path.stem, talents_dir)
    return talents
