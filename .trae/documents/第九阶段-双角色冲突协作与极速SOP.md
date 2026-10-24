# 第九阶段：双角色冲突协作与极速 SOP

## Context

OneGameStudio 目前是四员工顺序工作流（COO → Engineer → 机械门禁 → Reviewer → 修复循环 → Marketer）。阶段 8 已具备 Talent 版本库与自进化，Mini-6 Harness 已覆盖契约、工具权限、质量门禁、恢复、预算与事件追踪；但「游戏版本」目前只是 `history/index.v{n}.html` 修复快照，任务上没有 SOP、冲突决策、来源版本与 run 记录。

本阶段新增两位 AI 员工（Creative Director、Delivery Director），在进入编码前形成有限、可审计的冲突协作，并提供 FAST / BALANCED / CREATIVE 三种 SOP。核心目标是：**复用现有 Vessel / Talent / Harness，不重写执行器；不为戏剧效果制造争论；不因“极速”绕过质量门禁与测试。**

### 关键语义决定

1. **CEO = 用户需求输入阶段**。本阶段只新增两名员工，不新增 CEO Agent；COO 仍是方案汇总与最终决策者。
2. **CREATIVE 的“最多一轮额外方案修订”**：Creative 提案 → Delivery 挑战 → 若 Delivery 判定 `feasibility != "feasible"`，Creative 针对挑战做**恰好一次**修订 → COO 最终决策。不会无限讨论。
3. **FAST 跳过 Marketer 与两名总监**，但**绝不跳过**机械门禁、AI Reviewer、修复循环、预算检查与历史版本保留。
4. **并行是真实并发**：`max_concurrent_calls` 默认由 1 调整为 2，否则 Vessel 信号量会把两名总监串行化。预算超额窗口最多多出一次顾问调用，需在文档中明确。
5. **游戏版本 = 不可变记录**：每任务完成后写入 `versions/{task_id}-vN.json` + `.html`；历史版本只增不改；跨任务分支通过 `source_version_id` 复制父 HTML 到新任务 `source/` 只读引用，并记录 SHA-256。

## 实施步骤

### 1. 契约、Talent 与工具（先打地基）

- `backend/models/sop.py`（新建）
  - `SOPMode(fast|balanced|creative)`
  - `ConflictDecision`：`decision(adopt|simplify|reject)`、`summary`、`rationale`（必填）、`adopted_from(creative|delivery|both|neither)`
- `backend/schemas.py`
  - 新增 `CreativeProposal`：`innovation / player_value / complexity(low|medium|high) / priority(high|medium|low) / rationale`
  - 新增 `DeliveryAssessment`：`risk / feasibility(feasible|risky|infeasible) / simplification / priority / rationale`
  - `GamePRD` 增加可选 `conflict_decision: ConflictDecision | None`（FAST 时为 None，旧 PRD 仍可解析）
  - 注册 `OUTPUT_SCHEMAS`：`creative_proposal`、`delivery_assessment`
- `talents/creative.yaml`、`talents/delivery.yaml`（新建）
  - 提示词明确：基于事实提分歧，禁止为戏剧效果唱反调；认同对方时明确说明。
  - creative：输出创新建议、玩家价值、复杂度、优先级、依据。
  - delivery：输出最大交付风险、可行性、简化建议、优先级、依据。
  - `model: null`，由 Vessel 使用全局模型；工具权限最小化。
- `backend/tools.py`
  - 新增 `write_creative`（creative）、`write_delivery`（delivery）、`write_decision`（coo）。
  - `read_requirement` 扩展给 creative/delivery；`read_game` 扩展给 creative（用于历史分支）；`read_prd` 扩展给 creative/delivery。
  - 保持禁止 shell/exec 类工具与运行时双重校验。
- `backend/providers/mock.py`
  - 新增两个 schema 的确定性 payload；`prd` 在上下文含双方意见时附带 `conflict_decision`。
  - Delivery 在“挑战”上下文返回 `risky`，触发 CREATIVE 的一轮修订；Mock 仍不消耗真实 token。
