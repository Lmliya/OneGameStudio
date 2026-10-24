# OneGameStudio 架构说明

> 版本：v0.7（阶段 6：Mini-6 Harness）
> 本文只描述已实现的部分，未实现的内容标注为"规划中"。
> 跨对话交接、未完成模块与当前问题见 [HANDOFF.md](HANDOFF.md)。

## 1. 项目定位

用户输入一句自然语言游戏需求，四个 AI 员工协作产出可运行的 HTML5 游戏、审查报告与营销文案：

| 员工     | Talent id  | 输出契约                     |
| -------- | ---------- | ---------------------------- |
| COO      | `coo`      | `prd` → `GamePRD`            |
| Engineer | `engineer` | `game` → `GameArtifact`      |
| Reviewer | `reviewer` | `review` → `ReviewReport`    |
| Marketer | `marketer` | `marketing` → `MarketingKit` |

## 2. 核心公式

```
Employee = Talent + Vessel
Task     = WorkflowEngine + TaskStore
Review   = Mechanical Gate + AI Reviewer
Realtime = EventBus + WebSocket
```

## 3. 分层结构

```
frontend/
    index.html       驾驶舱骨架（顶部控制台 / 左办公室 / 右标签 / 底部日志）
    style.css        像素风样式
    office.js        Canvas 2D 像素办公室（事件驱动的员工动画）
    app.js           WebSocket、快照恢复、产物渲染、日志
backend/
    main.py          FastAPI：API + WebSocket + 隔离预览 + 静态页面
    bus.py           进程内事件总线
    config.py        全局配置（LLM_*）
    schemas.py       输出契约 + 门禁报告
    talents.py       Talent 加载与工具白名单校验
    store.py         任务持久化与版本快照
    models/          TaskRecord / TalentSpec / TraceEvent
    core/vessel.py   员工执行容器
    providers/       base / mock / openai
    gate/            机械门禁（Playwright）
    workflow/        状态机与编排引擎
talents/             四个员工的 YAML
tests/               pytest
docs/                架构与进度
output/{task_id}/    任务产物（不入库）
```

## 4. 状态机

```
pending → planning → coding → reviewing → (fixing → reviewing)* → marketing → completed
                                  ↓                                  ↓
                            needs_attention                      failed
```

`coding` 之后、`reviewing` 之前会插入机械门禁，但门禁不是独立状态——它是 `reviewing` 的输入。

| 当前状态    | 允许迁移                                           |
| ----------- | -------------------------------------------------- |
| `pending`   | `planning`, `failed`                               |
| `planning`  | `coding`, `failed`                                 |
| `coding`    | `reviewing`, `failed`                              |
| `reviewing` | `fixing`, `marketing`, `needs_attention`, `failed` |
| `fixing`    | `reviewing`, `needs_attention`, `failed`           |
| `marketing` | `completed`, `failed`                              |
| 终态        | 不可迁移                                           |

## 5. 双审查流程

```
Engineer 产出 HTML
   ↓ 落盘 index.html
Mechanical Gate（真实 Chromium）
   ├─ html_structure / page_load / js_errors
   ├─ game_area / restart_control
   ├─ arrow_keys / score_updates / restart_after_gameover
   └─ prd_acceptance
   ↓ 落盘 gate.json（并留档 history/gate.v{n}.json）
AI Reviewer（读 PRD + 门禁报告 + 代码）
   ↓ 落盘 review.json
裁决：
   门禁 fail 且 AI 说 PASS  → 强制 ITERATE，forced_by_gate=true
   门禁 fail 且 AI 说 ITERATE → ITERATE
   门禁 pass                 → 以 AI verdict 为准
```

### 5.1 机械门禁的判定原则

- 只做确定性断言：真实加载、真实按键、真实点击、真实状态读取。
- 不把"文件里有 canvas 标签"当成游戏能玩。
- 无法可靠验证的玩法统一标记 `unverified`，绝不写成 `pass`。
- `passed` 的计算方式：没有任何 `fail`。`unverified` 不影响交付，但会进入 AI 审查视野。

