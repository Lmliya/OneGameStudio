# Mini-6 Harness

运行保障层：管住「谁可以做、做到什么程度、失败怎么办、花多少钱、留下什么痕迹」。
它不改变业务产物，只约束流程。所有机制都在后端实现，模型无法绕过。

```
COO → Engineer → 机械门禁 → Reviewer →（修复循环）→ Marketer
         ↑          ↑            ↑          ↑
      Tool Policy  Quality Gate  Recovery   Budget Guard
         └──────── Event Trace / Task Contract ────────┘
```

---

## Harness 1：Task Contract

**实现位置**：`backend/models/contract.py`、`backend/models/talent.py`、`backend/schemas.py`、`backend/workflow/state_machine.py`

- 所有输入输出都是 Pydantic 模型：`TaskCreateRequest`、`TaskRecord`、`TalentSpec`、`GamePRD`、`GameArtifact`、`ReviewReport`、`MarketingKit`、`MechanicalReport`。
- 员工输出在 `Vessel._validate()` 里按 `output_schema` 强校验，字段缺失或类型错误直接失败，不会进入下一步。
- 状态只允许走 `ALLOWED_TRANSITIONS`：

| 状态                                                     | 可迁移到                                                        |
| -------------------------------------------------------- | --------------------------------------------------------------- |
| `pending`                                                | `planning`、`failed`、`cancelled`                               |
| `planning`                                               | `coding`、`failed`、`cancelled`                                 |
| `coding`                                                 | `reviewing`、`failed`、`cancelled`                              |
| `reviewing`                                              | `fixing`、`marketing`、`needs_attention`、`failed`、`cancelled` |
| `fixing`                                                 | `reviewing`、`needs_attention`、`failed`、`cancelled`           |
| `marketing`                                              | `completed`、`failed`、`cancelled`                              |
| `completed` / `failed` / `needs_attention` / `cancelled` | 无（终态）                                                      |

- 终态任务不能再执行也不能再取消（`TaskNotRunnableError`）；非法迁移抛 `InvalidTransitionError`。
- 错误类型分三层：

| 层                     | 类型                      | 含义                     |
| ---------------------- | ------------------------- | ------------------------ |
| 模型层 `VesselError`   | `TalentNotFoundError`     | Talent 缺失或配置非法    |
|                        | `ProviderTimeoutError`    | 调用超时（不重试）       |
|                        | `ProviderCallError`       | 重试用尽仍失败           |
|                        | `OutputParseError`        | 输出不是 JSON            |
|                        | `OutputValidationError`   | JSON 不符合契约          |
|                        | `BudgetExceededError`     | 预算达到上限，拒绝新调用 |
| 编排层 `WorkflowError` | `TaskAlreadyRunningError` | 同任务并发启动           |
|                        | `TaskNotRunnableError`    | 终态任务被再次执行/取消  |
|                        | `TaskCancelledError`      | 内部取消信号             |
|                        | `StageExecutionError`     | 阶段确定性检查失败       |
| 配置/权限层            | `TalentConfigError`       | YAML 工具或 schema 非法  |
|                        | `ToolPolicyError`         | 越权或未注册工具         |
|                        | `BudgetConfigError`       | `MODEL_PRICES` 非法      |

**边界**：契约只保证结构与状态合法，不保证语义质量；语义由机械门禁与 AI Reviewer 负责。

---

## Harness 2：Tool Policy

**实现位置**：`backend/tools.py`（注册表）、`backend/talents.py`（加载期校验）、`backend/workflow/engine.py::_use_tool`（运行时校验）

| 员工     | 授权工具                                     |
| -------- | -------------------------------------------- |
| COO      | `read_requirement`、`write_prd`              |
| Engineer | `read_prd`、`write_game`、`read_review`      |
| Reviewer | `read_game`、`run_tests`、`write_review`     |
| Marketer | `read_prd`、`read_review`、`write_marketing` |

- 两道校验：加载 YAML 时要求 `allowed_tools ⊆ ROLE_TOOLS[员工]` 且全部已注册；每次实际读写前再调 `ToolRegistry.require(agent, tool)`。
- 每次工具调用写入 `tool.called` 事件（落盘 + 推送），因此权限使用可审计。
- 注册表构造时拒绝 `shell*`、`exec*`、`subprocess*`、`system*`、`eval*` 等名称；系统根本没有执行任意命令的能力，模型输出只被当作 JSON 解析，不会被当成命令。
- 越权直接抛 `ToolPolicyError`，由引擎统一转成 `failed`，不会继续跑后续阶段。

**边界**：策略只覆盖「模型可触及的动作」。门禁执行、文件落盘本身是后端代码，不是模型工具。

---

## Harness 3：Quality Gate

