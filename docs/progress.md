# 开发进度

## 阶段 5：像素办公室与实时驾驶舱（已完成）

**日期**：2026-10-24

### 已实现

**布局（原生 HTML/CSS，无框架）**

- 顶部 CEO 控制台：需求输入 + 连接状态 + 任务状态徽章 + task_id
- 左侧 55%：Canvas 2D 像素办公室（880×520 逻辑尺寸，CSS 自适应）
- 右侧 45%：Game / Review / Marketing / Logs 四个标签页
- 底部 116px：最近事件横向条
- 细节：墙上任务牌按 `measureText` 实测宽度截断长需求，不再溢出边框；favicon 用内联 SVG，控制台无 404 噪音

**四员工状态**

- `idle / working / reviewing / fixing / completed / error` 六态，颜色与动画各不相同
- 状态完全由后端事件驱动（`agent.status_changed`），前端没有计时器伪造进度
- 工作时显示器滚动绿色代码行、角色呼吸起伏；修复时抖动；出错时冒红色感叹号
- 对话气泡只在 `working / reviewing / fixing / error` 时出现，任务完成后自动消失，不长期遮挡画面

**事件总线与 WebSocket**

- `backend/bus.py`：`EventBus.subscribe(task_id)` 返回 `asyncio.Queue(256)`，队列满时丢弃最旧事件，慢消费者不会阻塞工作流
- `WorkflowEngine` 新增 `on_event` 回调：`_emit` 先追加 `TraceEvent` → 存入 `task.json` → 再广播，保证「刷新页面后仍能还原」
- 事件契约统一为 11 种类型（`task.created / task.status_changed / agent.status_changed / artifact.created / fix.requested / review.completed / task.completed / task.failed / stage.*`）
- 旧版 `task.json` 里的历史事件名（如 `state_changed`）通过 `EventType._missing_` 兼容，不需要迁移脚本
- `WS /ws/tasks/{task_id}`：连接后立即推送 `task.snapshot`（含完整任务记录与事件），之后持续推送事件，20s 无事件发送 ping
- 前端断线重连：指数退避 1s → 8s，`localStorage` 记住 task_id，重连后用快照重建员工状态、日志与产物

**隔离预览**

- `GET /preview/{task_id}/{filename}`：只允许 `index.html` 与 `history/index.v{n}.html`
- 响应头：严格 CSP（`default-src 'none'`、`script-src 'unsafe-inline'`、`connect-src 'none'`、`frame-ancestors 'self'`）+ `nosniff` + `no-store`
- iframe `sandbox="allow-scripts"`（不含 `allow-same-origin`）：游戏运行在 opaque origin，读不到主页面 DOM、Cookie 与 localStorage
- 文件名白名单 + task_id 正则（`^[0-9a-f]{6,32}$`）双重拦截路径穿越

**版本与产物接口**

- `GET /api/tasks/{id}/artifacts/{filename}`：白名单正则校验后读取单个产物
- `GET /api/tasks/{id}/history`：列出 `history/index.v{n}.html` 快照，前端可切换查看修复前版本
- 前端切换版本时用 `?t=` 缓存击穿参数，避免 iframe 复用旧页面

### 新增 / 修改文件

| 文件                         | 说明                                                                  |
| ---------------------------- | --------------------------------------------------------------------- |
| `backend/bus.py`             | 新增：进程内事件总线                                                  |
| `backend/models/events.py`   | 重写：11 种事件类型、`AgentStatus`、`TraceEvent.as_message()`         |
| `backend/workflow/engine.py` | 修改：`_emit` / `_agent` / `_write`，所有状态变化同时落盘与广播       |
| `backend/main.py`            | 重写：WebSocket、预览、单产物、历史端点与安全响应头                   |
| `frontend/index.html`        | 重写：驾驶舱布局与四标签页                                            |
| `frontend/style.css`         | 重写：像素风变量、无圆角硬边框、阶梯阴影、响应式单列                  |
| `frontend/office.js`         | 新增：Canvas 2D 像素办公室与员工动画                                  |
| `frontend/app.js`            | 新增：WebSocket、快照恢复、产物渲染、日志                             |
| `tests/test_api.py`          | 新增 6 个用例：预览 CSP、越权文件、单产物、历史、WS 快照、WS 未知任务 |

### 测试

```
uv run pytest -q  → 58 passed in 39.77s（最终回归）
```

### 端到端验收（真实浏览器，Mock 模式）

任务 `7f717031559b` 完整时间线：

