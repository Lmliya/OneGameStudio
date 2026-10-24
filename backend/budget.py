"""Harness 5：Budget Guard（预算守卫）。

职责边界：
- 只做「调用前决策 + 调用后记账」，不负责发起模型调用。
- 单价与模型名全部来自配置，代码里不写死任何模型名称或价格。
- `estimated_cost_usd` 是按配置单价 × token 数得到的**估算**，不是供应商账单；
  拿不到真实用量或没有配置单价时，一律标记 unknown，绝不填 0 冒充真实费用。

并发限制：
- 预算检查与调用之间存在时间窗，并发调用可能让花费超过上限。
- 这里用 asyncio.Lock 串行化「检查 + 记账」，同时 Vessel 用信号量限制并发数，
  使超额最多只可能发生在「一个并发槽位的一次调用」范围内。
"""

from __future__ import annotations

import asyncio
import json
from typing import Literal

from pydantic import BaseModel, Field, ValidationError

UsageSource = Literal["provider", "estimated", "unknown"]
CostStatus = Literal["estimated", "unknown"]


class BudgetConfigError(RuntimeError):
    """预算相关配置非法（如 MODEL_PRICES 不是合法 JSON）。"""


class ModelPrice(BaseModel):
    """每 1K token 的单价，由配置提供。"""

    input_per_1k: float = Field(ge=0)
    output_per_1k: float = Field(ge=0)


class TaskBudget(BaseModel):
    """单个任务的预算快照，随 task.json 一起落盘。"""

    task_id: str
    budget_usd: float = 1.0
    spent_usd: float = 0.0  # 估算值，不是账单
    calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    unknown_usage_calls: int = 0
    unknown_cost_calls: int = 0
    downgraded_calls: int = 0
    blocked_calls: int = 0
    models: dict[str, int] = Field(default_factory=dict)

    @property
    def ratio(self) -> float:
        """已用预算比例；预算为 0 时视为已用满。"""
        if self.budget_usd <= 0:
            return 1.0
        return self.spent_usd / self.budget_usd

    @property
    def cost_status(self) -> CostStatus:
        """只要出现过无法估算的调用，整体费用就只能标记为 unknown。"""
        return "unknown" if self.unknown_cost_calls else "estimated"


class UsageRecord(BaseModel):
    """一次调用的记账结果。"""

    agent: str
    model: str
    input_tokens: int = 0
    output_tokens: int = 0
    usage_source: UsageSource = "unknown"
    estimated_cost_usd: float | None = None
    cost_status: CostStatus = "unknown"
    duration_ms: int = 0
    downgraded: bool = False


class BudgetDecision(BaseModel):
    """调用前决策结果。"""

    allowed: bool
    model: str
    downgraded: bool = False
    reason: str = ""
    budget: TaskBudget


