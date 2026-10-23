"""真实模型供应商：调用任意 OpenAI 兼容的 /chat/completions 接口。

仅在 MOCK_MODE=false 且已配置 OPENAI_API_KEY 时才会被实例化。
API Key 只从服务端环境变量读取，不写入代码或前端。
"""

import httpx

from backend.config import Settings
from backend.providers.base import BaseProvider, ProviderResponse


class OpenAICompatProvider(BaseProvider):
    def __init__(self, settings: Settings) -> None:
        if not settings.openai_api_key:
            raise ValueError(
                "MOCK_MODE=false 时必须提供 OPENAI_API_KEY（放在服务端环境变量中）"
            )
        self._settings = settings

    async def complete(self, system: str, user: str, *, model: str) -> ProviderResponse:
        url = f"{self._settings.openai_base_url.rstrip('/')}/chat/completions"
        payload = {
            "model": model or self._settings.default_model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        }
        async with httpx.AsyncClient(timeout=60) as client:
            response = await client.post(
                url,
                headers={"Authorization": f"Bearer {self._settings.openai_api_key}"},
                json=payload,
            )
            response.raise_for_status()
            data = response.json()

        usage = data.get("usage") or {}
        return ProviderResponse(
            text=data["choices"][0]["message"]["content"],
            model=data.get("model", model),
            input_tokens=usage.get("prompt_tokens", 0),
            output_tokens=usage.get("completion_tokens", 0),
        )
