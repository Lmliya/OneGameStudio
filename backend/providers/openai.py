"""真实模型供应商：调用任意 OpenAI 兼容的 /chat/completions 接口。

模型名与密钥全部来自配置，业务代码不出现任何硬编码。
费用不由这里计算：BudgetGuard 按配置单价估算，接口没有返回 usage 时标记未知。
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
        if not settings.llm_model:
            raise ValueError("MOCK_MODE=false 时必须通过 LLM_MODEL 指定模型名称")
        self._settings = settings
        self.default_model = settings.llm_model

    async def complete(
        self,
        system: str,
        user: str,
        *,
        model: str,
        schema: str | None = None,
        max_tokens: int | None = None,
    ) -> ProviderResponse:
        if schema:
            system = f"{system}\n\n输出必须是符合 '{schema}' 契约的纯 JSON，不要包含代码块标记。"

        url = f"{self._settings.llm_base_url.rstrip('/')}/chat/completions"
        payload: dict = {
            "model": model or self.default_model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        }
        if max_tokens is not None and max_tokens > 0:
            payload["max_tokens"] = max_tokens

        async with httpx.AsyncClient(timeout=self._settings.request_timeout_seconds) as client:
            response = await client.post(
                url,
                headers={"Authorization": f"Bearer {self._settings.llm_api_key}"},
                json=payload,
            )
            response.raise_for_status()
            data = response.json()

        usage = data.get("usage") or {}
        has_usage = "prompt_tokens" in usage or "completion_tokens" in usage
        return ProviderResponse(
            text=data["choices"][0]["message"]["content"],
            model=data.get("model", model),
            input_tokens=int(usage.get("prompt_tokens", 0)) if has_usage else 0,
            output_tokens=int(usage.get("completion_tokens", 0)) if has_usage else 0,
            usage_source="provider" if has_usage else "unknown",
        )
