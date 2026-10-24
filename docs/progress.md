# 开发进度

## 交接状态（2026-10-24）

- 分支 `main`，最新提交 `ec70e94 补充跨对话交接文档并同步阶段6状态说明`；阶段 8 改动尚未提交。
- 未提交修改：`backend/`（config、vessel、main、contract、talent、engine）、`frontend/`（index、style、app、talent.js）、`talents/*.yaml`、`tests/test_evolution.py`、`backend/evolution/`、文档。
- 测试：`uv run pytest -q` → **97 passed**。
- 交接文档：[HANDOFF.md](HANDOFF.md)（含架构、API、存储、问题与下一阶段入口）。
- 阶段 8 说明：[talent-evolution.md](talent-evolution.md)。

---

## 阶段 8：AI 员工自进化（已完成）

**日期**：2026-10-24

目标：打通「任务反馈 → 经验 → 提案 → 新旧评估 → 用户批准 → 启用 → 回滚」闭环，同时保证历史不可覆盖、安全边界不可触碰。

### 已实现

- **Talent 版本库**：首次启动从 `talents/*.yaml` 播种 `v1`（幂等）；版本文件写入后只读，`active.json` 指针决定启用版本；启用时与基线逐字段比对工具白名单、输出契约与模型。
- **经验库**：`candidate / verified / rejected` 三态；`verified` 必须有可追溯证据；任务产物提取（门禁 fail → verified，审查问题 → candidate）；固定回归诊断的漏检项自动生成 verified 经验。
- **进化提案**：只接受同员工的 `verified` 经验，且经验不能被其他未拒绝提案占用；只允许修改 `prompt` / `checklist`，受保护字段在模型层直接拒绝。
- **规则型提案**：`prompt` 保持基线不变，只追加 `checklist`，控制 token 增长并保证来源可追溯。
- **固定回归评估**：Reviewer 5 条（含正常游戏）、COO 4 条、Engineer 4 条、Marketer 4 条；每条员工另有正常样例检查误报。
- **验收条件写死**：检出率 ≥ 0.9、不低于基线、误报率 ≤ 0.1、Token ≤ 2.0 倍基线；全部通过才允许批准。
- **审批与回滚**：未评估或评估失败时批准返回 409；批准先落盘审批状态再启用，失败回滚审批；任意非候选版本可回滚，审计写入 `active.json`。
- **运行时接入**：`Vessel` 使用启用版本的 prompt/checklist，返回 `talent_version`；`WorkflowEngine` 写入 `TaskRecord.talent_versions`，事件中带版本标签。
- **前端 Talent 面板**：第 5 个标签，展示版本、经验、提案、评估指标与验收条目，支持诊断、生成提案、提取经验、验证/拒绝经验、评估、批准、回滚。

### 新增 / 修改文件

```
新建  backend/evolution/models.py       领域模型与安全边界
新建  backend/evolution/store.py        JSON 版本库与原子写
新建  backend/evolution/regression.py   固定回归用例与评估
新建  backend/evolution/service.py      闭环编排
新建  backend/evolution/extract.py      任务产物经验提取
新建  backend/evolution/api.py          17 个自进化端点
新建  backend/evolution/errors.py       异常类型
新建  backend/evolution/__init__.py     导出
新建  frontend/talent.js                Talent 面板
新建  tests/test_evolution.py           19 个用例
新建  docs/talent-evolution.md          闭环、字段、边界与限制

修改  backend/models/talent.py          checklist / version 字段
修改  backend/core/vessel.py            启用版本读取、checklist 注入、版本标签
修改  backend/models/contract.py        talent_versions 快照
修改  backend/workflow/engine.py        记录实际 Talent 版本
修改  backend/config.py                 EVOLUTION_DIR
修改  backend/main.py                   装配 EvolutionStore/Service，v0.8.0
修改  talents/*.yaml                    四份初始 checklist
修改  frontend/index.html/style.css     Talent 标签与样式
修改  frontend/app.js                   Talent 面板初始化
```

### 测试

```
uv run pytest -q  → 97 passed in 51.37s（阶段 6 为 78，新增 19）
```

新增覆盖：种子幂等、verified 必须有证据、受保护字段拒绝、未批准不能启用、诊断生成 verified 经验且幂等、仅 verified 可进提案、手工验证、评估 passed + `engine=mock` + notes 标注模拟、批准启用与回滚审计、拒绝提案、篡改工具白名单被拒、live 引擎显式不可用、工作流记录 `reviewer@v2` / `coo@v1`、任务经验提取 verified/candidate 区分、API 全链路、非终态任务提取返回 409、拒绝经验。

### 端到端验收（真实 HTTP，Mock 模式）

服务：`EVOLUTION_DIR=/tmp/ogs_evo_demo uv run uvicorn backend.main:app --port 8123`

