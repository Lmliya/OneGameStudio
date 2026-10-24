"""第一层机械门禁：用真实浏览器验证生成游戏的确定性行为。

安全边界（生成的 HTML 视为不可信代码）：
- 通过 `page.set_content()` 注入，不授予任何服务端文件路径。
- 每次新建浏览器上下文，无 cookie / localStorage / 权限 / API Key。
- 除 `data:` / `about:` / `blob:` 外的所有请求一律拦截并记录，默认断开外网。
- 全流程有总超时上限，任何路径都会关闭浏览器。
- 只做"观察与输入"，不读取环境变量，也不执行 shell。
"""

from __future__ import annotations

import asyncio
import os
import re
import time

from playwright.async_api import Error as PlaywrightError
from playwright.async_api import async_playwright

from backend.schemas import GamePRD, GateCheck, MechanicalReport

# 允许的内联源；其余请求一律阻断
_ALLOWED_PREFIXES = ("data:", "about:", "blob:")

_RESTART_PATTERN = re.compile(r"重新开始|再来一局|再玩一次|重开|restart|start|开始", re.I)

_GAME_AREA_JS = """
() => {
  const canvas = document.querySelector('canvas');
  if (canvas && canvas.width > 0 && canvas.height > 0) {
    return { kind: 'canvas', desc: `canvas ${canvas.width}x${canvas.height}` };
  }
  const el = document.querySelector('[id*="game" i], [class*="game" i], [id*="stage" i]');
  if (el) {
    const r = el.getBoundingClientRect();
    if (r.width > 0 && r.height > 0) {
      return { kind: 'element', desc: `元素 ${el.tagName.toLowerCase()} ${Math.round(r.width)}x${Math.round(r.height)}` };
    }
  }
  return null;
}
"""

_FIND_RESTART_JS = """
() => {
  const pat = /重新开始|再来一局|再玩一次|重开|restart|start|开始/i;
  const nodes = [...document.querySelectorAll('button, [role=button], a, input[type=button]')];
  const hit = nodes.find(n => pat.test((n.textContent || n.value || '').trim()));
  return hit ? (hit.textContent || hit.value || '').trim() : null;
}
"""

_CLICK_RESTART_JS = """
() => {
  const pat = /重新开始|再来一局|再玩一次|重开|restart|start|开始/i;
  const nodes = [...document.querySelectorAll('button, [role=button], a, input[type=button]')];
  const hit = nodes.find(n => pat.test((n.textContent || n.value || '').trim()));
  if (!hit) return false;
  hit.click();
  return true;
}
"""


class GateUnavailableError(RuntimeError):
    """浏览器不可用（未安装 Chromium 等）。"""


def _check(id: str, title: str, status: str, detail: str = "") -> GateCheck:
    return GateCheck(id=id, title=title, status=status, detail=detail)


def _html_structure(html: str) -> GateCheck:
    lowered = html.lower()
    missing = [
        tag
        for tag in ("<html", "<body", "<script")
        if tag not in lowered
    ]
    if not html.strip():
        return _check("html_structure", "HTML 基本结构", "fail", "index.html 为空")
    if missing:
        return _check(
            "html_structure", "HTML 基本结构", "fail", "缺少：" + "、".join(missing)
        )
    return _check("html_structure", "HTML 基本结构", "pass", "包含 html/body/script")


async def run_mechanical_gate(
    html: str,
    prd: GamePRD,
    *,
    timeout_ms: int = 8000,
    overall_timeout_s: float = 30.0,
) -> MechanicalReport:
    """执行全部机械检查。任何一项 fail 都会让 passed 为 False。"""
    started = time.perf_counter()
    checks: list[GateCheck] = [_html_structure(html)]
    blocked: list[str] = []

    if checks[0].status == "fail":
        return MechanicalReport(
            passed=False, checks=checks, duration_ms=_ms(started)
        )

    try:
        await asyncio.wait_for(
            _inspect(html, prd, checks, blocked, timeout_ms), overall_timeout_s
        )
    except asyncio.TimeoutError:
        checks.append(
            _check("gate_timeout", "门禁总超时", "fail", f"超过 {overall_timeout_s}s 未完成")
        )
    except GateUnavailableError:
        raise
    except PlaywrightError as exc:
        checks.append(
            _check("browser_error", "浏览器执行异常", "fail", str(exc)[:200])
        )

    return MechanicalReport(
        passed=all(c.status != "fail" for c in checks),
        checks=checks,
        blocked_requests=blocked,
        duration_ms=_ms(started),
    )