**实现位置**：`backend/gate/mechanical.py`、`backend/workflow/engine.py::_review`

- 第一层机械门禁：真实 Chromium 打开隔离预览，执行 10 项确定性检查（页面加载、游戏区域、方向键、计分、结束提示、重开、PRD 验收等），结果只有 `pass` / `fail` / `unverified`。
- 第二层 AI Reviewer：读 PRD、代码、门禁报告，输出 `PASS` / `ITERATE` 与问题列表。
- 最终裁决由后端规则控制：
  1. 门禁 `fail` → 无论 AI 说什么，强制 `ITERATE` 并置 `forced_by_gate=True`；
  2. 门禁通过 → 以 AI `verdict` 为准；
  3. Reviewer 输出无法解析 → `StageExecutionError`，任务失败，不进入无效修复循环；
  4. 修复后必须重新跑门禁与审查。
- 每轮报告快照：`history/gate.v{n}.json`；每轮代码快照：`history/index.v{n}.html`。

**边界**：玩法断言依赖游戏暴露 `window.__ogsProbe`；未暴露时门禁只能标 `unverified`，不假装通过。Playwright 依赖本机 Chrome/Chromium。

---

## Harness 4：Recovery

**实现位置**：`backend/core/vessel.py`、`backend/workflow/engine.py`、`backend/main.py`

| 机制         | 行为                                                                                                                            |
| ------------ | ------------------------------------------------------------------------------------------------------------------------------- |
| 有限重试     | provider 调用异常最多重试 `PROVIDER_MAX_RETRIES` 次，指数退避；**超时不重试**，避免叠加等待                                     |
| 超时         | `asyncio.wait_for(...)` + `REQUEST_TIMEOUT_SECONDS`，超时抛 `ProviderTimeoutError`                                              |
| 修复上限     | `max_fix_rounds`（默认 2）；用尽后进入 `needs_attention`，不再自动重试                                                          |
| 失败原因     | `TaskRecord.error` + `task.failed` 事件（带 `error` 顶层字段与 `from` 状态）                                                    |
| 任务取消     | `POST /api/tasks/{id}/cancel`；运行中任务在安全点（每阶段开始、每次调用后、每次门禁后）退出并进入 `cancelled`；终态任务返回 409 |
| 产物保留     | 取消/失败只改状态，不删除任何文件；取消后 `task.json`、`prd.md`、`index.html` 等仍在                                            |
| 重复执行保护 | 同一 task 并发启动拒绝；终态任务不能再执行；相同需求有非终态任务时 API 返回 409                                                 |

**边界**：取消是协作式的——不会中断已经发出的 HTTP 请求，最长等待一个调用超时或一个阶段展示时长；重试只针对调用异常，不重试「输出不合法」（重试同样提示词大概率仍然不合法）。

---

## Harness 5：Budget Guard

**实现位置**：`backend/budget.py`、`backend/providers/*`、`backend/core/vessel.py`、`backend/config.py`

记录字段（`TaskBudget`，随 `task.json` 落盘）：

```
budget_usd / spent_usd(估算) / calls / input_tokens / output_tokens
unknown_usage_calls / unknown_cost_calls / downgraded_calls / blocked_calls / models
```

决策顺序（`BudgetGuard.before_call`，在 `asyncio.Lock` 内执行）：

1. `spent_usd >= budget_usd` → 拒绝，`blocked_calls += 1`，`Vessel` 抛 `BudgetExceededError`，不再发起调用；
2. `spent_usd / budget_usd >= BUDGET_SOFT_RATIO`（默认 0.7）且配置了 `LIGHT_MODEL` → 改用轻量模型，`downgraded += 1`；
3. 否则使用员工/全局首选模型。

费用口径：

- 模型名与单价全部来自配置，代码里没有写死任何模型名或价格；
- `MODEL_PRICES={"模型名":{"input_per_1k":x,"output_per_1k":y}}`，留空则费用未知；
- `estimated_cost_usd = input/1000 × 单价 + output/1000 × 单价`，这是**估算**，不是供应商账单；
- 接口没返回 usage，或该模型没有单价 → `cost_status="unknown"`、`unknown_cost_calls += 1`，**不会填 0 冒充真实费用**；
- token 用量本身也带来源标记：`provider` / `estimated`（Mock 按字符数估算）/ `unknown`。

输出长度上限：`MAX_OUTPUT_TOKENS` 作为 `max_tokens` 传给 provider。

并发限制：预算检查和记账串行化，`MAX_CONCURRENT_CALLS`（默认 1）限制同时在途的模型调用，避免并发窗口把预算放大。

**边界**：

