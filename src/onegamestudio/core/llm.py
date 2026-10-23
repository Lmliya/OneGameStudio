"""模型调用层：Mock 与真实 OpenAI 兼容客户端实现同一个接口。

这是 Mock 模式的关键设计：上层 Vessel 只依赖 BaseLLM，
所以切换 MOCK_MODE 不需要改动任何工作流代码。
"""

from __future__ import annotations

from abc import ABC, abstractmethod

import httpx
from pydantic import BaseModel

from onegamestudio.config import Settings


class LLMResponse(BaseModel):
    text: str
    model: str
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0


class BaseLLM(ABC):
    """所有模型实现的统一接口。"""

    @abstractmethod
    async def complete(self, system: str, user: str, *, model: str) -> LLMResponse:
        """给定系统提示词与用户输入，返回一段文本。"""


class MockLLM(BaseLLM):
    """离线假模型：不联网、不消耗 token、结果确定。

    它不是"假装成功"，而是把内容生成替换为按关键词匹配的模板，
    让整条工作流可以在没有 API Key 的情况下真实跑通并写测试。
    """

    # 关键词 -> 预置输出。后续阶段会扩充为完整的四员工模板。
    TEMPLATES: dict[str, str] = {
        "贪吃蛇": "【Mock】贪吃蛇需求已解析：核心循环为移动、吃食物、增长、碰撞判定。",
        "snake": "【Mock】Snake requirement parsed: move, eat, grow, collision.",
        "打砖块": "【Mock】打砖块需求已解析：挡板、球体反弹、砖块阵列、生命值。",
        "tetris": "【Mock】Tetris requirement parsed: falling blocks, rotation, line clear.",
    }

    async def complete(self, system: str, user: str, *, model: str) -> LLMResponse:
        text = self._render(user)
        return LLMResponse(
            text=text,
            model="mock",
            input_tokens=len(user) // 4,
            output_tokens=len(text) // 4,
            cost_usd=0.0,
        )

    def _render(self, user: str) -> str:
        lowered = user.lower()
        for key, template in self.TEMPLATES.items():
            if key in user or key in lowered:
                return template
        return f"【Mock】通用需求已接收：{user}"


class OpenAICompatLLM(BaseLLM):
    """真实模式：调用任意 OpenAI 兼容的 /chat/completions 接口。"""

    def __init__(self, settings: Settings) -> None:
        if not settings.openai_api_key:
            raise ValueError(
                "MOCK_MODE=false 时必须提供 OPENAI_API_KEY（放在服务端环境变量中）"
            )
        self._settings = settings

    async def complete(self, system: str, user: str, *, model: str) -> LLMResponse:
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
        return LLMResponse(
            text=data["choices"][0]["message"]["content"],
            model=data.get("model", model),
            input_tokens=usage.get("prompt_tokens", 0),
            output_tokens=usage.get("completion_tokens", 0),
        )


def build_llm(settings: Settings) -> BaseLLM:
    """根据配置决定使用假大脑还是真模型。"""
    if settings.mock_mode:
        return MockLLM()
    return OpenAICompatLLM(settings)
