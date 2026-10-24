"""供应商工厂：根据配置决定使用 Mock 还是真实模型。"""

from backend.config import Settings
from backend.providers.base import BaseProvider, ProviderResponse
from backend.providers.mock import MockProvider
from backend.providers.openai import OpenAICompatibleProvider

__all__ = [
    "BaseProvider",
    "ProviderResponse",
    "MockProvider",
    "OpenAICompatibleProvider",
    "MissingKeyProvider",
    "build_provider",
]


class MissingKeyProvider(BaseProvider):
    """Live 模式缺少密钥时的占位供应商。

    Live 模式未配置 LLM_API_KEY / LLM_MODEL 时服务仍可启动，
    便于 /api/health 暴露 live_ready=false；任务创建会被 503 拦截，
    即使有代码绕过门禁，这里也会直接失败，不会发起付费调用。
    """

    default_model = "unavailable"

    async def complete(self, *args, **kwargs) -> ProviderResponse:
        raise RuntimeError("Live 模式缺少 LLM_API_KEY，已拒绝调用真实模型")


def build_provider(settings: Settings) -> BaseProvider:
    if settings.mock_mode:
        return MockProvider()
    if not settings.llm_api_key or not settings.llm_model:
        return MissingKeyProvider()
    return OpenAICompatibleProvider(settings)
