"""Mock 模型供应商：不联网、不消耗 token、结果确定。

按 schema 名称返回结构合法的 JSON，让四个员工在没有 API Key 的情况下
也能被同一套 Vessel 独立执行与自动化测试。
Mock 不理解需求语义，只保证结构与流程正确。

审查策略：默认第一次审查不通过、第二次通过，用于演示一次完整的修复闭环。
"""

import json
import re

from backend.providers.base import BaseProvider, ProviderResponse

_SNAKE_HTML = """<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="UTF-8"><title>Snake</title>
<style>body{margin:0;background:#10131a;display:flex;justify-content:center;align-items:center;height:100vh}
canvas{background:#1a1f2b;border:2px solid #6ee7b7}</style></head>
<body><canvas id="c" width="400" height="400"></canvas>
<script>
const c=document.getElementById('c'),x=c.getContext('2d'),G=20;
let s=[{x:10,y:10}],d={x:1,y:0},f={x:15,y:10},score=0,dead=false;
document.addEventListener('keydown',e=>{const k=e.key;
if(k==='ArrowUp'&&d.y===0)d={x:0,y:-1};if(k==='ArrowDown'&&d.y===0)d={x:0,y:1};
if(k==='ArrowLeft'&&d.x===0)d={x:-1,y:0};if(k==='ArrowRight'&&d.x===0)d={x:1,y:0};});
function step(){if(dead)return;const h={x:s[0].x+d.x,y:s[0].y+d.y};
if(h.x<0||h.y<0||h.x>=G||h.y>=G||s.some(p=>p.x===h.x&&p.y===h.y)){dead=true;}
else{s.unshift(h);if(h.x===f.x&&h.y===f.y){score++;f={x:Math.floor(Math.random()*G),y:Math.floor(Math.random()*G)};}else s.pop();}}
function draw(){x.clearRect(0,0,400,400);x.fillStyle='#6ee7b7';s.forEach(p=>x.fillRect(p.x*G,p.y*G,G-1,G-1));
x.fillStyle='#fbbf24';x.fillRect(f.x*G,f.y*G,G-1,G-1);x.fillStyle='#8b93a7';
x.font='14px monospace';x.fillText('Score: '+score,8,18);if(dead)x.fillText('Game Over - refresh',130,200);}
setInterval(()=>{step();draw();},120);draw();
</script></body></html>"""

_PRIMARY_OUTPUTS: dict[str, dict] = {
    "prd": {
        "title": "贪吃蛇",
        "genre": "arcade",
        "core_loop": ["移动", "吃食物", "变长", "避免撞墙或撞到自己"],
        "features": ["计分", "随机食物", "游戏结束判定"],
        "controls": ["方向键移动"],
        "win_condition": "尽可能获得更高分数",
        "lose_condition": "撞墙或撞到自身",
    },
    "game": {
        "title": "贪吃蛇",
        "filename": "snake.html",
        "html": _SNAKE_HTML,
        "notes": "单文件 Canvas 2D 实现，无外部依赖",
    },
    "marketing": {
        "tagline": "一条蛇，一块屏幕，无限贪吃",
        "description": "经典贪吃蛇玩法，方向键操作，节奏轻快，适合碎片时间。",
        "hashtags": ["#贪吃蛇", "#休闲游戏", "#HTML5"],
        "channels": ["朋友圈", "游戏社区"],
    },
}

_REVIEW_FAIL = {
    "score": 55,
    "passed": False,
    "issues": [
        {
            "severity": "high",
            "description": "缺少计分与游戏结束提示",
            "suggestion": "在画面左上角显示分数，并在结束时给出重开提示",
        }
    ],
}

_REVIEW_PASS = {"score": 88, "passed": True, "issues": []}


def _review_attempt(user: str) -> int:
    match = re.search(r"审查轮次\s*:\s*(\d+)", user)
    return int(match.group(1)) if match else 1


class MockProvider(BaseProvider):
    default_model = "mock"

    def __init__(self, review_passes_from: int = 2) -> None:
        # 第 N 次及以后的审查返回通过；默认第 2 次通过
        self._review_passes_from = review_passes_from

    async def complete(
        self,
        system: str,
        user: str,
        *,
        model: str,
        schema: str | None = None,
    ) -> ProviderResponse:
        payload = self._payload(user, schema)
        text = json.dumps(payload, ensure_ascii=False)
        return ProviderResponse(
            text=text,
            model="mock",
            input_tokens=len(system + user) // 4,
            output_tokens=len(text) // 4,
            cost_usd=0.0,
        )

    def _payload(self, user: str, schema: str | None) -> dict:
        if schema == "review":
            attempt = _review_attempt(user)
            return (
                dict(_REVIEW_PASS)
                if attempt >= self._review_passes_from
                else dict(_REVIEW_FAIL)
            )
        if schema == "game":
            payload = dict(_PRIMARY_OUTPUTS["game"])
            if "审查意见" in user:
                payload["notes"] = "已按审查意见补充计分与结束提示"
            return payload
        return dict(_PRIMARY_OUTPUTS.get(schema or "prd", _PRIMARY_OUTPUTS["prd"]))
