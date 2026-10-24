# 开发进度

## 阶段 3：双层审查与自动修复（已完成）

**日期**：2026-10-23

### 已实现

**第一层：机械门禁**（`backend/gate/mechanical.py`）

| 检查项                   | 手段                     | 失败/未验证条件                         |
| ------------------------ | ------------------------ | --------------------------------------- |
| `html_structure`         | 纯 Python                | 空文件或缺少 `html/body/script`         |
| `page_load`              | Playwright `set_content` | 页面无法加载                            |
| `js_errors`              | `pageerror` 事件         | 出现未处理异常                          |
| `network_isolation`      | 路由拦截                 | 记录被拦截的外部请求（不计失败）        |
| `game_area`              | DOM 查询                 | 无可见 canvas / 游戏容器                |
| `restart_control`        | DOM 查询                 | 找不到重开控件时标记 unverified         |
| `arrow_keys`             | 探针 + 真实按键          | 方向未变化                              |
| `score_updates`          | 探针摆放食物             | 分数未增长                              |
| `restart_after_gameover` | 撞墙 → 点击重开          | 重开后 `over` 仍为真或分数未归零        |
| `prd_acceptance`         | PRD 条目映射             | 映射不到可自动验证的项时标记 unverified |
| `gameplay`               | 无探针时                 | 明确标记 unverified，不伪造通过         |

**第二层：AI Reviewer**

- 输入：PRD + 机械门禁报告 + 游戏代码。
- 输出契约改为 `verdict(PASS|ITERATE) / issues / suggestions / summary`。
- 裁决规则：
  - 门禁失败且 AI 说 PASS → 强制改为 ITERATE，`forced_by_gate=true`。
  - 门禁失败时把失败项并入 `issues`，拒绝原因完整落盘。
  - Reviewer 输出无法解析 → 任务直接 `failed`，不进入无意义的修复循环。

**自动修复**

- ITERATE 时把 issues + suggestions 交给 Engineer。
- 修复前把当前 `index.html` 快照到 `history/index.v{n}.html`。
- 每轮门禁报告留档 `history/gate.v{n}.json`。
- 修复后重新执行门禁 + 审查，最多 2 次，用尽进 `needs_attention`。

### 安全措施

| 要求                 | 实现                                                  |
| -------------------- | ----------------------------------------------------- |
| 不访问服务端文件系统 | `set_content` 注入，不传任何路径                      |
| 不接触 API Key       | 全新 context，无 storage / 无环境变量注入             |
| 独立隔离浏览器上下文 | 每次新建 context，`service_workers=block`             |
| 禁止不必要的外部网络 | 除 `data:/about:/blob:` 外全部 `route.abort()` 并记录 |
| 限制超时与资源       | 单次 8s、总 30s，`finally` 强制关闭浏览器             |
| 不执行模型 shell     | 全项目无 shell 入口，模型输出只作 JSON 解析           |

### 测试

```
uv run pytest -q   → 50 passed in 40.06s
```

新增 9 个门禁用例（真实 Chromium）+ 2 个工作流用例：

- 贪吃蛇全部探针通过
- 人为破坏重开 → `restart_after_gameover` 失败
- JS 抛错被捕获
- 外部脚本被拦截
- 无画布判失败
- 无探针时玩法标记 unverified
- AI 强行 PASS 但门禁失败 → `needs_attention`，`review.json` 为 ITERATE
- Reviewer 输出不可解析 → 任务 failed

### 实际运行验证

**A. 注入重开缺陷 → 被拦截 → 修复 → 交付**

```
status: completed | fix_attempts: 1
首轮门禁 passed: False | 失败项: ['restart_after_gameover', 'prd_acceptance']
  - 结束后可重新开始: 点击重开后 over=True, score=1
  - PRD 验收项: 未满足：结束后可重新开始
产物: prd.md index.html gate.json review.json marketing_kit.md
      history/index.v1.html history/gate.v1.json history/gate.v2.json
```

**B. AI 持续说 PASS，但门禁持续失败**

```
status: needs_attention | fix_attempts: 2
首轮门禁 passed: False | 失败项: ['game_area']
```

此时 `review.json`：

```json
{
  "verdict": "ITERATE",
  "issues": [
    {
      "severity": "high",
      "description": "机械门禁未通过：可识别的游戏区域（未找到可见的 canvas 或游戏容器）",
      "suggestion": "修复后必须重新通过机械门禁与 AI 审查"
    }
  ],
  "suggestions": [],
  "summary": "机械门禁未通过，禁止判定 PASS。可交付",
  "forced_by_gate": true
}
```

### 未解决问题

1. **Playwright 自带 Chromium 下载失败**：本机网络无法访问下载源。已实现回退到系统 Chrome（`channel="chrome"`），并支持 `OGS_BROWSER_PATH`。部署到新机器时需确认浏览器可用。
2. **玩法探针是可选协议**：只有暴露 `window.__ogsProbe` 的游戏能做确定性玩法断言；真实模型生成的游戏多数没有，此时只能标记 unverified。后续可考虑用图像差异等弱信号改进。
3. **门禁总耗时约 2-3 秒/轮**：当前每次检查都新建浏览器，尚未复用。
4. **PRD 映射是关键词匹配**：`方向键`、`计分`、`结束` 之外的验收项都会落到 unverified。

---

## 阶段 2：四 Agent 工作流（已完成）
