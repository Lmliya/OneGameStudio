"""Mock 模型供应商：不联网、不消耗 token、结果确定。

按 schema 名称返回结构合法的 JSON，让四个员工在没有 API Key 的情况下
也能被同一套 Vessel 独立执行与自动化测试。
Mock 不理解需求语义，只保证结构与流程正确。

审查策略：默认第一次审查不通过、第二次通过，用于演示一次完整的修复闭环。
"""

import json
import re

from backend.providers.base import BaseProvider, ProviderResponse

# 贪吃蛇：可被机械门禁用探针确定性驱动（方向 / 计分 / 重开）
SNAKE_HTML = """<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="UTF-8"><title>Snake</title>
<style>
  body{margin:0;background:#10131a;color:#e6e8ee;font-family:monospace;
       display:flex;flex-direction:column;align-items:center;justify-content:center;height:100vh}
  #hud{margin-bottom:8px;font-size:14px}
  canvas{background:#161b26;border:2px solid #6ee7b7}
  #restart{margin-top:10px;padding:6px 14px;background:#6ee7b7;border:0;border-radius:4px;cursor:pointer}
</style></head>
<body>
<div id="hud">Score: <span id="score">0</span></div>
<canvas id="game" width="400" height="400"></canvas>
<button id="restart" hidden>重新开始</button>
<script>
(function () {
  var CELL = 20, COLS = 20, TICK = 120;
  var canvas = document.getElementById('game');
  var ctx = canvas.getContext('2d');
  var scoreEl = document.getElementById('score');
  var restartBtn = document.getElementById('restart');
  var snake, dir, food, score, over, timer;

  function randCell() { return Math.floor(Math.random() * COLS); }
  function placeFood() {
    var p;
    do { p = { x: randCell(), y: randCell() }; }
    while (snake.some(function (s) { return s.x === p.x && s.y === p.y; }));
    food = p;
  }
  function draw() {
    ctx.fillStyle = '#161b26'; ctx.fillRect(0, 0, 400, 400);
    ctx.fillStyle = '#6ee7b7';
    snake.forEach(function (s) { ctx.fillRect(s.x * CELL, s.y * CELL, CELL - 2, CELL - 2); });
    ctx.fillStyle = '#fbbf24';
    ctx.fillRect(food.x * CELL, food.y * CELL, CELL - 2, CELL - 2);
    if (over) {
      ctx.fillStyle = 'rgba(0,0,0,.62)'; ctx.fillRect(0, 0, 400, 400);
      ctx.fillStyle = '#fff'; ctx.font = '20px monospace';
      ctx.fillText('Game Over', 140, 200);
    }
  }
  function tick() {
    if (over) return;
    var head = { x: snake[0].x + dir.x, y: snake[0].y + dir.y };
    var hitWall = head.x < 0 || head.y < 0 || head.x >= COLS || head.y >= COLS;
    var hitSelf = snake.some(function (s) { return s.x === head.x && s.y === head.y; });
    if (hitWall || hitSelf) {
      over = true; clearInterval(timer); restartBtn.hidden = false; draw(); return;
    }
    snake.unshift(head);
    if (head.x === food.x && head.y === food.y) {
      score += 1; scoreEl.textContent = String(score); placeFood();
    } else {
      snake.pop();
    }
    draw();
  }
  function reset() {
    snake = [{ x: 10, y: 10 }];
    dir = { x: 1, y: 0 };
    score = 0; over = false;
    placeFood();
    scoreEl.textContent = '0';
    restartBtn.hidden = true;
    if (timer) clearInterval(timer);
    timer = setInterval(tick, TICK);
    draw();
  }
  document.addEventListener('keydown', function (e) {
    if (e.key === 'ArrowUp' && dir.y === 0) dir = { x: 0, y: -1 };
    else if (e.key === 'ArrowDown' && dir.y === 0) dir = { x: 0, y: 1 };
    else if (e.key === 'ArrowLeft' && dir.x === 0) dir = { x: -1, y: 0 };
    else if (e.key === 'ArrowRight' && dir.x === 0) dir = { x: 1, y: 0 };
  });
  restartBtn.addEventListener('click', reset);

  // 测试探针：只读状态 + 摆放食物，不改变游戏规则
  window.__ogsProbe = {
    version: 1,
    state: function () {
      return { dir: { x: dir.x, y: dir.y }, score: score, over: over,
               head: { x: snake[0].x, y: snake[0].y }, length: snake.length, tickMs: TICK };
    },
    placeFood: function (x, y) { food = { x: x, y: y }; }
  };

  reset();
})();
</script></body></html>"""

_PRIMARY_OUTPUTS: dict[str, dict] = {
    "prd": {
        "title": "贪吃蛇",
        "genre": "arcade",
        "core_loop": ["移动", "吃食物", "变长", "避免撞墙或撞到自己"],
        "features": ["计分", "随机食物", "游戏结束判定", "结束后可重新开始"],
        "controls": ["方向键移动"],
        "win_condition": "尽可能获得更高分数",
        "lose_condition": "撞墙或撞到自身",
    },
    "game": {
        "title": "贪吃蛇",
        "filename": "snake.html",
        "html": SNAKE_HTML,
        "notes": "单文件 Canvas 2D 实现，无外部依赖",
    },
}