- `backend/evolution/regression.py`
  - 为 `creative`、`delivery` 增加固定 `CASES`，否则 Talent 面板诊断会因 `ValueError` 返回 500。
- 同步更新：`tests/test_talents.py`（4→6 个 Talent、schema 断言）、`tests/test_harness.py`（`ROLE_TOOLS` 精确表）、`tests/test_evolution.py`（seed 名单）。

### 2. SOP 选择与版本模型

- `backend/workflow/sop.py`（新建）
  - `select_sop(requirement, requested, source_version_id) -> (SOPMode, reason)`。
  - 规则优先级：用户手动选择 > 有 `source_version_id`（创新分支）> 创新关键词 > 短句 + 局部修改关键词 → FAST > 默认 BALANCED。
  - 每个自动决定都返回**可读原因**，写入 `TaskRecord.sop_reason` 与 `sop.selected` 事件。
- `backend/models/version.py`（新建）
  - `GameVersion`：`version_id`、`parent_version_id`、`source_version_id`、`source_sha256`、`task_id`、`run_id`、`sop_mode`、`sop_reason`、`conflict_decision`、`creative_talent_version`、`delivery_talent_version`、`artifact_path`、`created_at`。
- `backend/models/contract.py`
  - `TaskRecord` 增加：`sop_mode`、`sop_reason`、`source_version_id`、`source_sha256`、`run_id`、`final_version_id`、`conflict_decision`、`creative_talent_version`、`delivery_talent_version`、`metrics`（`elapsed_ms`、`model_calls`、`parallel_wall_ms`）。
  - `TaskCreateRequest` 增加可选 `sop_mode`、`source_version_id`。
- `backend/store.py`
  - `save()` 改为临时文件 + `replace`，避免 task.json 半写。
  - `save_version()`：版本号取同任务已有最大号 +1；先检查目标不存在再写 `.html` 与 `.json`，拒绝覆盖；更新 `final_version_id`。
  - `find_version(version_id)`：严格校验 `^[0-9a-f]{6,32}-v[1-9]\d*$`，跨 `output/*/versions` 查找，核对 `task_id`、文件存在、`resolve()` 位于 `store.root` 内，拒绝符号链接与路径穿越。
  - `create()` 支持 `source_version_id`：校验父版本存在，复制父 HTML 到新任务 `source/{version_id}.html`，记录 SHA-256。
  - `list_versions(task_id)`。
- `backend/main.py`
  - `POST /api/tasks` 接收并校验 `sop_mode` / `source_version_id`（父版本不存在返回 404）。
  - 新增 `GET /api/tasks/{id}/versions`。
  - 产物白名单加入 `creative_proposal.json`、`delivery_assessment.json`、`conflict_decision.json`。
  - `app.version` 升到 `0.9.0`。

### 3. 引擎：冲突阶段 + 三种 SOP

改造 `backend/workflow/engine.py`，不重写 Vessel：

- 拆 `_call` 为「执行」与「提交」两段：
  - `_execute(...)` 只调用 Vessel，返回 `AgentResult`，不碰 `record`。
  - `_commit_result(...)` 串行更新 token/budget/talent_versions、发事件、落盘。
  - 这样并行阶段不会并发写 `task.json`。