### 5.2 玩法探针协议（可选）

生成游戏可以暴露：

```js
window.__ogsProbe = {
  version: 1,
  state: () => ({ dir, score, over, head, length }),
  placeFood: (x, y) => {},
};
```

有探针时门禁做确定性玩法断言；没有探针时，方向键/计分/重开一律 `unverified`。

### 5.3 AI 审查失败策略

| 情况                  | 处理                                   |
| --------------------- | -------------------------------------- |
| 输出不是合法 JSON     | 任务 `failed`，原因写入 `error` 与事件 |
| JSON 合法但不符合契约 | 任务 `failed`                          |
| 判定 PASS 但门禁失败  | 强制 ITERATE                           |
| 判定 ITERATE          | 进入修复循环                           |

### 5.4 门禁检查项与判定

| 检查项                   | 手段          | fail                          | unverified           |
| ------------------------ | ------------- | ----------------------------- | -------------------- |
| `html_structure`         | 纯 Python     | 空文件或缺 `html/body/script` | —                    |
| `page_load`              | `set_content` | 加载异常                      | —                    |
| `js_errors`              | `pageerror`   | 有未捕获异常                  | —                    |
| `network_isolation`      | `route.abort` | —                             | —（只记录）          |
| `game_area`              | DOM 查询      | 无可见 canvas/容器            | —                    |
| `restart_control`        | DOM 查询      | —                             | 找不到重开元素       |
| `arrow_keys`             | 探针 + 按键   | 方向未变                      | 无探针               |
| `score_updates`          | 探针摆食物    | 分数未增                      | 无探针               |
| `restart_after_gameover` | 撞墙 + 点击   | 未恢复                        | 无探针               |
| `prd_acceptance`         | PRD 映射      | 已映射项失败                  | 有无法自动验证的条目 |
| `gameplay`               | 无探针时      | —                             | 始终 unverified      |

`MechanicalReport.passed = 所有检查均不为 fail`。

## 6. 自动修复

```
ITERATE
  ↓ 快照当前 index.html -> history/index.v{n}.html
  ↓ issues + suggestions 交给 Engineer
  ↓ 重新执行机械门禁（报告留档 history/gate.v{n}.json）
  ↓ 重新执行 AI 审查
最多 2 次，仍不通过 -> needs_attention
```

Reviewer 只写 `review.json`，Marketer 只写 `marketing_kit.*`，两者都不改 `index.html`。

## 6.5 营销阶段

进入条件：最终裁决为 `PASS`。状态机不允许从 `reviewing` 直接跳到 `marketing`，必须满足裁决。

输入：PRD、游戏文件名、审查结论、机械门禁的「已验证功能」清单。

输出：

| 文件                 | 用途                                            |
| -------------------- | ----------------------------------------------- |
| `marketing_kit.json` | 前端结构化渲染                                  |
| `marketing_kit.md`   | 人读版（定位 / Slogan / 两篇文案 / 7 天计划表） |

真实性约束：

- 只把门禁 `pass` 的功能映射为可宣传项（`_VERIFIED_LABELS`），未验证项在提示词中明确禁止宣传。
- `find_fabricated_claims` 用正则拦截「数字 + 用户/玩家/下载/粉丝」等编造表述，命中即 `failed`。
- 营销失败只影响营销产物，`index.html` 与 `review.json` 保留。
- 全流程没有发布接口，不向任何第三方平台推送。

## 7. 产物

`output/{task_id}/`：

| 文件                      | 产出者   | 内容                   |
| ------------------------- | -------- | ---------------------- |
| `prd.md`                  | COO      | 结构化 PRD             |
| `index.html`              | Engineer | 单文件游戏（当前版本） |
| `gate.json`               | 门禁     | 最新一轮机械检查报告   |
| `review.json`             | Reviewer | 最终裁决与问题清单     |
| `marketing_kit.json`      | Marketer | 结构化营销素材（前端） |
| `marketing_kit.md`        | Marketer | 人读版营销素材         |
| `task.json`               | 引擎     | 状态、事件、产物索引   |
| `history/index.v{n}.html` | 引擎     | 修复前版本快照         |
| `history/gate.v{n}.json`  | 引擎     | 每轮门禁报告           |

