# 阶段 6：Mini-6 Harness 实施计划

## Context

阶段 1–5 已经跑通「COO → Engineer → 机械门禁 → Reviewer →（修复循环）→ Marketer」全流程，但运行保障机制散落在各文件中，且存在明确缺口：

| Harness | 现状 | 缺口 |
| --- | --- | --- |
| 1 Task Contract | Pydantic 契约 + 9 态状态机 + `assert_transition` 已有 | 无「已取消」状态；错误类型未成体系归档 |
| 2 Tool Policy | 只有加载期 `ALLOWED_TOOLS={"read_contract","write_artifact"}`，与业务工具名不符 | 无显式工具注册表、无运行时拦截、YAML 里是占位工具名 |
| 3 Quality Gate | 阶段 3 已完整（Playwright 10 项检查 + AI Reviewer + 后端强制裁决） | 仅需文档化裁决边界 |
| 4 Recovery | 2 次修复上限、调用超时、错误落盘、同任务并发保护、产物保留已有 | 无任务取消、无 provider 有限重试、无「已终态不可再跑」保护 |
| 5 Budget Guard | Vessel 实例级累计 `_spent_usd`，调用前只判 `>= budget_usd`；OpenAI 费用恒 0 | 无单任务预算、无 70% 降级、无价格表、无 max_tokens、无未知用量标记、无并发限制 |
| 6 Event Trace | 11 类事件 + WS 推送已有；`duration_ms`/`tokens`/`cost_usd` 塞在 `data` | 缺 `model`/`duration`/`token_usage`/`result`/`error` 顶层统一字段 |

本阶段目标：**整合为统一的 Mini-6 Harness，不重构工作流业务逻辑**。改动集中在「契约字段补齐 + 新增两个独立模块（`tools.py`、`budget.py`）+ 引擎挂载点」。全部验收使用贪吃蛇 Mock 端到端，不伪造费用与模型切换结果。

---

## 一、Harness 1：Task Contract

**修改 `backend/models/contract.py`**
- `TaskStatus` 新增 `CANCELLED = "cancelled"`；加入 `TERMINAL_STATUSES`。
- `TaskRecord` 新增 `budget: TaskBudget | None = None`（来自 `backend.budget`），用于前端/日志展示本任务预算快照；新增 `cancel_requested_at: datetime | None`（可选，便于追溯）。
- `backend/models/events.py` 新增 `EventType.TASK_CANCELLED = "task.cancelled"`。

**修改 `backend/workflow/state_machine.py`**
- 所有非终态增加 `-> CANCELLED` 迁移；`PENDING -> CANCELLED` 也允许（尚未启动就取消）。
- 终态集合保持不可再迁移。

**错误类型归档（不大改，只补两个）**
- `backend/workflow/state_machine.py` 已有 `InvalidTransitionError`（沿用）。
- `engine.py` 新增 `TaskNotRunnableError`（终态任务禁止再执行）、`TaskCancelledError`（引擎内部取消信号）。
- 错误家族保持三组：`VesselError`（模型层）、`WorkflowError`（编排层）、`TalentConfigError`/`ToolPolicyError`（配置与权限层）。`docs/harness.md` 用表格归档。

---

## 二、Harness 2：Tool Policy

**新建 `backend/tools.py`**
- `ToolSpec(name, description, allowed_agents)`；`TOOL_SPECS` 显式注册 9 个工具：
  - `read_requirement`（coo）
  - `write_prd`（coo）
  - `read_prd`（engineer, marketer）
  - `write_game`（engineer）
  - `read_review`（engineer, marketer）
  - `read_game`（reviewer）
  - `run_tests`（reviewer）
  - `write_review`（reviewer）
  - `write_marketing`（marketer）
- `ROLE_TOOLS: dict[str, frozenset[str]]` 由 `TOOL_SPECS` 反向生成，作为唯一真相。
- `ToolRegistry`：`names()` / `allowed_for(agent)` / `require(agent, tool)`；`require` 不通过抛 `ToolPolicyError`。
- `DEFAULT_REGISTRY = ToolRegistry(TOOL_SPECS)`。
- **不注册任何 shell / subprocess / 任意代码执行工具**；测试断言注册表中无 `shell*`，且 `require("engineer","shell_exec")` 抛错。

**修改 `backend/talents.py`**
- 删除旧 `ALLOWED_TOOLS`，改为校验：
  1. `allowed_tools ⊆ DEFAULT_REGISTRY.names()`；
  2. `allowed_tools ⊆ DEFAULT_REGISTRY.allowed_for(talent.id)`（按员工身份校验，YAML 多申请工具即拒绝加载）。