_REVIEW_FAIL = {
    "verdict": "ITERATE",
    "issues": [
        {
            "severity": "high",
            "description": "缺少计分与游戏结束提示",
            "suggestion": "在画面上方显示分数，并在结束时显示可点击的重新开始按钮",
        }
    ],
    "suggestions": ["补充计分 UI 与结束后重开入口"],
    "summary": "核心玩法存在，但缺少反馈与恢复入口，暂不交付。",
}

_REVIEW_PASS = {
    "verdict": "PASS",
    "issues": [],
    "suggestions": [],
    "summary": "玩法与 PRD 一致，机械门禁通过，可交付。",
}


MARKETING_PAYLOAD: dict = {
    "positioning": {
        "game_name": "贪吃蛇",
        "core_gameplay": "方向键控制蛇吃食物变长，撞墙或撞到自己即结束",
        "one_liner": "三分钟一局，看你能把这条蛇养多长",
        "target_players": "喜欢碎片化休闲游戏的玩家",
    },
    "slogan": "摸鱼三分钟，你能让这条蛇活多久？",
    "posts": [
        {
            "kind": "fun",
            "title": "上班摸鱼神器，这条蛇我玩到停不下来",
            "body": (
                "一条蛇，一块屏幕，一个下午。\n"
                "方向键控制，规则简单到不用看教程，"
                "吃一个苹果长一截，撞墙就重来。"
                "卡壳的时候来两把，脑子反而清醒了。"
            ),
            "emojis": ["🐍", "🍎", "🎮"],
            "hashtags": ["#贪吃蛇", "#摸鱼日常", "#休闲游戏"],
        },
        {
            "kind": "challenge",
            "title": "挑战：连续吃 10 个苹果不撞墙，你能做到吗",
            "body": (
                "规则就一条：别撞墙，也别咬到自己。\n"
                "越到后面越长，转弯的余地越小。"
                "玩完在评论区报一下你的最高分，看看谁更能憋。"
            ),
            "emojis": ["🔥", "🏆", "👀"],
            "hashtags": ["#游戏挑战", "#贪吃蛇", "#手速"],
        },
    ],
    "plan": [
        {
            "day": 1,
            "goal": "让身边人先玩上",
            "action": "把游戏链接发到同学群，收集最直接的操作反馈",
            "assets": ["游戏链接", "一句话卖点"],
            "metrics": ["试玩人数", "评论数"],
        },
        {
            "day": 2,
            "goal": "发布第一篇体验向笔记",
            "action": "发布摸鱼场景的小红书笔记",
            "assets": ["第一篇文案", "游戏截图"],
            "metrics": ["曝光量", "收藏数"],
        },
        {
            "day": 3,
            "goal": "收集真实玩家分数",
            "action": "在笔记评论区发起晒分",
            "assets": ["评论区引导话术"],
            "metrics": ["评论数", "互动率"],
        },
        {
            "day": 4,
            "goal": "发布第二篇挑战向笔记",
            "action": "发布挑战文案，引导用户晒最高分",
            "assets": ["第二篇文案", "挑战规则图"],
            "metrics": ["点击率", "点赞数"],
        },
        {
            "day": 5,
            "goal": "沉淀玩法说明",
            "action": "整理一份新手三句话攻略",
            "assets": ["攻略图文"],
            "metrics": ["收藏数"],
        },
        {
            "day": 6,
            "goal": "观察留存",
            "action": "对比两篇笔记带来的复访情况",
            "assets": ["数据记录表"],
            "metrics": ["二次访问率"],
        },
        {
            "day": 7,
            "goal": "复盘首周",
            "action": "汇总有效动作，确定下一周只保留表现最好的渠道",
            "assets": ["首周复盘文档"],
            "metrics": ["互动总量", "有效反馈条数"],
        },
    ],
}


def _review_attempt(user: str) -> int:
    match = re.search(r"审查轮次\s*:\s*(\d+)", user)
    return int(match.group(1)) if match else 1


class MockProvider(BaseProvider):
    default_model = "mock"

    def __init__(self, review_passes_from: int = 2) -> None:
        # 第 N 次及以后的审查返回 PASS；默认第 2 次通过
        self._review_passes_from = review_passes_from

    async def complete(
        self,
        system: str,
        user: str,
        *,
        model: str,
        schema: str | None = None,
        max_tokens: int | None = None,
    ) -> ProviderResponse:
        _ = max_tokens  # Mock 不限制输出长度
        payload = self._payload(user, schema)
        text = json.dumps(payload, ensure_ascii=False)
        return ProviderResponse(
            text=text,
            model=model or self.default_model,
            input_tokens=len(system + user) // 4,
            output_tokens=len(text) // 4,
            cost_usd=0.0,
            # Mock 的 token 是按字符数估算，不是真实用量
            usage_source="estimated",
        )

    def _payload(self, user: str, schema: str | None) -> dict:
        if schema == "review":
            attempt = _review_attempt(user)
            return (
                json.loads(json.dumps(_REVIEW_PASS))
                if attempt >= self._review_passes_from
                else json.loads(json.dumps(_REVIEW_FAIL))
            )
        if schema == "game":
            payload = dict(_PRIMARY_OUTPUTS["game"])
            if "审查意见" in user:
                payload["notes"] = "已按审查意见补充计分与结束提示"
            return payload
        if schema == "marketing":
            return json.loads(json.dumps(MARKETING_PAYLOAD))
        return json.loads(
            json.dumps(_PRIMARY_OUTPUTS.get(schema or "prd", _PRIMARY_OUTPUTS["prd"]))
        )
