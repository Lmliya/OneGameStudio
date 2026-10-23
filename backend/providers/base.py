"""模型供应商抽象层。

Vessel 只依赖 BaseProvider，因此切换 Mock / 真实模型不影响工作流代码。
"""

from abc import ABC, abstractmethod

from pydantic import BaseModel


class ProviderResponse(BaseModel):
    """一次模型调用的统一返回结构。"""

    text: str
    model: str
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0


class BaseProvider(ABC):
    """所有模型供应商的基类。"""

    default_model: str

    @abstractmethod
    async def complete(
        self,
        system: str,
        user: str,
        *,
        model: str,
        schema: str | None = None,
    ) -> ProviderResponse:
        """给定系统提示词与任务上下文，返回文本与用量。

        schema 用于告诉供应商期望的输出契约名称（Mock 据此返回对应结构的 JSON）。
        """
