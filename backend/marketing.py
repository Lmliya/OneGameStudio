"""营销素材的渲染与真实性校验。

Marketer 只允许宣传机械门禁真实验证过的功能，并且不得编造任何数据。
"""

from __future__ import annotations

import re

from backend.schemas import MarketingKit

# 编造数据检测：数字 + 用户/玩家/下载等口径
_FABRICATED = re.compile(
    r"(\d[\d,\.]*\s*(万|千|w|W|k|K)?\s*(用户|玩家|下载|安装|注册|DAU|MAU|粉丝))"
    r"|((用户|玩家|下载|安装|注册|粉丝)\s*[:：]?\s*\d[\d,\.]*)"
    r"|(破\s*\d+\s*(万|w|W))"
    r"|(\d+\s*(万|w|W)\s*\+)",
    re.I,
)


def find_fabricated_claims(kit: MarketingKit) -> list[str]:
    """返回文本中疑似编造的数据表述；空列表表示未发现。"""
    texts: list[str] = [
        kit.slogan,
        kit.positioning.one_liner,
        kit.positioning.core_gameplay,
        kit.positioning.target_players,
    ]
    for post in kit.posts:
        texts += [post.title, post.body]
    for day in kit.plan:
        texts += [day.goal, day.action, *day.assets, *day.metrics]

    hits: list[str] = []
    for text in texts:
        hits += [match.group(0) for match in _FABRICATED.finditer(text)]
    return hits


def render_marketing(kit: MarketingKit) -> str:
    """把结构化营销素材渲染成 markdown。"""
    pos = kit.positioning
    lines = [
        "# 营销素材",
        "",
        "## 游戏定位",
        "",
        f"- **游戏名称**：{pos.game_name}",
        f"- **核心玩法**：{pos.core_gameplay}",
        f"- **一句话卖点**：{pos.one_liner}",
        f"- **目标玩家**：{pos.target_players}",
        "",
        "## Slogan",
        "",
        f"> {kit.slogan}",
        "",
        "## 小红书文案",
        "",
    ]
    for index, post in enumerate(kit.posts, 1):
        label = "趣味体验向" if post.kind == "fun" else "挑战互动向"
        lines += [
            f"### 第 {index} 篇 · {label}",
            "",
            f"**标题**：{post.title}",
            "",
            post.body,
            "",
            f"**Emoji**：{' '.join(post.emojis)}",
            "",
            f"**话题标签**：{' '.join(post.hashtags)}",
            "",
        ]

    lines += ["## 首周推广计划", "", "| Day | 每日目标 | 推广动作 | 所需素材 | 可观察指标 |"]
    lines += ["| --- | --- | --- | --- | --- |"]
    for item in sorted(kit.plan, key=lambda d: d.day):
        assets = "、".join(item.assets) or "—"
        metrics = "、".join(item.metrics) or "—"
        lines.append(
            f"| Day {item.day} | {item.goal} | {item.action} | {assets} | {metrics} |"
        )
    lines.append("")
    return "\n".join(lines)
