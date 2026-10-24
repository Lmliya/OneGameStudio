"""Vessel：员工统一执行容器。

Talent 描述"这个员工是谁"，Vessel 负责"怎么把它跑起来"：
加载配置 -> 预算检查与模型选择 -> 调供应商（限并发 + 有限重试 + 超时）
-> 解析 JSON -> Pydantic 校验 -> 结算用量 -> 返回统一 AgentResult。
"""

from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ValidationError

from backend.budget import BudgetGuard
from backend.models.events import EventType, TokenUsage, TraceEvent, Tracer
from backend.models.talent import TalentSpec
from backend.providers.base import BaseProvider
from backend.schemas import OUTPUT_SCHEMAS
from backend.talents import TalentConfigError, load_talent


class VesselError(RuntimeError):
    """Vessel 执行失败的基类。"""


class TalentNotFoundError(VesselError):
    """指定的 Talent 不存在或配置非法。"""


class ProviderTimeoutError(VesselError):
    """模型调用超时（不重试，避免重复等待）。"""


class ProviderCallError(VesselError):
    """模型调用在重试用尽后仍然失败（网络、鉴权等）。"""


class OutputParseError(VesselError):
    """模型输出不是合法 JSON。"""


class OutputValidationError(VesselError):
    """JSON 合法但不符合输出契约。"""


