"""真实模型供应商：调用任意 OpenAI 兼容的 /chat/completions 接口。

模型名与密钥全部来自配置，业务代码不出现任何硬编码。
"""

import httpx

from backend.config import Settings
from backend.providers.base import BaseProvider, ProviderResponse


class OpenAICompatibleProvider(BaseProvider):
    def __init__(self, settings: Settings) -> None:
        if not settings.llm_api_key:
            raise ValueError(
                "MOCK_MODE=false 时必须提供 LLM_API_KEY（放在服务端环境变量中）"
            )
        self._settings = settings
        self.default_model = settings.llm_model

    async def complete(
        self,
        system: str,
        user: str,
        *,
        model: str,
        schema: str | None = None,
    ) -> ProviderResponse:
        if schema:
            system = f"{system}\n\n输出必须是符合 '{schema}' 契约的纯 JSON，不要包含代码块标记。"

        url = f"{self._settings.llm_base_url.rstrip('/')}/chat/completions"
        payload = {
            "model": model or self.default_model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        }
        async with httpx.AsyncClient(timeout=self._settings.request_timeout_seconds) as client:
            response = await client.post(
                url,
                headers={"Authorization": f"Bearer {self._settings.llm_api_key}"},
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