```
task.created          任务已创建
task.status_changed   pending -> planning
agent.status_changed  coo working / completed        → 生成 prd.md
task.status_changed   planning -> coding
agent.status_changed  engineer working / completed   → 生成 index.html + 门禁 10 项通过
task.status_changed   coding -> reviewing
review.completed      第 1 次审查：ITERATE（1 个问题）
task.status_changed   reviewing -> fixing
fix.requested         第 1 次修复，旧版本已存入 history/index.v1.html
agent.status_changed  engineer fixing / completed    → 修复版 + 门禁通过
review.completed      第 2 次审查：PASS（0 个问题）
task.status_changed   reviewing -> marketing
agent.status_changed  marketer working / completed   → marketing_kit.json / .md
task.status_changed   marketing -> completed
task.completed        任务完成，游戏与营销素材已就绪
```

Playwright 实测（1280×800）：

```
office canvas        684×555（CSS 自适应，逻辑 880×520）
preview canvas       404×404，title=Snake
tab 切换             game / review / marketing / logs 全部可点击且可见
overlay              preview-empty=hidden、preview-error=hidden
review 渲染          407 字符，含 PASS 与 10 项门禁表格
marketing 渲染       646 字符，含定位、Slogan、两篇文案、7 天计划
控制台错误           无（favicon 已改为内联图标）
```

### 未解决问题

1. **事件总线是进程内的**：`uvicorn --reload` 单进程可用；未来多 worker/多实例部署需要换成 Redis 或外部 broker，当前阶段不做。
2. **快照体积随事件数增长**：`task.json` 保存全量事件，长任务重连时会整包下发，暂无截断或分页。
3. **办公室画布是固定逻辑尺寸**：靠 CSS 缩放适配，极窄窗口下姓名与气泡字号偏小。
4. **Mock 模式 `duration_ms` 为 0**：耗时与 token 指标只有接入真实模型才有意义，Mock 下不具参考性。
5. **修复前版本只保留 HTML**：`history/` 只有 `index.v{n}.html` 与 `gate.v{n}.json`，没有对应轮次的 `review.json` 快照。

---

## 阶段 4：Vibe Marketing（已完成）

**日期**：2026-10-24

### 已实现

- Marketer 输出契约重构为 `MarketingKit`：
  - `positioning`：游戏名称、核心玩法、一句话卖点、目标玩家
  - `slogan`
  - `posts`：正好 2 篇（`fun` 趣味向 / `challenge` 挑战向），含标题、正文、Emoji、话题标签
  - `plan`：正好 7 天，`day` 必须是 1–7 且不重复（`model_validator` 强校验）
- 同时产出 `marketing_kit.json`（供前端）与 `marketing_kit.md`（供人读）
- 营销素材与游戏一致性：
  - 只有最终裁决 `PASS` 才进入 marketing（引擎状态机保证）
  - 输入里带上门禁「已验证功能」清单，未验证项明确标注为不可宣传
- 真实性校验 `find_fabricated_claims`：
  - 正则拦截「数字 + 用户/玩家/下载/粉丝」等编造表述
  - 命中即任务 `failed`，但已通过审查的 `index.html`、`review.json` 全部保留
- Marketer 不写游戏代码，输出契约里也没有代码字段

### 测试

```
uv run pytest -q  → 52 passed in 41.56s
```

新增 2 个工作流用例：

- `test_marketing_content_matches_game`：两篇文案、7 天计划、markdown 含 slogan 与标题
- `test_fabricated_marketing_claims_keep_game`：编造「10 万用户」被拦截，游戏产物保留

### 端到端验收（真实运行）

```
task_id : a580ffc16032
status  : completed | fix: 1
artifacts: gate.json index.html marketing_kit.json marketing_kit.md prd.md review.json

positioning keys: game_name, core_gameplay, one_liner, target_players
slogan: 摸鱼三分钟，你能让这条蛇活多久？
posts: [('fun', 上班摸鱼神器…), ('challenge', 挑战：连续吃 10 个苹果…)]
plan days: [1, 2, 3, 4, 5, 6, 7]
```

### 未解决问题

1. **编造检测是正则**：只能拦住常见口径，无法判断语义层面的夸大（如"史上最好玩"）。
2. **未验证功能只能靠提示词约束**：Marketer 若忽略清单硬写未验证能力，目前不会被确定性拦截。
3. **文案与玩法一致性未做实机校验**：用的是 PRD 标题与门禁标签，而不是解析游戏文本。

---

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