- `_run` 顺序：
  1. 解析 SOP（`SOPMode` + 原因），发 `sop.selected`；`PENDING → PLANNING`。
  2. **Conflict Gate**（PLANNING 内）：
     - FAST：不调用 creative/delivery。
     - BALANCED：`asyncio.gather` 并行执行 creative 与 delivery（`return_exceptions=True`，等待双方结束后串行提交；`max_concurrent_calls >= 2` 时真实并发）。
     - CREATIVE：顺序 creative → delivery（上下文含 creative 提案）→ 若 `feasibility != feasible` 再做且仅做一轮 creative 修订。
     - 每份意见写出 `creative_proposal.json` / `delivery_assessment.json`，发 `conflict.opinion`（数据来自真实结构化输出）。
  3. COO：上下文含需求、双方意见、用户明确要求优先规则；输出 PRD + `conflict_decision`。有意见却缺失决策时抛 `StageExecutionError`。写 `prd.md` 与 `conflict_decision.json`，发 `conflict.resolved`。
  4. `CODING`：Engineer；若任务有 `source_version_id`，把父 HTML 作为增量修改上下文传入。
  5. 机械门禁 + Reviewer + 修复循环（与现状一致，FAST 也照常执行）。
  6. 审查 PASS 后：
     - FAST：`REVIEWING → COMPLETED`（状态机新增该迁移），不调用 Marketer。
     - BALANCED/CREATIVE：`MARKETING → COMPLETED`，Marketer 规则不变。
  7. 转 COMPLETED 前写 `GameVersion`，记录本 Run 的 SOP、冲突决策、双总监 Talent 版本、`source_version_id`、`run_id`。
- 入口 `start()` 记录实际 `elapsed_ms`；`_execute` 累计 `model_calls`；冲突阶段记录真实 `parallel_wall_ms`。
- `Vessel.execute` 增加可选 `max_output_tokens` 覆盖；顾问输出使用配置 `opinion_max_output_tokens`（默认 600），代码生成仍用全局上限。
- `backend/config.py`：新增 `opinion_max_output_tokens`；`max_concurrent_calls` 默认 2。
- `backend/models/events.py`：新增 `SOP_SELECTED="sop.selected"`、`CONFLICT_OPINION="conflict.opinion"`、`CONFLICT_RESOLVED="conflict.resolved"`。
- `backend/workflow/state_machine.py`：仅新增 `REVIEWING → COMPLETED`，不开放 `FIXING → COMPLETED`。

### 4. 前端像素办公室与驾驶舱

- `frontend/office.js`
  - `AGENTS` 改为 3 列 × 2 行：`x=150/440/730`，`y=156/380`。
    - 上排：COO、CREATIVE、DELIVERY；下排：ENGINEER、REVIEWER、MARKETER。
  - 新增两名员工的像素颜色/发型/姓名。
  - 新增 `setSpeech(agentId, text)`：只更新气泡文本，不改状态；观点来自真实 `conflict.opinion` 事件。
  - 保留 `activeAgent` 单动画约束：并行阶段两名员工都显示 `working`，但同一时刻仍只有一名播放动作。
- `frontend/index.html`
  - 顶部表单增加 SOP 选择器：`auto / FAST / BALANCED / CREATIVE`；可选 `source-version` 输入。
  - 新增 `Studio` 标签；保留现有五标签样式。
- `frontend/app.js`
  - `AGENT_NAME` 增加 creative/delivery。
  - 处理 `sop.selected`、`conflict.opinion`、`conflict.resolved`；`hydrate()` 从任务快照恢复 SOP/决策。
  - Studio 面板从真实产物渲染：`creative_proposal.json`、`delivery_assessment.json`、`conflict_decision.json`、版本记录、`elapsed_ms`、`model_calls`、`parallel_wall_ms`。
  - 提交时按选择发送 `sop_mode`（auto 则省略）与 `source_version_id`。
  - Mock 模式继续由顶部徽标与 Studio 文案明确标识；不伪造进度。
- `frontend/style.css`
  - 复用 `.tabs`、`.block`、`.plain`、`.verdict` 等现有像素风样式；仅补 SOP 选择器与 Studio 布局。

### 5. 测试与实测对比

新增 `tests/test_sop.py`，并更新受影响的现有测试：

