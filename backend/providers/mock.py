"""Mock 模型供应商：不联网、不消耗 token、结果确定。

它不是"假装成功"，而是把内容生成替换为按关键词匹配的模板，
让整条工作流能在没有 API Key 的情况下真实跑通并写自动化测试。
"""

from backend.providers.base import BaseProvider, ProviderResponse


class MockProvider(BaseProvider):
    # 关键词 -> 预置输出。后续阶段会按四个员工分别扩充。
    TEMPLATES: dict[str, str] = {
        "贪吃蛇": "【Mock】贪吃蛇需求已解析：移动、吃食物、增长、碰撞判定。",
        "snake": "【Mock】Snake requirement parsed: move, eat, grow, collision.",
        "打砖块": "【Mock】打砖块需求已解析：挡板、球体反弹、砖块阵列、生命值。",
        "tetris": "【Mock】Tetris requirement parsed: falling blocks, rotation, line clear.",
    }

    async def complete(self, system: str, user: str, *, model: str) -> ProviderResponse:
        text = self._render(user)
        return ProviderResponse(
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