| 步骤           | 结果                                                                           |
| -------------- | ------------------------------------------------------------------------------ |
| 基线           | `reviewer@v1`，checklist 3 条                                                  |
| 诊断           | `engine=mock`，base 检出率 0.0，生成 4 条 verified 经验                        |
| 提案           | `proposal_2df991c13c`，v1 → v2，`proposed_changes` 仅含 `prompt` / `checklist` |
| 未评估直接批准 | HTTP 409 `{"detail":"提案评估未通过，不能批准"}`                               |
| 评估           | `passed=true`，检出率 0.0 → 1.0，误报 0.0 → 0.0，notes 明确标注模拟            |
| 批准           | active `reviewer@v2`，审计 `activate 1 -> 2`                                   |
| 回滚           | active `reviewer@v1`，审计 `rollback 阶段8演示回滚`                            |
| 收尾           | versions `[(2,inactive),(1,active)]`、lessons 4、proposals 1                   |

### 未解决问题

1. `live` 评估引擎未接入，真实模型下的进化效果未验证；`MOCK_MODE=false` 时服务层明确报错。
2. Mock 评估基于「清单是否覆盖验证点」的关键词判定，不代表模型真实执行能力。
3. 提案生成是规则型，不支持自动改写提示词；提示词级改写需要真实的对比评估。
4. 没有独立 Project/Run 实体，经验来源用 `task_id` 近似。
5. Talent 面板尚未做浏览器点击级自动化测试，仅通过 `node --check` 与 HTTP 接口验证。
6. `active.json` 审计为追加数组，没有归档策略。

---

## 阶段 6：Mini-6 Harness（已完成）

**日期**：2026-10-24

目标是把散落的运行保障机制整合成统一 Harness，不重构工作流业务逻辑。详细机制与边界见 [harness.md](harness.md)。

### 审计结论

| Harness       | 阶段 6 之前                                   | 本阶段补齐                                                                       |
| ------------- | --------------------------------------------- | -------------------------------------------------------------------------------- |
| Task Contract | Pydantic + 9 态状态机已有                     | 新增 `cancelled` 终态、全部非终态到 cancelled 的迁移、预算快照字段、错误类型归档 |
| Tool Policy   | 只有占位白名单 `read_contract/write_artifact` | 新建显式注册表、按角色校验、运行时拦截、YAML 改为真实工具名                      |
| Quality Gate  | 阶段 3 已完整                                 | 文档化裁决边界，未改业务逻辑                                                     |
| Recovery      | 2 次修复、超时、错误落盘、并发保护已有        | 新增 provider 有限重试、任务取消、终态不可再执行                                 |
| Budget Guard  | Vessel 实例级累计、费用恒 0                   | 单任务预算、70% 降级、100% 阻断、可配置价格、未知用量标记、限并发                |
| Event Trace   | 11 类事件，字段塞在 `data`                    | 统一顶层 `model/duration_ms/token_usage/result/error`，新增 3 类事件             |

### 已实现

- **Harness 1**：`TaskStatus.CANCELLED`；`ALLOWED_TRANSITIONS` 覆盖取消；`TaskRecord.budget`、`cancel_requested_at`；终态任务 `TaskNotRunnableError`。
- **Harness 2**：`backend/tools.py` 注册 9 个工具与 `ROLE_TOOLS`；加载期（`talents.py`）与运行时（`engine::_use_tool`）双重校验；不注册任何 shell/subprocess 能力；每次调用写 `tool.called`。
- **Harness 3**：沿用阶段 3 双层审查；门禁 fail 强制 ITERATE、Reviewer 输出不可解析即终止。
- **Harness 4**：Vessel 有限重试（异常重试、超时不重试、指数退避）；`POST /api/tasks/{id}/cancel`；取消在安全点退出且保留全部产物；同一任务并发与终态重跑均被拒绝。
- **Harness 5**：`backend/budget.py`（`BudgetGuard`）；`MODEL_PRICES` 价格表、`LIGHT_MODEL`、`BUDGET_SOFT_RATIO`、`MAX_OUTPUT_TOKENS`、`MAX_CONCURRENT_CALLS`；provider 支持 `max_tokens` 与 `usage_source`；费用 `estimated` / `unknown` 双状态，绝不把未知写成 0。
- **Harness 6**：`TraceEvent` 统一字段并贯穿 Vessel、引擎、落盘与 WebSocket；新增 `tool.called`、`budget.updated`、`task.cancelled`。

### 新增 / 修改文件

