# OneGameStudio — AI 员工自进化（阶段 8）

> 版本：v0.8
> 本文只描述已实现的行为。未接入的能力（真实模型评估）在文中明确标注。

## 1. 目标与不变量

自进化让员工从任务与回归结果中积累经验，并把这些经验变成**可审计、可回滚**的 Talent 新版本。

三条不变量：

1. **历史不可覆盖**：每个版本写入后只读，当前启用哪一版由 `active.json` 指针决定。
2. **提案不自动生效**：必须经过固定回归评估 + 用户显式批准，才能成为启用版本。
3. **安全边界不参与进化**：工具白名单、输出契约、模型、质量门禁、预算、文件系统与执行逻辑都不允许被提示词层改动。

## 2. 闭环总览

```
任务 Run（记录实际 Talent 版本）
   ↓ 产物 / 门禁 / 审查
经验提取 extract.py
   ├─ 门禁 fail        → verified（证据指向 gate.json#check）
   └─ 审查问题(非 low) → candidate（等人工补证据）
   ↓
诊断 diagnose（固定回归集）
   └─ 漏检项 → verified 经验（证据指向评估报告与用例）
   ↓
进化提案 create_proposal（只接受 verified 经验）
   └─ 生成 candidate 版本（prompt 不变，追加 checklist）
   ↓
新旧版本评估 evaluate（同一组固定用例）
   └─ 写入 EvaluationReport，提案 evaluation_status = passed/failed
   ↓
用户批准 approve（评估必须 passed）
   └─ 候选版本 → active，旧版本 → inactive，写审计
   ↓
后续任务使用新版本（task.json 记录 talent_versions）
   ↓
必要时 rollback 到任意非候选版本
```

## 3. 领域模型