- 保留 `output_schema` 注册校验。

**修改 4 个 `talents/*.yaml`**
- coo: `read_requirement, write_prd`
- engineer: `read_prd, write_game, read_review`
- reviewer: `read_game, run_tests, write_review`
- marketer: `read_prd, read_review, write_marketing`

**修改 `backend/workflow/engine.py`**（运行时拦截 + 证据）
- 构造参数新增 `tools: ToolRegistry = DEFAULT_REGISTRY`。
- 新增 `_use_tool(record, agent, tool)`：先 `registry.require(...)`，再发 `EventType.TOOL_CALLED = "tool.called"` 事件（`agent`、`data={"tool": ...}`），落盘并推送。
- 挂载点：
  - COO：`read_requirement`（读需求前）、`write_prd`（写 prd.md 前）
  - Engineer：`read_prd`（初版上下文）、`read_review`（修复上下文）、`write_game`（写 index.html 前）
  - Reviewer：`read_game`（读代码前）、`run_tests`（执行机械门禁前）、`write_review`（写 review.json 前）
  - Marketer：`read_prd`、`read_review`（拼上下文前）、`write_marketing`（写两份营销产物前）

---

## 三、Harness 3：Quality Gate（审计为已具备，不改业务逻辑）

- 机械门禁 `backend/gate/mechanical.py` 保持：真实 Chromium、10 项检查、`pass/fail/unverified`。
- 裁决后端规则保持：门禁 fail 时强制 `ITERATE` 并置 `forced_by_gate=True`；Reviewer 输出无法解析直接终止；门禁失败导致修复后必须重跑门禁与审查。
- 仅在 `docs/harness.md` 明确「谁有权裁决 / 谁无权裁决」边界。

---

## 四、Harness 4：Recovery

**有限重试（provider 层）**
- `backend/config.py` 新增 `provider_max_retries: int = 1`、`provider_retry_backoff_seconds: float = 0.5`。
- `backend/core/vessel.py` 的 `execute()` 改为重试循环：仅对 `ProviderCallError`（网络/鉴权等）重试，每次指数退避；**超时不重试**（避免叠加等待）；每次失败写 `STAGE_FAILED` 事件并带 `error` 字段；重试次数用尽抛 `ProviderCallError`。

**超时**：沿用 `asyncio.wait_for` + `request_timeout_seconds`。

**任务取消**
- `WorkflowEngine.cancel(task_id) -> TaskRecord`：
  - 终态 → 抛 `TaskNotRunnableError`；
  - 在 `_running` → 置 `_cancel_requested` 标记并返回当前记录（后台循环在安全点退出）；
  - 未在运行（如 pending 尚未调度）→ 直接迁移到 `CANCELLED` 并发 `task.cancelled`。
- `_run()` 在每阶段开始、每次 `_call` 返回后、每次门禁后调用 `_check_cancel(record)`，命中抛 `TaskCancelledError`；外层捕获后走 `_cancelled(record)`：置终态、发事件、**不删除任何已生成产物**。
- `_run()` 开头新增终态保护：`if record.is_terminal: raise TaskNotRunnableError`。
- `backend/main.py` 新增 `POST /api/tasks/{task_id}/cancel`：非终态返回 202 + 最新记录；终态 409。

**失败原因记录**
- 沿用 `TaskRecord.error`，统一在 `_fail` 写入；`task.failed` 事件带 `error` 顶层字段与 `data["from"]`。

**已生成文件保留 / 非法重复执行保护**：沿用 `TaskStore`（只增不删）+ `_running` 集合；新增测试覆盖。

---

## 五、Harness 5：Budget Guard

**新建 `backend/budget.py`**
- `ModelPrice(input_per_1k, output_per_1k)`；价格**全部来自配置**，默认空（不硬编码任何模型名或价格）。
- `TaskBudget`：`task_id / budget_usd / spent_usd(估算) / calls / input_tokens / output_tokens / unknown_usage_calls / downgraded_calls / blocked_calls / models`，`ratio` 属性。
- `UsageRecord`：`agent / model / input_tokens / output_tokens / usage_source / estimated_cost_usd / cost_status / duration_ms`。
- `BudgetDecision`：`allowed / model / downgraded / reason / budget`。
- `BudgetGuard`：
  - `before_call(task_id, preferred_model, agent)`（`asyncio.Lock` 保护）：
    - `spent_usd >= budget_usd` → `allowed=False`，`blocked_calls+=1`；
    - `ratio >= soft_ratio(0.7)` 且配置了 `light_model` → 返回轻量模型，`downgraded=True`（后续调用持续降级）；
    - 否则用首选模型。
  - `after_call(...)`：有价格且用量来源非 unknown → 计算 `estimated_cost_usd`；否则 `None` + `cost_status="unknown"`，`unknown_usage_calls+=1`。
  - `snapshot(task_id)` / `register(task_id, budget)`；`from_settings(settings)` 解析 `MODEL_PRICES` JSON，解析失败直接报配置错误。
  - 明确注释：`estimated_cost_usd` 是**按配置单价的估算**，不是账单；无价格/无用量一律标记 unknown，不做猜测。

