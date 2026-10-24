# 双角色冲突协作协议（Conflict Gate）

> 版本：v0.9（阶段 9）
> 本文描述**已实现**的冲突协作流程与边界。未实现内容明确标注。

## 1. 为什么需要冲突协作

四员工串行流程里，COO 同时承担「想创意」和「控成本」两种互相拉扯的目标，结果往往是创意被悄悄折中，或者复杂度被悄悄放大。

阶段 9 把这两个目标拆给两名独立员工：

| 员工              | Talent id  | 核心问题                       | 输出契约              |
| ----------------- | ---------- | ------------------------------ | --------------------- |
| Creative Director | `creative` | 这个游戏为什么值得玩家体验？   | `CreativeProposal`    |
| Delivery Director | `delivery` | 怎样以最小可行成本稳定交付？   | `DeliveryAssessment`  |

COO 不再自己扮演两个角色，而是**汇总双方意见并做最终裁决**。

## 2. 角色契约

两名员工复用现有 `Employee = Talent + Vessel`，没有新增任何模型执行器。

### 2.1 Creative Director

`talents/creative.yaml`：

| 字段            | 值                                                            |
| --------------- | ------------------------------------------------------------- |
| `output_schema` | `creative_proposal`                                           |
| `model`         | `null`（由 Vessel 使用全局模型）                              |
| `allowed_tools` | `read_requirement`、`read_prd`、`read_game`、`write_creative` |

结构化输出 `CreativeProposal`：

| 字段           | 类型                     | 含义               |
| -------------- | ------------------------ | ------------------ |
| `innovation`   | string（非空）           | 最重要的创新建议   |
| `player_value` | string（非空）           | 对玩家的价值       |
| `complexity`   | `low / medium / high`    | 实现复杂度         |
| `priority`     | `high / medium / low`    | 优先级             |
| `rationale`    | string（非空）           | 依据               |

### 2.2 Delivery Director

`talents/delivery.yaml`：

| 字段            | 值                                                            |
| --------------- | ------------------------------------------------------------- |
| `output_schema` | `delivery_assessment`                                         |
| `model`         | `null`                                                        |
| `allowed_tools` | `read_requirement`、`read_prd`、`write_delivery`              |

结构化输出 `DeliveryAssessment`：

| 字段             | 类型                          | 含义         |
| ---------------- | ----------------------------- | ------------ |
| `risk`           | string（非空）                | 最大交付风险 |
| `feasibility`    | `feasible / risky / infeasible` | 可行性判断   |
| `simplification` | string（非空）                | 简化建议     |
| `priority`       | `high / medium / low`         | 优先级       |
| `rationale`      | string（非空）                | 依据         |

### 2.3 不允许为了戏剧效果争论

两份 YAML 的 checklist 都写死：

- 不得为了戏剧效果刻意反对；认同时必须明确说明。
- Delivery 在创意可交付时直接判定 `feasible`，不需要制造分歧。
- 不得臆造未经验证的用户数据、已实现功能或下载量。
- 不得建议删除必要测试或绕过质量门禁。

冲突只应来自**目标差异**，不是表演。

## 3. Conflict Gate 流程

```
用户需求
   ↓
Creative 与 Delivery 并行提出意见（BALANCED）
   ↓
COO 汇总双方观点
   ↓
COO 输出 conflict_decision：adopt / simplify / reject
   ↓
Engineer 执行
```

### 3.1 决策契约

`GamePRD` 新增可选字段 `conflict_decision`：

| 字段            | 类型                                  | 含义             |
| --------------- | ------------------------------------- | ---------------- |
| `decision`      | `adopt / simplify / reject`           | 采用、简化或拒绝 |
| `summary`       | string（非空）                        | 双方观点汇总     |
| `rationale`     | string（非空）                        | 决策理由（必填） |
| `adopted_from`  | `creative / delivery / both / neither` | 采纳来源         |

引擎在**收到意见却没有决策**时直接抛 `StageExecutionError`，任务失败，不会静默进入编码。

### 3.2 决策落盘与事件

| 产物                         | 内容                                     |
| ---------------------------- | ---------------------------------------- |
| `creative_proposal.json`     | Creative 结构化提案（修订后为最终版）    |
| `delivery_assessment.json`   | Delivery 结构化判断                      |
| `conflict_decision.json`     | COO 裁决（含理由）                       |
| `history/creative_proposal.round1.json` | CREATIVE 修订前的提案留档 |

三个事件：

| 事件               | 触发点                 | `data` 关键字段                                                     |
| ------------------ | ---------------------- | ------------------------------------------------------------------- |
| `sop.selected`     | 每次 Run 开始          | `mode`、`reason`、`manual`、`source_version_id`                     |
| `conflict.opinion` | 每份意见落盘后         | `role`、`round`、`proposal` / `assessment`（真实结构化输出）        |
| `conflict.resolved`| COO 决策落盘后         | `decision`、`sop_mode`、`revision_rounds`、`parallel_wall_ms`、双方 Talent 版本 |

