"""模型供应商抽象层：Mock 与真实实现共用同一个接口。"""

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
    """所有模型供应商的基类。上层 Vessel 只依赖这个接口。"""

    @abstractmethod
    async def complete(self, system: str, user: str, *, model: str) -> ProviderResponse:
        """给定系统提示词与用户输入，返回文本与用量。"""