def _ms(started: float) -> int:
    return int((time.perf_counter() - started) * 1000)


async def _launch_browser(playwright):
    """优先用 Playwright 自带 Chromium；不可用时退化为系统 Chrome。

    离线或下载失败的环境里，bundled Chromium 往往装不上，系统 Chrome 仍然可用。
    """
    attempts = [
        ("bundled chromium", {}),
        ("system chrome", {"channel": "chrome"}),
    ]
    browser_path = os.environ.get("OGS_BROWSER_PATH")
    if browser_path:
        attempts.append(("OGS_BROWSER_PATH", {"executable_path": browser_path}))

    last_error: Exception | None = None
    for _label, kwargs in attempts:
        try:
            return await playwright.chromium.launch(headless=True, **kwargs)
        except PlaywrightError as exc:
            last_error = exc

    raise GateUnavailableError(
        "无法启动 Chromium。请执行 `uv run playwright install chromium`，"
        "或安装 Google Chrome / 设置 OGS_BROWSER_PATH 指向可执行文件。"
        f" 最后一次错误：{last_error}"
    )


async def _inspect(
    html: str,
    prd: GamePRD,
    checks: list[GateCheck],
    blocked: list[str],
    timeout_ms: int,
) -> None:
    try:
        playwright = await async_playwright().start()
    except PlaywrightError as exc:  # pragma: no cover - 环境相关
        raise GateUnavailableError(
            "无法启动 Playwright，请先执行 `uv run playwright install chromium`"
        ) from exc

    browser = None
    try:
        browser = await _launch_browser(playwright)

        context = await browser.new_context(
            java_script_enabled=True,
            offline=False,
            bypass_csp=False,
            service_workers="block",
        )

        async def _guard(route) -> None:
            url = route.request.url
            if url.startswith(_ALLOWED_PREFIXES):
                await route.continue_()
            else:
                blocked.append(url)
                await route.abort()

        await context.route("**/*", _guard)

        page = await context.new_page()
        js_errors: list[str] = []
        page.on("pageerror", lambda exc: js_errors.append(str(exc)))

        # 1) 页面能否加载
        try:
            await page.set_content(html, wait_until="load", timeout=timeout_ms)
            checks.append(_check("page_load", "页面加载", "pass", "DOMContentLoaded 完成"))
        except PlaywrightError as exc:
            checks.append(_check("page_load", "页面加载", "fail", str(exc)[:200]))
            return

        await page.wait_for_timeout(300)

        # 2) 未处理的 JS 错误
        if js_errors:
            checks.append(
                _check("js_errors", "无未处理 JS 错误", "fail", "；".join(js_errors)[:300])
            )
        else:
            checks.append(_check("js_errors", "无未处理 JS 错误", "pass", "未捕获到 pageerror"))

        # 3) 外部网络拦截情况（安全性信息，不计为失败）
        checks.append(
            _check(
                "network_isolation",
                "外部网络隔离",
                "pass",
                f"已拦截 {len(blocked)} 个外部请求" if blocked else "无外部请求",
            )
        )

        # 4) 可识别的游戏区域
        area = await page.evaluate(_GAME_AREA_JS)
        if area:
            checks.append(
                _check("game_area", "可识别的游戏区域", "pass", area["desc"])
            )
        else:
            checks.append(
                _check(
                    "game_area",
                    "可识别的游戏区域",
                    "fail",
                    "未找到可见的 canvas 或游戏容器",
                )
            )

        # 5) 开始/重开等必要交互（只看元素存在，不作为功能通过的证据）
        restart_label = await page.evaluate(_FIND_RESTART_JS)
        if restart_label:
            checks.append(
                _check("restart_control", "存在开始/重开控件", "pass", restart_label)
            )
        else:
            checks.append(
                _check(
                    "restart_control",
                    "存在开始/重开控件",
                    "unverified",
                    "未找到可点击的开始/重开元素",
                )
            )

        # 6) 玩法验证：只有游戏暴露测试探针时才做确定性断言
        has_probe = await page.evaluate(
            "() => !!(window.__ogsProbe && window.__ogsProbe.version === 1)"
        )
        probe_results: dict[str, GateCheck] = {}
        if has_probe:
            probe_results = await _run_probe_checks(page)
            checks.extend(probe_results.values())
        else:
            checks.append(
                _check(
                    "gameplay",
                    "玩法行为验证",
                    "unverified",
                    "游戏未提供测试探针，无法确定性验证方向键/计分/重开",
                )
            )

        checks.append(_prd_acceptance(prd, probe_results, has_probe))

    finally:
        if browser is not None:
            await browser.close()
        await playwright.stop()