代码：[backend/evolution/models.py](file:///Users/lmliyascarlet/Desktop/项目/OneManCompany/OneGameStudio/backend/evolution/models.py)

### 3.1 TalentVersion

| 字段                | 说明                                            |
| ------------------- | ----------------------------------------------- |
| `talent_name`       | 员工 id：`coo / engineer / reviewer / marketer` |
| `version`           | 从 1 开始递增的整数                             |
| `parent_version`    | 由哪一版派生，基线为 `null`                     |
| `prompt`            | 系统提示词                                      |
| `checklist`         | 逐条自检清单，会被拼进系统提示词                |
| `created_at`        | 创建时间（UTC）                                 |
| `change_reason`     | 为什么产生这一版                                |
| `evaluation_result` | 如 `eval_ab12:passed`，未评估为 `null`          |
| `status`            | `candidate / active / inactive / rejected`      |
| `proposal_id`       | 由哪个提案生成，回滚版本为 `null`               |
| `allowed_tools`     | **只读镜像**，从基线复制，启用时逐字段比对      |
| `output_schema`     | 同上                                            |
| `model`             | 同上                                            |
| `label`             | 计算字段，如 `reviewer@v2`                      |

`prompt` 与 `checklist` 是唯一允许进化的内容；其余三个字段只是用来证明边界没被改动。

### 3.2 Lesson（经验）

| 字段                | 说明                                                 |
| ------------------- | ---------------------------------------------------- |
| `lesson_id`         | `lesson_xxxxxxxxxx`                                  |
| `source_project_id` | 来源任务；回归诊断为 `regression-suite`              |
| `source_version_id` | 来源版本标签或产物文件（如 `history/index.v1.html`） |
| `source_run_id`     | 来源任务 id 或评估报告 id                            |
| `related_talent`    | 该经验属于哪个员工                                   |
| `problem`           | 问题描述                                             |
| `improvement`       | 对应改进项，进入 checklist                           |
| `verification`      | 可追溯证据                                           |
| `status`            | `candidate / verified / rejected`                    |

模型校验：`status=verified` 时 `verification` 必填。**未验证的模型推测只能停留在 candidate，不能进入提案。**

### 3.3 EvolutionProposal

| 字段                                                   | 说明                                |
| ------------------------------------------------------ | ----------------------------------- |
| `proposal_id`                                          | `proposal_xxxxxxxxxx`               |
| `target_talent` / `base_version` / `candidate_version` | 目标员工与版本                      |
| `proposed_changes`                                     | 只允许 `prompt`、`checklist` 两个键 |
| `supporting_evidence`                                  | 支撑该提案的 `lesson_id` 列表       |
| `expected_benefit` / `risks`                           | 预期收益与风险说明                  |
| `evaluation_status`                                    | `pending / passed / failed`         |
| `approval_status`                                      | `pending / approved / rejected`     |
| `evaluation_id`                                        | 最近一次评估报告                    |
| `generated_by`                                         | 当前实现固定为 `rules`              |
| `created_at` / `decided_at`                            | 时间戳                              |

模型校验：构造时调用 `validate_changes`，出现受保护字段直接抛错。

### 3.4 EvaluationReport

包含逐用例结果（`EvaluationCaseResult`）、新旧两版指标（`EvaluationMetrics`）、逐条验收结果（`AcceptanceCriterion`）、总判定 `passed` 与 `notes`。

指标：检出率、误报率、Token、执行时间、覆盖用例数。Token 来源标记为 `estimated`，不是供应商账单。

## 4. 存储布局

代码：[backend/evolution/store.py](file:///Users/lmliyascarlet/Desktop/项目/OneManCompany/OneGameStudio/backend/evolution/store.py)

`EVOLUTION_DIR`（默认 `output/evolution`，在 `.gitignore` 的 `output/*` 范围内）：

```
output/evolution/
    talents/{talent}/
        versions/v1.json     基线版本（首次启动从 talents/*.yaml 播种，幂等）
        versions/v2.json
        ...
        active.json          当前启用版本指针 + 启用/回滚审计
    lessons/{lesson_id}.json
    proposals/{proposal_id}.json
    evaluations/{evaluation_id}.json
```

写入策略：`.tmp` 文件 + `replace` 原子替换。版本文件写入后不再覆盖，状态变化（active/inactive/rejected）通过重写同一版本文件表达，内容字段保持不变。

## 5. 闭环各步实现

代码：[backend/evolution/service.py](file:///Users/lmliyascarlet/Desktop/项目/OneManCompany/OneGameStudio/backend/evolution/service.py)

### 5.1 任务反馈与经验提取

[extract.py](file:///Users/lmliyascarlet/Desktop/项目/OneManCompany/OneGameStudio/backend/evolution/extract.py) 只读取任务已落盘的产物：

| 输入                                       | 生成经验               | 状态        |
| ------------------------------------------ | ---------------------- | ----------- |
| `gate.json` 中 `status == "fail"` 的检查项 | Reviewer：门禁失败原因 | `verified`  |
| `review.json` 中 `severity != low` 的问题  | Engineer：修复建议     | `candidate` |

- `source_project_id` / `source_run_id` 都映射为 `task_id`（当前没有独立 Project/Run 实体）。
- `source_version_id` 指向具体产物，如 `index.html` 或 `history/index.v{n}.html`。
- 按 `problem` 去重，已有经验不会重复写入。

### 5.2 经验验证

- `verify_lesson(id, verification)`：只有 `candidate` 可以验证，证据不能为空。
- `reject_lesson(id)`：`verified` 经验不能直接拒绝，避免误删已生效依据。
- 没有「模型自称已验证」的入口；证据必须由调用方显式提供。

### 5.3 诊断

`diagnose(talent)` 用当前启用版本跑一遍固定回归集：

- 报告 `engine=mock`（见第 9 节），`candidate` 与 `base` 是同一版，用于暴露漏检项。
- 每个未检出的缺陷用例生成一条 `verified` 经验，证据为 `回归评估 {evaluation_id}#{case_id} 未检出`。
- 相同 `problem` 已存在时跳过，重复诊断不会膨胀经验库。

### 5.4 提案

`create_proposal(talent, lesson_ids)` 的校验顺序：

1. 至少一条经验。
2. 经验必须属于同一员工。
3. 经验必须是 `verified`。
4. 经验不能被其他**非 rejected** 提案占用。
5. 改进项不能已经在当前 checklist 中。

通过后生成候选版本：

- `prompt` 与基线**完全相同**；
- `checklist` = 基线清单 + 经验改进项；
- 记录 `change_reason` 与 `proposal_id`。

### 5.5 固定回归评估

[regression.py](file:///Users/lmliyascarlet/Desktop/项目/OneManCompany/OneGameStudio/backend/evolution/regression.py) 对同一组用例分别跑新旧两版。用例与验收阈值写死在代码里，提案无法修改：

```python
ACCEPTANCE_CRITERIA = {
    "detection_min": 0.9,
    "false_positive_max": 0.1,
    "token_ratio_max": 2.0,
}
```

四条验收：

1. 检出率 ≥ 0.9。
2. 检出率不低于基线。
3. 误报率 ≤ 0.1。
4. Token 不超过基线的 2.0 倍。

全部通过 `passed=True`，提案才允许批准；否则 `evaluation_status=failed`。

### 5.6 审批与启用

`approve(proposal_id)`：

1. 提案必须 `pending` 且 `evaluation_status=passed`。
2. 先把提案落盘为 `approved`，再调用 `store.activate`。
3. `activate` 校验候选版本的工具白名单、输出契约、模型与基线完全一致。
4. 旧 active 版本改为 `inactive`，新版本改为 `active`，重写 `active.json` 并追加审计。
5. 任一步失败，提案回滚为 `pending`，不会出现「审批成功但未启用」的半状态。

### 5.7 回滚

`rollback(talent, version, reason)`：

- 任意非候选版本都可以重新启用（包括历史 `inactive` 版本）。
- 候选版本被拒绝：必须先评估并获得批准。
- 审计记录操作原因，`proposal_id=null`。

## 6. 固定回归用例

| 员工     | 用例                     | 期望                     |
| -------- | ------------------------ | ------------------------ |
| Reviewer | `normal_game`            | 正常游戏 PASS，不误报    |
| Reviewer | `restart_broken`         | 重新开始失效             |
| Reviewer | `pause_broken`           | 暂停失效                 |
| Reviewer | `score_wrong`            | 得分错误                 |
| Reviewer | `js_error`               | 未捕获 JS 异常           |
| COO      | `normal_requirement`     | 正常需求，不误报         |
| COO      | `missing_acceptance`     | 缺少可机械验证的验收标准 |
| COO      | `missing_lose_condition` | 缺少失败条件             |
| COO      | `vague_core_loop`        | 核心循环模糊             |
| Engineer | `game_normal`            | 单文件可运行，不误报     |
| Engineer | `no_restart`             | 缺少重新开始入口         |
| Engineer | `no_score`               | 计分未实现或未刷新       |
| Engineer | `js_error`               | 存在未处理 JS 异常       |
| Marketer | `kit_normal`             | 只宣传已验证功能，不误报 |
| Marketer | `fabricated_users`       | 编造用户数/下载量        |
| Marketer | `unverified_feature`     | 宣传未验证功能           |
| Marketer | `missing_plan`           | 缺少 7 天推广计划        |

每个员工另有一条「正常样例」，用于检查候选版本是否过拟合、把正常情况误判为缺陷。

## 7. 安全边界

`models.py` 在模型层强制约束：

| 允许修改    | 明确拒绝                                         |
| ----------- | ------------------------------------------------ |
| `prompt`    | `allowed_tools`、`tools`、`shell`                |
| `checklist` | `output_schema`、`schema`                        |
| —           | `model`、`api_key`、`llm_api_key`                |
| —           | `budget`、`budget_usd`、`max_output_tokens`      |
| —           | `gate`、`quality_gate`、`preview_csp`、`sandbox` |
| —           | `file_system`、`filesystem`、`core`、`engine`    |

三层防线：

1. 提案构造时 `validate_changes` 拒绝受保护键。
2. 候选版本创建时只接收 `prompt` 与 `checklist`，安全字段从基线复制。
3. 启用时 `store.activate` 再与基线逐字段比对，不一致直接拒绝。

## 8. 运行时接入

- `EvolutionStore` 装配到 `Vessel(talent_versions=...)`。
- `Vessel.run` 通过 `effective_spec` 读取当前启用版本的 `prompt`、`checklist` 与 `version`；工具、契约、模型仍来自基线。
- `checklist` 由 `Vessel._compose_system_prompt` 逐条拼进系统提示词。
- 每次调用返回 `talent_version`（如 `reviewer@v2`，基线为 `baseline`）。
- `WorkflowEngine._call` 把它写入 `TaskRecord.talent_versions`，并附在 `agent.status_changed` 事件的 `data` 中。这样每个 Run 都能追溯实际使用的 Talent 版本。

## 9. Mock 与 Live 评估

| 引擎   | 行为                                                      | 是否可用于审批       |
| ------ | --------------------------------------------------------- | -------------------- |
| `mock` | 按「checklist/prompt 是否显式覆盖缺陷验证点」做确定性判定 | 是，报告明确标注模拟 |
| `live` | 真实模型执行同一组用例                                    | **本阶段未接入**     |

`EvolutionService._engine()` 在 `MOCK_MODE=false` 时直接抛出：

> 真实模型评估尚未接入（阶段 8 仅提供 MOCK_MODE=true 的确定性回归评估），拒绝伪造真实模型评测结果

Mock 报告的 `notes` 固定包含：

> 引擎=mock：判定依据是检查清单是否显式覆盖缺陷验证点，属确定性模拟，不代表真实模型能力

同时 Token 指标标记 `token_source=estimated`，不写成真实账单。

## 10. API

代码：[backend/evolution/api.py](file:///Users/lmliyascarlet/Desktop/项目/OneManCompany/OneGameStudio/backend/evolution/api.py)

| 方法 | 路径                                     | 行为                                                   |
| ---- | ---------------------------------------- | ------------------------------------------------------ |
| GET  | `/api/talents`                           | 六名员工的当前版本概览                                 |
| GET  | `/api/talents/{talent}`                  | 详情：版本、经验、提案、评估、审计、回归用例与验收阈值 |
| GET  | `/api/talents/{talent}/versions`         | 版本列表                                               |
| GET  | `/api/talents/{talent}/lessons`          | 该员工的经验                                           |
| POST | `/api/talents/{talent}/diagnose`         | 固定回归集诊断，生成 verified 经验                     |
| POST | `/api/talents/{talent}/rollback`         | `{"version": n, "reason": "..."}`                      |
| GET  | `/api/lessons`                           | 全部经验（可按 talent 过滤）                           |
| POST | `/api/lessons/{id}/verify`               | `{"verification": "证据"}`，candidate → verified       |
| POST | `/api/lessons/{id}/reject`               | candidate → rejected                                   |
| POST | `/api/tasks/{task_id}/lessons`           | 从任务产物提取经验；仅终态任务                         |
| GET  | `/api/evolution/proposals`               | 提案列表（可按 talent/状态过滤）                       |
| POST | `/api/evolution/proposals`               | `{"talent": "...", "lesson_ids": [...]}`               |
| GET  | `/api/evolution/proposals/{id}`          | 单个提案                                               |
| POST | `/api/evolution/proposals/{id}/evaluate` | 跑固定回归评估                                         |
| POST | `/api/evolution/proposals/{id}/approve`  | 评估通过后批准并启用                                   |
| POST | `/api/evolution/proposals/{id}/reject`   | 拒绝提案与候选版本                                     |
| GET  | `/api/evolution/evaluations/{id}`        | 评估报告                                               |

异常映射：不存在 → 404；状态冲突/不可启用 → 409；非法变更 → 400；权限类问题 → 403（当前无用户体系，预留）。

## 11. 前端 Talent 面板

新增右侧第 5 个标签 `Talent`（[frontend/talent.js](file:///Users/lmliyascarlet/Desktop/项目/OneManCompany/OneGameStudio/frontend/talent.js)）：

- 员工列表：名称、角色、当前启用版本。
- 详情：当前版本 prompt 与 checklist、版本历史（可回滚）、经验库（验证/拒绝）、提案卡（评估指标 + 验收条目 + 批准/拒绝）、启用审计。
- 操作按钮：诊断、生成提案（自动使用未被占用的 verified 经验）、从当前任务提取经验、评估、批准、回滚。
- 评估卡的「引擎」「Token 来源」如实显示，`mock` 不会被渲染成真实评测。

## 12. 设计理由与限制

设计理由：

- **规则型提案只追加 checklist、不改写 prompt**：来源可追溯、token 增长可控，且提示词级改写需要真实模型评估，本阶段不伪造。
- **验收阈值写死**：避免「先看结果再调标准」。
- **诊断即证据**：回归漏检是可重复的确定性事实，比模型主观反思更适合作为 verified 经验。
- **版本文件只读 + 指针切换**：回滚只是移动指针，不需要复制内容，也不会丢历史。

当前限制：

1. `live` 评估引擎未接入，真实模型下的进化效果尚未验证。
2. Mock 判定基于关键词覆盖，只能验证「清单是否覆盖验证点」，不能证明模型真的会执行。
3. 提案生成是规则型（拼接 checklist），不支持自动改写提示词。
4. 没有独立的 Project/Run 实体，经验来源用 `task_id` 近似。
5. `active.json` 的审计为追加数组，暂无归档策略。
6. 前端 Talent 面板尚未做浏览器点击级自动化测试，只通过 `node --check` 与 HTTP 接口验证。