- 预算是**进程内**状态，进程重启会清零；多 worker 部署时每个 worker 各算各的（当前单进程部署，见 architecture 已知问题）。
- 调用前无法预知本次输入 token，因此最后一次调用可能让实际花费**略微超过上限**（本次实测：预算 $0.0005，实际估算 $0.0011，第 3 次调用被拒）。这是「最多超一次调用」的有界超额，不是无限制穿透。
- 没有对账能力：`estimated` 与真实账单可能不同，账单需要另接供应商接口。

---

## Harness 6：Event Trace

**实现位置**：`backend/models/events.py`、`backend/workflow/engine.py::_emit`、`backend/bus.py`、`backend/main.py`

统一字段：

| 字段          | 说明                                                                      |
| ------------- | ------------------------------------------------------------------------- |
| `task_id`     | 所属任务                                                                  |
| `type`        | `EventType`（`tool.called`、`budget.updated`、`task.cancelled` 等 14 种） |
| `agent`       | 相关员工（可为空）                                                        |
| `created_at`  | UTC 时间戳，WS 消息里为 `ts`                                              |
| `duration_ms` | 本次调用耗时                                                              |
| `model`       | 实际使用的模型                                                            |
| `token_usage` | `{input_tokens, output_tokens, total_tokens, source}`                     |
| `result`      | `ok` / `failed` / `skipped`                                               |
| `error`       | 失败原因（成功为 null）                                                   |
| `data`        | 事件特定载荷（工具名、预算快照、审查结论等）                              |

写入顺序固定：追加到 `record.events` → `store.save()` 写 `task.json` → `bus.publish()` 推送 WebSocket。
`task.json` 是唯一真相源，断线重连先收 `task.snapshot` 再收增量，不会丢状态。

**边界**：事件日志当前无上限（长任务会持续增长）；EventBus 是进程内的，多 worker 部署需要外部消息层。

---

## 验收记录（Mock 模式，真实运行）

环境：`MOCK_MODE=true`，本地 uvicorn，贪吃蛇需求。数字来自实际落盘的 `task.json`，未做任何人工改写。

| #   | 验收项                 | 证据                                                                                                                                                                                                                                                    |
| --- | ---------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 1   | 四 Agent 工具权限      | 任务 `c5e97426164a`：`tool.called` 事件集合与 `ROLE_TOOLS` 完全一致（coo 2 个、engineer 3 个、reviewer 3 个、marketer 3 个）                                                                                                                            |
| 2   | 错误输出不破坏工作流   | `BadProvider` 返回非 JSON：COO 阶段失败，任务 `failed`，`task.json` 保留；`test_trace_records_error_on_failure`                                                                                                                                         |
| 3   | Reviewer 拒绝触发修复  | 同一任务 `review_verdicts = [(1, ITERATE), (2, PASS)]`，`fix.requested` 带 `history/index.v1.html` 快照                                                                                                                                                 |
| 4   | 修复次数达上限停止     | `tests/test_workflow.py::test_fix_limit_reached_goes_to_needs_attention` → `needs_attention`，`fix_attempts == 2`                                                                                                                                       |
| 5   | 预算阈值影响模型选择   | 任务 `9eba54b444d0`：预算 $0.005、单价按配置；前 4 次 `mock`，越过 70% 后第 5、6 次改用 `mock-light`，`downgraded_calls=2`，任务完成。预算降到 $0.0005 的任务 `0bacc3f6de11`：第 3 次调用被拒，`blocked_calls=1`，任务 `failed`，错误写明估算花费与预算 |
| 6   | WebSocket 展示真实状态 | 任务 `c5e97426164a` WS 消息类型含 `tool.called`、`budget.updated`、`review.completed`、`fix.requested`；首帧 `task.snapshot` 含 `budget`、`cancel_requested_at`                                                                                         |
| 7   | 失败后日志与产物保留   | 任务 `0bacc3f6de11` 失败后仍有 `prd.md`、`index.html`、`gate.json`，事件 26 条；取消测试 `test_task_cancel_keeps_artifacts` 取消后 `prd.md` 保留                                                                                                        |

未配置 `MODEL_PRICES` 的任务 `acf52a57ccfd`：6 次调用、`unknown_cost_calls=6`、`spent_usd=0`、`cost_status="unknown"`，说明无价格时不会伪造费用。

测试统计：`uv run pytest -q` → **78 passed**。

## 已知边界汇总

1. 预算与事件总线都是进程内状态，重启清零、不支持多 worker。
2. 取消是协作式的，不能中断在途 HTTP 调用。
3. 费用是配置单价 × 估算 token，不能替代真实账单。
4. 最后一次调用可能让花费有限超额（最多一次调用）。
5. 机械门禁的玩法断言依赖游戏暴露测试探针；未暴露时标 `unverified`。
6. 事件日志无上限，长任务需后续做归档/截断。