async def _run_probe_checks(page) -> dict[str, GateCheck]:
    results: dict[str, GateCheck] = {}
    probe = "() => window.__ogsProbe.state()"

    # --- 方向键真的能改变方向 ---
    try:
        before = await page.evaluate(probe)
        initial_dir = before["dir"]
        key = "ArrowUp" if initial_dir["x"] != 0 else "ArrowLeft"
        await page.keyboard.press(key)
        await page.wait_for_timeout(150)
        after = await page.evaluate(probe)
        changed = after["dir"] != initial_dir
        results["arrow_keys"] = _check(
            "arrow_keys",
            "方向键改变方向",
            "pass" if changed else "fail",
            f"{initial_dir} -> {after['dir']}（按键 {key}）",
        )
    except PlaywrightError as exc:
        results["arrow_keys"] = _check("arrow_keys", "方向键改变方向", "fail", str(exc)[:200])

    # --- 吃到食物后分数真的增加 ---
    try:
        state = await page.evaluate(probe)
        head, direction = state["head"], state["dir"]
        target = {"x": head["x"] + direction["x"], "y": head["y"] + direction["y"]}
        await page.evaluate(
            "([x, y]) => window.__ogsProbe.placeFood(x, y)", [target["x"], target["y"]]
        )
        await page.wait_for_timeout(300)
        after = await page.evaluate(probe)
        increased = after["score"] > state["score"]
        results["score_updates"] = _check(
            "score_updates",
            "得分会更新",
            "pass" if increased else "fail",
            f"score {state['score']} -> {after['score']}",
        )
    except PlaywrightError as exc:
        results["score_updates"] = _check("score_updates", "得分会更新", "fail", str(exc)[:200])

    # --- 撞墙结束后能重新开始 ---
    try:
        await page.wait_for_function(
            "() => window.__ogsProbe.state().over === true", timeout=5000
        )
        clicked = await page.evaluate(_CLICK_RESTART_JS)
        await page.wait_for_timeout(250)
        after = await page.evaluate(probe)
        ok = clicked and after["over"] is False and after["score"] == 0
        detail = (
            f"点击重开后 over={after['over']}, score={after['score']}"
            if clicked
            else "找不到可点击的重开控件"
        )
        results["restart_after_gameover"] = _check(
            "restart_after_gameover", "结束后可重新开始", "pass" if ok else "fail", detail
        )
    except PlaywrightError as exc:
        results["restart_after_gameover"] = _check(
            "restart_after_gameover", "结束后可重新开始", "fail", str(exc)[:200]
        )

    return results


def _prd_acceptance(
    prd: GamePRD, probe_results: dict[str, GateCheck], has_probe: bool
) -> GateCheck:
    """把 PRD 里能自动验证的条目映射到探针检查；不能验证的明确标记。"""
    mapping: list[tuple[str, str]] = []
    for control in prd.controls:
        if re.search(r"方向|箭头|键盘|arrow|key", control, re.I):
            mapping.append(("方向键改变方向", "arrow_keys"))
        else:
            mapping.append((f"操作：{control}", ""))
    for feature in prd.features:
        if re.search(r"计分|得分|score", feature, re.I):
            mapping.append(("得分会更新", "score_updates"))
        elif re.search(r"结束|失败|game over|重开|重新", feature, re.I):
            mapping.append(("结束后可重新开始", "restart_after_gameover"))
        else:
            mapping.append((f"功能：{feature}", ""))
    if re.search(r"撞|墙|结束|失败", prd.lose_condition):
        mapping.append(("结束后可重新开始", "restart_after_gameover"))

    unverified: list[str] = []
    failures: list[str] = []
    seen: set[str] = set()
    for label, check_id in mapping:
        if label in seen:
            continue
        seen.add(label)
        if not has_probe or not check_id:
            unverified.append(label)
        elif probe_results[check_id].status == "fail":
            failures.append(label)

    if failures:
        return _check(
            "prd_acceptance",
            "PRD 验收项",
            "fail",
            "未满足：" + "、".join(failures),
        )
    if unverified:
        return _check(
            "prd_acceptance",
            "PRD 验收项",
            "unverified",
            "无法自动验证：" + "、".join(sorted(set(unverified))),
        )
    return _check("prd_acceptance", "PRD 验收项", "pass", "全部可自动验证项通过")