写入策略：只新增不删除。任一阶段失败，已产出文件全部保留。

## 7.5 实时驾驶舱

### 7.5.1 前端结构

| 区域          | 内容                                                |
| ------------- | --------------------------------------------------- |
| 顶部（64px）  | 需求输入、WebSocket 连接徽章、任务状态徽章、task_id |
| 左侧（55%）   | Canvas 2D 像素办公室：四张桌子 + 四名员工 + 任务牌  |
| 右侧（45%）   | Game / Review / Marketing / Logs 四个标签页         |
| 底部（116px） | 最近事件条（同内容在 Logs 页保留全量）              |

员工状态只有 `idle / working / reviewing / fixing / completed / error`，**全部由后端事件驱动**。前端没有任何计时器或随机数伪造进度；刷新页面后用快照回放事件，画面立即恢复。

- `activeAgent` 保证同一时刻最多只有一名员工播放动画，`idle/completed` 完全静止。
- 员工动作需要真实时长支撑，因此节奏由后端 `STAGE_MIN_SECONDS`（默认 6 秒）控制：`WorkflowEngine._call` 在模型返回后补足等待，测试引擎默认 0，套件不受影响。
- 人物为背对观众坐姿（后脑勺 + 耳机），桌子在后、椅子在前，姓名与状态标签位于椅子下方。
- 画布以 `object-fit: contain` 保持 880×520 比例，避免 CSS 拉伸。

### 7.5.2 事件契约

`TraceEvent` 是唯一事件模型，写入 `task.json` 与推送 WebSocket 使用同一份数据：

| 字段      | 说明                                               |
| --------- | -------------------------------------------------- |
| `type`    | 11 种事件类型之一                                  |
| `task_id` | 任务标识                                           |
| `agent`   | 相关员工（`coo/engineer/reviewer/marketer`），可选 |
| `status`  | 员工状态或任务状态，可选                           |
| `stage`   | 当前阶段，便于日志过滤                             |
| `message` | 人读文案（顶部与日志直接展示）                     |
| `data`    | 结构化附加信息（失败项、裁决、产物列表等）         |
| `ts`      | ISO 时间戳                                         |

旧版本 `task.json` 中的历史事件名（`state_changed` 等）由 `EventType._missing_` 映射到新枚举，读取无需迁移。

### 7.5.3 WebSocket 协议

```
客户端  ──连接──▶  /ws/tasks/{task_id}
服务端  ──立即──▶  {"type":"task.snapshot","task": {...完整 TaskRecord...}}
服务端  ──持续──▶  {"type":"<event>", "task_id","agent","status","stage","message","ts","data"}
服务端  ──空闲 20s──▶ {"type":"ping"}
```

- 快照消息里带完整 `events` 数组，前端据此重建员工状态、日志与产物列表。
- 断线由前端指数退避重连（1s → 8s），`localStorage` 保存最近 task_id。
- `EventBus` 每任务一个 `asyncio.Queue(256)`，队列满时丢弃最旧事件：慢消费者不会阻塞工作流，也不会让事件无限堆积。
- 该总线是**进程内**的；多 worker 部署需要替换为外部 broker（当前阶段不做）。

### 7.5.4 预览隔离

`GET /preview/{task_id}/{filename}` 只服务两种文件：`index.html` 与 `history/index.v{n}.html`。

| 防护       | 实现                                                                                                     |
| ---------- | -------------------------------------------------------------------------------------------------------- |
| 路径穿越   | `task_id` 匹配 `^[0-9a-f]{6,32}$`，文件名匹配固定白名单正则                                              |
| 页面联网   | CSP `default-src 'none'; connect-src 'none'`                                                             |
| 读本站数据 | CSP `frame-ancestors 'self'` + iframe `sandbox="allow-scripts"`（无 `allow-same-origin`，opaque origin） |
| 缓存残留   | `Cache-Control: no-store` + 前端 `?t=` 参数                                                              |
| MIME 嗅探  | `X-Content-Type-Options: nosniff`                                                                        |

