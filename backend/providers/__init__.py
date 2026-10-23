"""供应商工厂：根据配置决定使用 Mock 还是真实模型。"""

from backend.config import Settings
from backend.providers.base import BaseProvider, ProviderResponse
from backend.providers.mock import MockProvider
from backend.providers.openai import OpenAICompatProvider

__all__ = ["BaseProvider", "ProviderResponse", "MockProvider", "build_provider"]


def build_provider(settings: Settings) -> BaseProvider:
    if settings.mock_mode:
        return MockProvider()
    return OpenAICompatProvider(settings)