class BudgetExceededError(VesselError):
    """预算达到上限，不再发起付费模型调用。"""


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
    usage_source: str = "provider"
    # 费用可信度：estimated = 按配置单价估算，unknown = 没有价格或没有真实用量
    cost_status: str = "unknown"
    budget_ratio: float | None = None
    downgraded: bool = False
    budget_reason: str = ""


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
        guard: BudgetGuard | None = None,
        max_output_tokens: int = 2048,
        max_concurrent_calls: int = 1,
        max_retries: int = 0,
        retry_backoff_seconds: float = 0.5,
    ) -> None:
        self._provider = provider
        self._talents_dir = talents_dir
        self._default_model = default_model
        self._timeout = timeout_seconds
        self._budget_usd = budget_usd
        self._tracer = tracer
        self._guard = guard
        self._max_output_tokens = max(1, max_output_tokens)
        self._max_retries = max(0, max_retries)
        self._retry_backoff = max(0.0, retry_backoff_seconds)
        # 显式限制并发调用：预算检查与调用之间的窗口越小，超额风险越低
        self._semaphore = asyncio.Semaphore(max(1, max_concurrent_calls))
        # 无 BudgetGuard 时的兼容路径：实例级累计花费
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
        preferred = talent.model or self._default_model
        model = preferred
        downgraded = False
        budget_reason = ""

        # ---------- Harness 5：调用前预算检查 ----------
        if self._guard is not None:
            decision = await self._guard.before_call(
                task_id, preferred, agent=talent.id
            )
            if not decision.allowed:
                raise BudgetExceededError(decision.reason)
            model = decision.model
            downgraded = decision.downgraded
            budget_reason = decision.reason
        elif self._spent_usd >= self._budget_usd:
            raise BudgetExceededError(
                f"已花费 ${self._spent_usd:.4f}，达到预算上限 ${self._budget_usd:.4f}"
            )

        self._trace(
            task_id,
            talent,
            EventType.STAGE_STARTED,
            f"{talent.name} 开始执行",
            model=model,
        )
        started = time.perf_counter()

        # ---------- Harness 4：限并发 + 有限重试 ----------
        attempts = self._max_retries + 1
        response = None
        last_error: Exception | None = None
        for attempt in range(attempts):
            try:
                async with self._semaphore:
                    response = await asyncio.wait_for(
                        self._provider.complete(
                            talent.system_prompt,
                            context,
                            model=model,
                            schema=talent.output_schema,
                            max_tokens=self._max_output_tokens,
                        ),
                        timeout=self._timeout,
                    )
                break
            except asyncio.TimeoutError as exc:
                duration_ms = int((time.perf_counter() - started) * 1000)
                self._trace(
                    task_id,
                    talent,
                    EventType.STAGE_FAILED,
                    f"{talent.name} 调用超时（>{self._timeout}s）",
                    model=model,
                    duration_ms=duration_ms,
                    error="timeout",
                )
                raise ProviderTimeoutError(
                    f"{talent.name} 调用超时（>{self._timeout}s）"
                ) from exc
            except Exception as exc:  # noqa: BLE001 - 统一包装
                last_error = exc
                duration_ms = int((time.perf_counter() - started) * 1000)
                self._trace(
                    task_id,
                    talent,
                    EventType.STAGE_FAILED,
                    f"{talent.name} 第 {attempt + 1} 次调用失败：{exc}",
                    model=model,
                    duration_ms=duration_ms,
                    error=str(exc),
                )
                if attempt + 1 < attempts:
                    await asyncio.sleep(self._retry_backoff * (2**attempt))

        if response is None:
            raise ProviderCallError(
                f"{talent.name} 调用失败（已重试 {self._max_retries} 次）：{last_error}"
            )

        duration_ms = int((time.perf_counter() - started) * 1000)
        usage = TokenUsage.of(
            response.input_tokens, response.output_tokens, response.usage_source
        )

        # 解析与校验在调用之后进行，失败时同样留下事件
        try:
            output = self._validate(talent, response.text)
        except VesselError as exc:
            self._trace(
                task_id,
                talent,
                EventType.STAGE_FAILED,
                str(exc),
                model=model,
                duration_ms=duration_ms,
                token_usage=usage,
                error=str(exc),
            )
            raise

        # ---------- Harness 5：调用后记账 ----------
        if self._guard is not None:
            record = await self._guard.after_call(
                task_id,
                agent=talent.id,
                model=model,
                input_tokens=response.input_tokens,
                output_tokens=response.output_tokens,
                usage_source=response.usage_source,
                duration_ms=duration_ms,
                downgraded=downgraded,
            )
            snapshot = self._guard.snapshot(task_id)
            cost_usd = record.estimated_cost_usd or 0.0
            cost_status = record.cost_status
            budget_ratio = snapshot.ratio
        else:
            self._spent_usd += response.cost_usd
            cost_usd = response.cost_usd
            cost_status = "estimated" if response.cost_usd else "unknown"
            budget_ratio = (
                self._spent_usd / self._budget_usd if self._budget_usd > 0 else 1.0
            )

        self._trace(
            task_id,
            talent,
            EventType.STAGE_COMPLETED,
            f"{talent.name} 完成，耗时 {duration_ms}ms",
            model=model,
            duration_ms=duration_ms,
            token_usage=usage,
        )

        return AgentResult(
            talent=talent.id,
            model=response.model,
            output=output,
            output_schema=talent.output_schema,
            raw=response.text,
            input_tokens=response.input_tokens,
            output_tokens=response.output_tokens,
            cost_usd=cost_usd,
            duration_ms=duration_ms,
            usage_source=response.usage_source,
            cost_status=cost_status,
            budget_ratio=budget_ratio,
            downgraded=downgraded,
            budget_reason=budget_reason,
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
        self,
        task_id: str,
        talent: TalentSpec,
        event_type: EventType,
        message: str,
        *,
        model: str | None = None,
        duration_ms: int | None = None,
        token_usage: TokenUsage | None = None,
        error: str | None = None,
    ) -> None:
        if self._tracer is None:
            return
        self._tracer.record(
            TraceEvent(
                task_id=task_id,
                type=event_type,
                stage=talent.id,
                message=message,
                agent=talent.id,
                model=model,
                duration_ms=duration_ms,
                token_usage=token_usage,
                result="failed" if event_type is EventType.STAGE_FAILED else "ok",
                error=error,
            )
        )
