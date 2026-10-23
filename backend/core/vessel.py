"""Vessel：员工统一执行容器。

Talent 描述"这个员工是谁"，Vessel 负责"怎么把它跑起来"：
加载配置 -> 选模型 -> 调供应商 -> 解析 JSON -> Pydantic 校验
-> 记录耗时与用量 -> 返回统一 AgentResult。
"""

from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ValidationError

from backend.models.events import EventType, TraceEvent, Tracer
from backend.models.talent import TalentSpec
from backend.providers.base import BaseProvider
from backend.schemas import OUTPUT_SCHEMAS
from backend.talents import TalentConfigError, load_talent


class VesselError(RuntimeError):
    """Vessel 执行失败的基类。"""


class TalentNotFoundError(VesselError):
    """指定的 Talent 不存在或配置非法。"""


class ProviderTimeoutError(VesselError):
    """模型调用超时。"""


class ProviderCallError(VesselError):
    """模型调用抛出的其他异常（网络、鉴权等）。"""


class OutputParseError(VesselError):
    """模型输出不是合法 JSON。"""


class OutputValidationError(VesselError):
    """JSON 合法但不符合输出契约。"""


class BudgetExceededError(VesselError):
    """累计花费超出预算。"""


class AgentResult(BaseModel):
    """一次员工执行的统一结果。"""

    talent: str
    model: str
    output: Any
    output_schema: str
    raw: str
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0
    duration_ms: int = 0


def _extract_json(raw: str) -> dict:
    """从原始文本中取出 JSON 对象，容忍 ```json 代码块包裹。"""
    text = raw.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        text = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise OutputParseError(f"输出中没有找到 JSON 对象：{raw[:120]}")
    try:
        data = json.loads(text[start : end + 1])
    except json.JSONDecodeError as exc:
        raise OutputParseError(f"JSON 解析失败：{exc}") from exc
    if not isinstance(data, dict):
        raise OutputParseError("JSON 顶层必须是对象")
    return data


class Vessel:
    def __init__(
        self,
        provider: BaseProvider,
        *,
        talents_dir: Path,
        default_model: str,
        timeout_seconds: float = 30.0,
        budget_usd: float = 1.0,
        tracer: Tracer | None = None,
    ) -> None:
        self._provider = provider
        self._talents_dir = talents_dir
        self._default_model = default_model
        self._timeout = timeout_seconds
        self._budget_usd = budget_usd
        self._tracer = tracer
        self._spent_usd = 0.0

    @property
    def spent_usd(self) -> float:
        return self._spent_usd

    def load(self, talent_id: str) -> TalentSpec:
        """加载并校验 Talent，未知工具/未知 schema 在这里被拒绝。"""
        try:
            return load_talent(talent_id, self._talents_dir)
        except TalentConfigError as exc:
            raise TalentNotFoundError(str(exc)) from exc

    async def execute(
        self, talent_id: str, context: str, *, task_id: str = "adhoc"
    ) -> AgentResult:
        """执行一次员工任务。所有失败都转换为明确的 VesselError 子类。"""
        talent = self.load(talent_id)
        model = talent.model or self._default_model

        if self._spent_usd >= self._budget_usd:
            raise BudgetExceededError(
                f"已花费 ${self._spent_usd:.4f}，达到预算上限 ${self._budget_usd:.4f}"
            )

        self._trace(task_id, talent, EventType.STAGE_STARTED, f"{talent.name} 开始执行")
        started = time.perf_counter()

        try:
            response = await asyncio.wait_for(
                self._provider.complete(
                    talent.system_prompt, context, model=model, schema=talent.output_schema
                ),
                timeout=self._timeout,
            )
        except asyncio.TimeoutError as exc:
            self._trace(task_id, talent, EventType.STAGE_FAILED, f"{talent.name} 调用超时")
            raise ProviderTimeoutError(
                f"{talent.name} 调用超时（>{self._timeout}s）"
            ) from exc
        except Exception as exc:  # noqa: BLE001 - 统一包装
            self._trace(task_id, talent, EventType.STAGE_FAILED, f"{talent.name} 调用失败：{exc}")
            raise ProviderCallError(f"{talent.name} 调用失败：{exc}") from exc

        duration_ms = int((time.perf_counter() - started) * 1000)

        # 解析与校验在调用之后进行，失败时同样留下事件
        try:
            output = self._validate(talent, response.text)
        except VesselError as exc:
            self._trace(task_id, talent, EventType.STAGE_FAILED, str(exc))
            raise

        self._spent_usd += response.cost_usd
        self._trace(
            task_id,
            talent,
            EventType.STAGE_COMPLETED,
            f"{talent.name} 完成，耗时 {duration_ms}ms",
        )

        return AgentResult(
            talent=talent.id,
            model=response.model,
            output=output,
            output_schema=talent.output_schema,
            raw=response.text,
            input_tokens=response.input_tokens,
            output_tokens=response.output_tokens,
            cost_usd=response.cost_usd,
            duration_ms=duration_ms,
        )

    def _validate(self, talent: TalentSpec, raw: str) -> BaseModel:
        """把原始文本解析并校验成对应契约对象。"""
        data = _extract_json(raw)
        schema_cls = OUTPUT_SCHEMAS[talent.output_schema]
        try:
            return schema_cls.model_validate(data)
        except ValidationError as exc:
            raise OutputValidationError(
                f"{talent.name} 输出不符合 '{talent.output_schema}' 契约：{exc}"
            ) from exc

    def _trace(
        self, task_id: str, talent: TalentSpec, event_type: EventType, message: str
    ) -> None:
        if self._tracer is None:
            return
        self._tracer.record(
            TraceEvent(
                task_id=task_id,
                type=event_type,
                stage=talent.id,
                message=message,
            )
        )