class BudgetGuard:
    def __init__(
        self,
        *,
        task_budget_usd: float = 1.0,
        light_model: str = "",
        soft_ratio: float = 0.7,
        prices: dict[str, ModelPrice] | None = None,
        max_output_tokens: int = 2048,
    ) -> None:
        self._default_budget = max(0.0, task_budget_usd)
        self._light_model = light_model.strip()
        self._soft_ratio = min(max(soft_ratio, 0.0), 1.0)
        self._prices = dict(prices or {})
        self.max_output_tokens = max(1, max_output_tokens)
        self._state: dict[str, TaskBudget] = {}
        self._lock = asyncio.Lock()

    # ---------- 构造辅助 ----------

    @classmethod
    def from_settings(cls, settings) -> "BudgetGuard":
        """从全局配置构建；MODEL_PRICES 非法时直接报错而不是静默忽略。"""
        return cls(
            task_budget_usd=settings.budget_usd,
            light_model=settings.light_model,
            soft_ratio=settings.budget_soft_ratio,
            prices=parse_model_prices(settings.model_prices),
            max_output_tokens=settings.max_output_tokens,
        )

    # ---------- 状态 ----------

    def register(self, task_id: str, budget_usd: float | None = None) -> TaskBudget:
        state = TaskBudget(
            task_id=task_id,
            budget_usd=self._default_budget if budget_usd is None else max(0.0, budget_usd),
        )
        self._state[task_id] = state
        return state

    def snapshot(self, task_id: str) -> TaskBudget:
        return self._state.setdefault(
            task_id, TaskBudget(task_id=task_id, budget_usd=self._default_budget)
        ).model_copy(deep=True)

    async def before_call(
        self, task_id: str, preferred_model: str, *, agent: str = ""
    ) -> BudgetDecision:
        """调用前检查：是否允许、用哪个模型。"""
        async with self._lock:
            state = self._state.get(task_id)
            if state is None:
                state = self.register(task_id)

            if state.ratio >= 1.0:
                state.blocked_calls += 1
                return BudgetDecision(
                    allowed=False,
                    model=preferred_model,
                    reason=(
                        f"任务预算已用尽（估算 ${state.spent_usd:.4f} / "
                        f"预算 ${state.budget_usd:.4f}），不再发起付费模型调用"
                    ),
                    budget=state.model_copy(deep=True),
                )

            model = preferred_model
            downgraded = False
            reason = ""
            if (
                self._light_model
                and preferred_model
                and state.ratio >= self._soft_ratio
                and preferred_model != self._light_model
            ):
                model = self._light_model
                downgraded = True
                reason = (
                    f"已用预算 {state.ratio:.0%} ≥ {self._soft_ratio:.0%}，"
                    f"降级到轻量模型 {self._light_model}"
                )
            return BudgetDecision(
                allowed=True,
                model=model,
                downgraded=downgraded,
                reason=reason,
                budget=state.model_copy(deep=True),
            )

    async def after_call(
        self,
        task_id: str,
        *,
        agent: str,
        model: str,
        input_tokens: int,
        output_tokens: int,
        usage_source: UsageSource,
        duration_ms: int = 0,
        downgraded: bool = False,
    ) -> UsageRecord:
        """调用后记账，返回本次估算费用与可信度。"""
        async with self._lock:
            state = self._state.setdefault(
                task_id, TaskBudget(task_id=task_id, budget_usd=self._default_budget)
            )
            state.calls += 1
            state.models[model] = state.models.get(model, 0) + 1
            state.input_tokens += max(0, input_tokens)
            state.output_tokens += max(0, output_tokens)
            if downgraded:
                state.downgraded_calls += 1
            if usage_source == "unknown":
                state.unknown_usage_calls += 1

            price = self._prices.get(model)
            if usage_source == "unknown" or price is None:
                # 没有真实用量或没有配置单价：不臆造价格
                state.unknown_cost_calls += 1
                return UsageRecord(
                    agent=agent,
                    model=model,
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    usage_source=usage_source,
                    estimated_cost_usd=None,
                    cost_status="unknown",
                    duration_ms=duration_ms,
                    downgraded=downgraded,
                )

            cost = (
                input_tokens / 1000 * price.input_per_1k
                + output_tokens / 1000 * price.output_per_1k
            )
            state.spent_usd += cost
            return UsageRecord(
                agent=agent,
                model=model,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                usage_source=usage_source,
                estimated_cost_usd=cost,
                cost_status="estimated",
                duration_ms=duration_ms,
                downgraded=downgraded,
            )


def parse_model_prices(raw: str) -> dict[str, ModelPrice]:
    """解析配置中的 MODEL_PRICES：{"模型名": {"input_per_1k": x, "output_per_1k": y}}。"""
    text = (raw or "").strip()
    if not text:
        return {}
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise BudgetConfigError(f"MODEL_PRICES 不是合法 JSON：{exc}") from exc
    if not isinstance(data, dict):
        raise BudgetConfigError("MODEL_PRICES 顶层必须是对象")
    prices: dict[str, ModelPrice] = {}
    for model, value in data.items():
        try:
            prices[model] = ModelPrice.model_validate(value)
        except ValidationError as exc:
            raise BudgetConfigError(f"MODEL_PRICES[{model}] 格式非法：{exc}") from exc
    return prices