生成游戏因此在「能运行」与「无法访问主页面上下文」之间取得平衡：脚本可执行，但拿不到 Cookie、localStorage 与父页面 DOM。

## 8. API

| 方法 | 路径                                    | 行为                                    |
| ---- | --------------------------------------- | --------------------------------------- |
| GET  | `/api/health`                           | 返回运行模式                            |
| POST | `/api/tasks`                            | 202，后台执行；同需求运行中任务返回 409 |
| POST | `/api/tasks/{task_id}/cancel`           | 202，取消任务；终态任务返回 409         |
| GET  | `/api/tasks/{task_id}`                  | 任务状态与事件                          |
| GET  | `/api/tasks/{task_id}/artifacts`        | 产物文件名到内容的映射                  |
| GET  | `/api/tasks/{task_id}/artifacts/{file}` | 单个产物（白名单校验）                  |
| GET  | `/api/tasks/{task_id}/history`          | 修复前版本快照列表                      |
| GET  | `/preview/{task_id}/{file}`             | 隔离预览（CSP + nosniff + no-store）    |
| WS   | `/ws/tasks/{task_id}`                   | 首帧快照 + 实时事件流                   |

未知 task_id 的 WebSocket 连接会被直接关闭。

## 9. 安全边界

机械门禁部分：

- 通过 `page.set_content()` 注入 HTML，不授予任何服务端文件路径。
- 每次全新 context：无 cookie、无 localStorage、无权限、无 API Key。
- 除 `data:` / `about:` / `blob:` 外所有请求 `abort()` 并记录。
- 单次加载 8s、总流程 30s 超时，`finally` 关闭浏览器。
- 浏览器进程与应用进程隔离；生成代码不在 Python 进程内执行。

其他：

- `allowed_tools` 加载时与白名单求差集。
- 全项目无 shell 执行入口。
- API Key 只从服务端环境变量读取。

浏览器内预览部分（见 7.5.4）：

- 只服务 `index.html` 与 `history/index.v{n}.html`，其余一律 404。
- `task_id` 正则 + 文件名白名单，双重拦截路径穿越。
- CSP 禁止联网与取本站资源（`connect-src 'none'`），`frame-ancestors 'self'` 防被外部站点嵌入。
- iframe `sandbox="allow-scripts"` 且不含 `allow-same-origin`，游戏处于 opaque origin。

## 10. Mini-6 落位情况

阶段 6 已把六项机制整合为统一 Harness，详见 [harness.md](harness.md)。

| 能力          | 实现位置                                                                    |
| ------------- | --------------------------------------------------------------------------- |
| Task Contract | `models/contract.py` + `workflow/state_machine.py`（10 态，含 cancelled）   |
| Tool Policy   | `tools.py` 注册表 + `talents.py` 加载期校验 + `engine._use_tool` 运行时校验 |
| Quality Gate  | `gate/mechanical.py` + `engine._review`（后端强制裁决）                     |
| Recovery      | `core/vessel.py`（重试/超时）+ `engine.cancel` + `main.py` 取消端点         |
| Budget Guard  | `budget.py`（单任务预算、70% 降级、阻断、价格可配置、限并发）               |
| Event Trace   | `models/events.py` 统一字段 + `engine._emit` 落盘 + `bus.py` + WS           |

## 11. 运行依赖

- Python 3.12+ / uv / FastAPI / Pydantic / PyYAML / pytest
- Playwright（运行时）：优先自带 Chromium，失败时回退系统 Chrome
- 前端原生 HTML/CSS/JS，无 React/Vue/构建工具
- 不使用 LangChain/LangGraph、Redis、PostgreSQL、Docker
