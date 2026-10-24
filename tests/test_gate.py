"""机械门禁测试：全部基于真实 Chromium，不使用伪造结果。

重点验证贪吃蛇：页面加载、方向键、计分、结束后重开，以及人为注入的重开缺陷。
"""

import pytest

from backend.gate import run_mechanical_gate
from backend.providers.mock import SNAKE_HTML
from backend.schemas import GamePRD

PRD = GamePRD(
    title="贪吃蛇",
    genre="arcade",
    core_loop=["移动", "吃食物", "变长"],
    features=["计分", "随机食物", "游戏结束判定", "结束后可重新开始"],
    controls=["方向键移动"],
    win_condition="尽可能获得更高分数",
    lose_condition="撞墙或撞到自身",
)


def _status(report, check_id: str) -> str:
    return next(c.status for c in report.checks if c.id == check_id)


async def test_snake_passes_all_probes() -> None:
    report = await run_mechanical_gate(SNAKE_HTML, PRD)

    assert report.passed, report.model_dump_json(indent=2)
    assert _status(report, "page_load") == "pass"
    assert _status(report, "js_errors") == "pass"
    assert _status(report, "game_area") == "pass"
    assert _status(report, "arrow_keys") == "pass"
    assert _status(report, "score_updates") == "pass"
    assert _status(report, "restart_after_gameover") == "pass"
    assert report.failed_ids == []
    assert report.blocked_requests == []


async def test_broken_restart_is_detected() -> None:
    broken = SNAKE_HTML.replace(
        "restartBtn.addEventListener('click', reset);", "/* 重开被破坏 */"
    )
    assert broken != SNAKE_HTML

    report = await run_mechanical_gate(broken, PRD)

    assert not report.passed
    assert "restart_after_gameover" in report.failed_ids
    detail = next(
        c.detail for c in report.checks if c.id == "restart_after_gameover"
    )
    assert "over=True" in detail or "over=true" in detail.lower()


async def test_js_error_is_detected() -> None:
    html = "<html><body><canvas width='200' height='200'></canvas><script>throw new Error('boom')</script></body></html>"

    report = await run_mechanical_gate(html, PRD)

    assert not report.passed
    assert "js_errors" in report.failed_ids


async def test_external_network_is_blocked() -> None:
    html = (
        "<html><body><canvas width='200' height='200'></canvas>"
        "<script src='https://cdn.example.com/engine.js'></script></body></html>"
    )

    report = await run_mechanical_gate(html, PRD)

    assert report.blocked_requests
    assert any("cdn.example.com" in url for url in report.blocked_requests)
    assert _status(report, "network_isolation") == "pass"


async def test_missing_game_area_fails() -> None:
    html = "<html><body><h1>Hello</h1><script>var a=1</script></body></html>"

    report = await run_mechanical_gate(html, PRD)

    assert not report.passed
    assert "game_area" in report.failed_ids


async def test_gameplay_without_probe_is_marked_unverified() -> None:
    """没有探针的游戏不能假装玩法已验证。"""
    html = "<html><body><canvas width='320' height='240'></canvas><script>var a=1</script></body></html>"

    report = await run_mechanical_gate(html, PRD)

    assert "gameplay" in report.unverified_ids
    assert "gameplay" not in report.failed_ids


@pytest.mark.parametrize(
    ("check_id", "title"),
    [
        ("arrow_keys", "方向键改变方向"),
        ("score_updates", "得分会更新"),
        ("restart_after_gameover", "结束后可重新开始"),
    ],
)
async def test_probe_check_titles(check_id: str, title: str) -> None:
    report = await run_mechanical_gate(SNAKE_HTML, PRD)
    check = next(c for c in report.checks if c.id == check_id)
    assert check.title == title