**修改 `backend/config.py`**
- `budget_usd` 语义明确为「单任务预算」。
- 新增：`budget_soft_ratio: float = 0.7`、`light_model: str = ""`、`max_output_tokens: int = 2048`、`model_prices: str = ""`、`max_concurrent_calls: int = 1`、`provider_max_retries`、`provider_retry_backoff_seconds`。
- `llm_model` 默认改为 `""`（真实模式必须由环境变量指定，避免硬编码过时模型名）。

**修改 `backend/providers/base.py`**
- `ProviderResponse` 新增 `usage_source: Literal["provider","estimated","unknown"] = "provider"`。
- `complete(..., max_tokens: int | None = None)`。

**修改 `backend/providers/openai.py`**
- payload 增加 `max_tokens`（有值时）。
- 有 `usage` → `usage_source="provider"`；无 `usage` → `usage_source="unknown"` 且 token 记 0。
- 不再计算费用（费用统一由 BudgetGuard 按配置估算）。
- 构造时校验 `settings.llm_model` 非空。

**修改 `backend/providers/mock.py`**
- 接受 `max_tokens`（忽略），`usage_source="estimated"`（字符数估算，非真实用量）。

**修改 `backend/core/vessel.py`**
- 构造参数新增 `guard: BudgetGuard | None`、`max_output_tokens`、`max_concurrent_calls`、`max_retries`、`retry_backoff`。
- `execute()`：调用前 `guard.before_call()`，被拒抛 `BudgetExceededError`；模型取 `decision.model`。无 guard 时保留旧的实例级预算行为（兼容现有测试）。
- `asyncio.Semaphore(max_concurrent_calls)` 包住 provider 调用，显式限制并发，避免预算检查与调用之间被并发放大。
- 调用后 `guard.after_call()` 结算并把 `TaskBudget` 快照写回 `TaskRecord.budget`；`AgentResult` 新增 `usage_source`、`cost_status`、`budget_ratio`。
- tracer 的 `STAGE_*` 事件补齐 `model`/`duration_ms`/`token_usage`/`result`/`error`。

**修改 `backend/workflow/engine.py`**
- 构造参数新增 `budget: BudgetGuard | None`。
- 每次 `_call` 完成后：`record.budget = budget.snapshot(task_id)`；发 `EventType.BUDGET_UPDATED = "budget.updated"`（`data` 含估算花费、比例、调用次数、是否降级、未知用量次数）。
- `BudgetExceededError` 已被现有 `VesselError` 捕获 → 任务进 `FAILED`，`error` 记录「预算达到上限」，**后续不再发起任何模型调用**。

---

## 六、Harness 6：Event Trace

**修改 `backend/models/events.py`**
- 新增 `TokenUsage(input_tokens, output_tokens, total_tokens)`。
- `TraceEvent` 新增可选顶层字段：`model: str | None`、`duration_ms: int | None`、`token_usage: TokenUsage | None`、`result: Literal["ok","failed","skipped"] | None`、`error: str | None`。
- `as_message()` 输出上述字段（保持旧字段不变，前端向后兼容）。
- 事件写入顺序保持：追加 `record.events` → `store.save` → `bus.publish`（`task.json` 是唯一真相源）。

**修改 `backend/workflow/engine.py`**
- `_emit(...)` 增加上述可选参数并透传。
- `_call` 成功：`model`、`duration_ms`、`token_usage`、`result="ok"`；失败：`result="failed"` + `error`。
- `_fail` / `_cancelled` / `_use_tool` 同样填统一字段。

**前端**：`frontend/app.js` 的 `applyEvent` 增加 `task.cancelled` / `budget.updated` 分支（取消时任务状态条切到终态；预算事件刷新日志即可）。日志消息里直接展示「模型 · token · 耗时」真实值。

---

## 七、测试与验收