```
新建  backend/tools.py            工具注册表与权限校验
新建  backend/budget.py           单任务预算守卫
新建  tests/test_harness.py       14 个运行保障测试
新建  docs/harness.md             六项机制说明与边界

修改  backend/models/contract.py      cancelled 状态、预算快照、取消时间
修改  backend/models/events.py        统一 TraceEvent 字段、TokenUsage
修改  backend/workflow/state_machine.py  取消迁移
修改  backend/workflow/engine.py      工具校验、取消、预算事件、统一追踪
修改  backend/core/vessel.py          重试、限并发、预算接入、输出上限
修改  backend/providers/*             max_tokens、usage_source、不硬编码模型名
修改  backend/config.py               预算/重试/并发配置
修改  backend/talents.py              按角色校验工具
修改  backend/main.py                 装配 BudgetGuard、取消端点 v0.7.0
修改  backend/store.py                沿用 TERMINAL_STATUSES 判断活跃任务
修改  talents/*.yaml                  真实工具名
修改  frontend/app.js                 cancelled 状态与事件
修改  tests/test_workflow.py          provider 签名适配
修改  tests/test_vessel.py            provider 签名适配
修改  tests/test_talents.py           角色工具一致性 + 越权用例
修改  tests/test_api.py               取消端点、快照字段用例
修改  README.md / .env.example        新配置项
```

### 测试

`uv run pytest -q` → **78 passed**（阶段 5 为 59，新增 19）。

新增覆盖：工具注册表与角色一致、shell 工具被拒、运行时工具事件、provider 重试成功、运行中取消保留产物、终态取消/重跑被拒、70% 降级选模型、预算耗尽阻断、未知费用标记、统一追踪字段、失败保留日志产物、取消 API 与 WS 快照。

### 端到端验收（Mock 模式，真实运行）

| 场景                             | 结果                                                                                                                                          |
| -------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------- |
| 贪吃蛇完整流程（`c5e97426164a`） | `completed`，`fix_attempts=1`，审查 `ITERATE → PASS`，6 个产物，61 条事件；四名员工工具集合与授权表完全一致                                   |
| 70% 降级（`9eba54b444d0`）       | 预算 $0.005，前 4 次 `mock`，后 2 次 `mock-light`，`downgraded_calls=2`，任务完成                                                             |
| 预算耗尽（`0bacc3f6de11`）       | 预算 $0.0005，第 3 次调用被拒，`blocked_calls=1`，`failed`，错误写明「估算 $0.0011 / 预算 $0.0005」；`prd.md`、`index.html`、`gate.json` 保留 |
| 无价格表（`acf52a57ccfd`）       | 6 次调用，`spent_usd=0`、`unknown_cost_calls=6`、`cost_status="unknown"`，未伪造费用                                                          |
| WebSocket                        | 首帧 `task.snapshot` 含 `budget` / `cancel_requested_at`；增量包含 `tool.called`、`budget.updated`、`review.completed`、`fix.requested`       |

### 未解决问题

1. 预算与 EventBus 都是进程内状态：重启清零，多 worker 各算各的。
2. 取消是协作式的，不会中断在途 HTTP 请求，最长等待一个超时或阶段展示时长。
3. 费用是「配置单价 × 估算 token」，不是账单；没有供应商对账。
4. 调用前无法预知输入 token，最后一次调用可能让花费有限超额（实测最多一次调用）。
5. 事件日志无上限，长任务需要归档/截断策略。
6. 机械门禁的玩法断言仍依赖游戏暴露 `window.__ogsProbe`。

---

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

### 补充调整（按用户反馈）

**动画节奏（后端控制，前端不做假动画）**

- 新增配置 `STAGE_MIN_SECONDS`（默认 6），`WorkflowEngine._call` 在模型返回后补足等待，保证每个员工的 `working/reviewing/fixing` 状态真实持续 ≥6 秒
- 实测：COO 6.0s、Reviewer 6.0s、Marketer 6.0s；Engineer 因跨机械门禁为 9.0–10.5s
- 完整播放顺序仍是 `COO → Engineer → Reviewer → Engineer(修复) → Reviewer → Marketer`
- 测试引擎默认 `stage_min_seconds=0`，套件不会被 6 秒等待拖慢

**动画独占**

- `office.js` 增加 `activeAgent`，同一时刻最多只有一个员工是动画焦点
- 只有焦点员工有呼吸、敲键盘、屏幕背光与台灯光晕；`idle/completed` 完全静止
- 画布分区域帧差实测：每一段只有对应员工区域发生变化

**人物与办公室**

- 人物改为坐在办公桌前、背对观众：只有后脑勺与耳机，不画五官；椅子在人物前方、桌子在后方，姓名与状态标签移到椅子下方
- 新增装饰：地毯、睡猫、书架、饮水机、落地灯、挂钟、海报、置物架、白板便签、桌面台灯/文件/咖啡杯、两盆落地植物、垃圾桶、显示器散热孔与背光
- 修复画布被 CSS 纵向拉伸的问题：`object-fit: contain`，保持 880×520 比例

### 测试

```
uv run pytest -q  → 59 passed in 40.10s（最终回归）
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