前端像素办公室的气泡文本直接取 `conflict.opinion` / `conflict.resolved` 的 `message`，不额外生成文案。

## 4. 有限讨论

| 限制                             | 实现                                                                 |
| -------------------------------- | -------------------------------------------------------------------- |
| 每个角色默认一轮意见             | BALANCED：每名总监恰好一次调用                                       |
| CREATIVE 最多一轮额外修订        | 仅当 `delivery.feasibility != "feasible"`，Creative 针对挑战修订一次 |
| 不允许无限讨论                   | 修订轮数固定为 `0` 或 `1`，写入 `conflict.resolved.data.revision_rounds` |
| 不允许绕过质量门禁               | 冲突阶段只产出建议；`gate.json` / `review.json` 流程完全不变         |
| 用户明确要求优先                 | COO 提示词与 checklist 写死「用户明确要求优先于任何角色建议」        |
| 记录完整决策                     | `conflict_decision.json` + 事件 + `GameVersion.conflict_decision`     |

CREATIVE 的顺序执行（提案 → 挑战 → 修订）是刻意设计：挑战需要看到提案内容，不能并行。

## 5. 并行与一致性

BALANCED 使用 `asyncio.gather(..., return_exceptions=True)` 真实并行：

- `Vessel` 的信号量默认 `MAX_CONCURRENT_CALLS=2`，否则两名总监会被串行化。
- 并行阶段只执行模型调用（`_execute`），**不写 `TaskRecord`**。
- `gather` 结束后串行提交结果（`_commit_result` + 落盘 + 事件），避免并发写坏 `task.json`。
- 任一方失败：已成功的一方产物先落盘并保留，随后任务 `failed`，错误原文写入 `error`。
- 测试用 `TrackingProvider` 观测到 `max_active == 2`，证明不是伪并行。

## 6. 失败与降级

| 情况                           | 行为                                                       |
| ------------------------------ | ---------------------------------------------------------- |
| Creative 调用失败（BALANCED）  | 保留 Delivery 已产出结果；任务 `failed`，原因是首个异常     |
| Delivery 调用失败（BALANCED）  | 保留 Creative 已产出结果；任务 `failed`                    |
| COO 未输出 `conflict_decision` | `StageExecutionError`，任务 `failed`，不进入编码           |
| 预算耗尽                       | 调用前拦截，已生成意见保留；两名总监各计一次 `blocked_calls` |
| 用户取消                       | 安全点退出，已生成意见与父版本全部保留                     |
| 输出不符合契约                 | Pydantic 校验失败 → 任务 `failed`，错误写事件              |

## 7. 版本记录

每个完成的任务写入不可变 `GameVersion`（`output/{task_id}/versions/{task_id}-vN.json` 与 `.html`）：

| 字段                       | 来源                                         |
| -------------------------- | -------------------------------------------- |
| `sop_mode`                 | 本次 Run 的 SOP                              |
| `sop_reason`               | 手动选择或自动规则原因                       |
| `conflict_decision`        | COO 裁决（FAST 为 `null`）                   |
| `creative_talent_version`  | 本次实际使用的 Creative Talent 版本          |
| `delivery_talent_version`  | 本次实际使用的 Delivery Talent 版本          |
| `source_version_id`        | 分支来源版本（非分支任务为 `null`）          |
| `source_sha256`            | 父版本 HTML 哈希                             |
| `run_id`                   | 本次 Run 标识                                |
| `parent_version_id`        | 同任务上一版本（首个版本为 `null`）          |

历史版本不可覆盖：目标文件存在即拒绝写入；跨任务分支只**复制**父 HTML 到新任务 `source/`，父版本哈希不变。

## 8. 测试证据

`tests/test_sop.py`：

- 场景 B 断言 `provider.max_active == 2`、`parallel_wall_ms > 0`、`model_calls == 6`。
- 场景 C 断言 Creative 调用恰好 2 次（提案 + 1 次修订）、`revision_rounds == 1`、父版本 SHA-256 不变。
- 异常恢复：Delivery 失败后 `creative_proposal.json` 保留、`prd.md` 不存在、任务 `failed`。
- 权限：两名总监无法使用 `write_game` / `write_marketing`；YAML 声明越权工具会被加载期拒绝。

## 9. 当前限制

1. 冲突决策只由 COO 输出，没有独立的第三方裁决 Agent。
2. `revision_rounds` 固定上限为 1，不可配置。
3. 并行调高到 2 会扩大预算超额窗口；预算检查在锁内，最坏多出一次顾问调用。
4. Mock 模式的结构化意见是确定性模板，不能代表真实模型的观点质量。
5. 事件与预算仍是进程内状态，多 worker 部署不适用。
