"""Vessel：统一负责模型调用、执行上下文、错误处理、日志与用量记录。

Talent 描述"这个员工是谁、能做什么"，Vessel 负责"怎么把它跑起来"。
"""

from __future__ import annotations

from dataclasses import dataclass

from onegamestudio.core.llm import BaseLLM
from onegamestudio.models.events import EventType, TraceEvent, Tracer
from onegamestudio.models.talent import TalentSpec


class VesselError(RuntimeError):
    """模型调用失败，已记录事件后抛出。"""


class BudgetExceededError(RuntimeError):
    """累计花费超出预算，停止继续调用。"""


@dataclass
class VesselResult:
    text: str
    model: str
    input_tokens: int
    output_tokens: int
    cost_usd: float


class Vessel:
    """一个可复用的执行容器，同一任务内的多个员工共享它来统计用量。"""

    def __init__(self, llm: BaseLLM, tracer: Tracer, *, budget_usd: float = 1.0) -> None:
        self._llm = llm
        self._tracer = tracer
        self._budget_usd = budget_usd
        self._spent_usd = 0.0

    @property
    def spent_usd(self) -> float:
        return self._spent_usd

    async def run(
        self, *, talent: TalentSpec, task_id: str, stage: str, prompt: str
    ) -> VesselResult:
        """执行一次员工任务。

        顺序固定为：预算检查 -> 记录开始 -> 调用模型 -> 记录结果 / 失败。
        任何一步异常都会留下事件，方便后续复盘。
        """
        if self._spent_usd >= self._budget_usd:
            raise BudgetExceededError(
                f"已花费 ${self._spent_usd:.4f}，达到预算上限 ${self._budget_usd:.4f}"
            )

        self._tracer.record(
            TraceEvent(
                task_id=task_id,
                type=EventType.STAGE_STARTED,
                stage=stage,
                message=f"{talent.name} 开始执行",
            )
        )

        try:
            response = await self._llm.complete(
                talent.system_prompt, prompt, model=talent.model
            )
        except Exception as exc:  # noqa: BLE001 - 统一包装为 VesselError
            self._tracer.record(
                TraceEvent(
                    task_id=task_id,
                    type=EventType.STAGE_FAILED,
                    stage=stage,
                    message=f"{talent.name} 执行失败：{exc}",
                )
            )
            raise VesselError(f"{talent.name} 执行失败：{exc}") from exc

        self._spent_usd += response.cost_usd
        self._tracer.record(
            TraceEvent(
                task_id=task_id,
                type=EventType.STAGE_COMPLETED,
                stage=stage,
                message=f"{talent.name} 完成，输出 {response.output_tokens} tokens",
                data={"model": response.model, "cost_usd": response.cost_usd},
            )
        )

        return VesselResult(
            text=response.text,
            model=response.model,
            input_tokens=response.input_tokens,
            output_tokens=response.output_tokens,
            cost_usd=response.cost_usd,
        )