**新增 `tests/test_harness.py`**
1. `test_tool_registry_has_no_shell`：注册表无 `shell/subprocess/exec` 类工具；`require("engineer","shell_exec")` 抛 `ToolPolicyError`。
2. `test_talent_tools_match_role_policy`（扩展 `test_talents.py`）：四名员工 YAML 的工具与 `ROLE_TOOLS` 一致；COO 申请 `write_game` 被拒绝加载。
3. `test_tool_policy_runtime_enforced`：引擎事件流中出现对应 `tool.called`，且不存在越权工具名。
4. `test_provider_retry_then_success`：脚本 provider 第一次抛异常、第二次成功 → 任务完成，`STAGE_FAILED` 事件带 `error`。
5. `test_task_cancel_keeps_artifacts`：`stage_min_seconds` 调大 + 后台运行，中途 `cancel` → `CANCELLED`，`prd.md`/`index.html`/`review.json` 仍在，`task.cancelled` 事件存在。
6. `test_cancel_terminal_task_rejected`：终态调 `cancel` 抛 `TaskNotRunnableError`（API 层 409）。
7. `test_budget_downgrades_to_light_model`：`BudgetGuard` 配价格（测试内自定义模型名 `strong-model`/`light-model` 与单价），前两次用首选模型，越过 70% 后第三次自动改用轻量模型；断言 provider 实际收到的 model。
8. `test_budget_blocks_when_exhausted`：预算花完后 `execute` 抛 `BudgetExceededError`，任务失败且 `error` 含「预算」，`blocked_calls >= 1`。
9. `test_unknown_cost_is_marked`：无价格表时 `cost_status="unknown"`、`estimated_cost_usd is None`，不伪造 0 费用。
10. `test_event_trace_unified_fields`：`agent.status_changed` 事件含 `model/duration_ms/token_usage/result`，`task.failed` 含 `error`；`as_message` 同步带出。
11. `test_ws_snapshot_includes_budget_and_cancel`（`tests/test_api.py` 扩展）：WS 首帧快照包含 `budget` 字段；`POST /cancel` 后快照 `status="cancelled"`。

**保留现有测试**：`test_workflow.py` 的 2 次修复上限、Reviewer 拒绝触发修复、错误输出不破坏工作流、失败保留产物等全部继续通过。

**端到端验收（Mock 贪吃蛇）**
- 启动 `uv run uvicorn backend.main:app`，创建贪吃蛇任务，用脚本读取 `output/{task_id}/task.json`：
  - 四名员工 `tool.called` 集合与 `ROLE_TOOLS` 完全一致；
  - Reviewer 首次 ITERATE → `fix.requested` → 第二次 PASS；
  - 把 `MAX_OUTPUT_TOKENS`/预算调小后重跑一次，验证预算阻断路径（真实事件时间戳为准，不伪造）；
  - WebSocket 收到 `task.snapshot` + 增量事件；
  - 人为让 Marketer 失败，确认 `prd.md`/`index.html`/`review.json` 保留。
- `uv run pytest -q` 全绿。

---

## 八、文档与收尾

- 新建 `docs/harness.md`：六项机制逐项说明「实现位置、关键字段、裁决规则、边界/未覆盖项」，附验收证据表（7 条 → 对应测试与事件）。
- 更新 `docs/progress.md`：新增「阶段 6：Mini-6 Harness」章节（改动文件、测试统计、验收结果、已知边界）。
- 更新 `README.md` 配置表与 API 表；更新 `.env.example` 新增配置项（含 `MODEL_PRICES` 示例，注释说明估算≠账单位）。
- 输出阶段 6 报告后停止，等待下一步指令。

---

## 九、涉及文件清单

| 动作 | 文件 |
| --- | --- |
| 新建 | `backend/tools.py`、`backend/budget.py`、`tests/test_harness.py`、`docs/harness.md` |
| 修改 | `backend/config.py`、`backend/models/events.py`、`backend/models/contract.py`、`backend/workflow/state_machine.py`、`backend/workflow/engine.py`、`backend/core/vessel.py`、`backend/talents.py`、`backend/providers/base.py`、`backend/providers/openai.py`、`backend/providers/mock.py`、`backend/main.py`、`talents/*.yaml`、`frontend/app.js`、`tests/test_talents.py`、`tests/test_api.py`、`docs/progress.md`、`README.md`、`.env.example` |

## 十、验证命令

```bash
cd /Users/lmliyascarlet/Desktop/项目/OneManCompany/OneGameStudio
uv run pytest -q
uv run python -c "from backend.tools import DEFAULT_REGISTRY; print(sorted(DEFAULT_REGISTRY.names()))"
uv run uvicorn backend.main:app --port 8000   # 手动/脚本端到端验收
```