- **场景 A（FAST）**：`把游戏背景颜色改成蓝色` → 断言模式为 FAST、原因已记录、creative/delivery/marketer 均未被调用、Reviewer 与机械门禁仍执行、无营销产物、版本记录完整。
- **场景 B（BALANCED）**：`开发一个经典贪吃蛇小游戏` → 断言 creative/delivery 被调用、Provider 观测到 `max_active == 2`（真实并行）、COO 决策存在、Marketer 执行、双总监 Talent 版本写入版本记录。
- **场景 C（CREATIVE 分支）**：先用一次任务生成父版本；再带 `source_version_id` 创建新任务 → 断言自动选择 CREATIVE、Creative 调用次数最多为“提案 + 1 次修订”、父版本文件哈希不变、新版本 `source_version_id` 正确、Engineer 上下文含父 HTML。
- 另补：角色权限拒绝、预算耗尽后保留产物、Delivery 调用异常时任务失败但 `creative_proposal.json` 与父版本仍在、`task.json` 可重新读取。
- **对比**：同一 Mock 场景记录 FAST / BALANCED 的 `model_calls` 与实际 `elapsed_ms`。只断言可确定的事实（调用次数），**不预设耗时一定更短**；Mock 耗时不代表真实网络延迟，结论写入文档。
- 必须同步修改：
  - `tests/test_workflow.py`：`ScriptedProvider` 增加 creative/delivery 默认响应；`PRD_JSON` 补 `conflict_decision`；产物断言加入三个冲突文件。
  - `tests/test_harness.py`：`ROLE_TOOLS` 期望表更新；PRD 补决策字段。
  - `tests/test_api.py`：Mock 流程断言与产物集合更新。
  - `tests/test_talents.py`、`tests/test_evolution.py`：员工数量与 seed 名单更新。
- 新增 `tests/test_versions.py`：版本号递增、拒绝覆盖、父版本跨任务查找、路径穿越/非法 version_id 拒绝、source SHA-256。

### 6. 文档

- 新建 `docs/conflict-protocol.md`：角色职责、输出契约、Conflict Gate 流程、决策语义、有限讨论、用户优先、失败与降级、事件/产物/版本字段。
- 新建 `docs/fast-sop.md`：FAST 适用边界、自动选择规则、跳过与绝不跳过的步骤、示例、预算/超时/输出长度策略。
- 更新 `docs/architecture.md`（v0.9）、`docs/progress.md`（阶段 9 状态、测试结果、Mock 实测对比表与局限）、`docs/HANDOFF.md`。

## 验证

1. 分阶段运行：
   - `uv run pytest -q tests/test_talents.py tests/test_vessel.py tests/test_gate.py`
   - `uv run pytest -q tests/test_sop.py tests/test_versions.py`
   - `uv run pytest -q tests/test_workflow.py tests/test_harness.py tests/test_api.py tests/test_evolution.py`
2. 全量：`uv run pytest -q`（基线 97 通过，目标全部通过）。
3. 手工验收（Mock）：启动 `uv run uvicorn backend.main:app --reload`
   - 输入“把背景改成蓝色” → FAST：无营销/无总监调用，仍有 `gate.json` 与 `review.json`。
   - 输入“开发经典小游戏” → BALANCED：像素办公室六人、两名总监同时 working、Studio 显示双方观点与 COO 决策。
   - 用上一任务 `final_version_id` 作为 source → CREATIVE：新任务产物独立，父版本未被修改。
   - 检查 `task.json`、`versions/*.json`、WS 事件顺序（先落盘 task.json 再广播）。

## 风险与边界

- 并发调高到 2 会扩大预算超额窗口；预算检查仍在锁内，最坏多一次顾问调用，需在文档中说明。
- 并行提交采用“先 gather 执行、后串行落盘”，避免共享 `TaskRecord` 竞态。
- Mock 的耗时与 token 只是估算，不得当作真实模型性能；文档与 UI 均需标明。
- 新增 Talent 必须带回归用例，否则自进化诊断会报错。
- 版本 ID 只能由服务端生成；任何外部输入都必须经过正则、目录归属与符号链接校验。
