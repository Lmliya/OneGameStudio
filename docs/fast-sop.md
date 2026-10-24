# FAST SOP：极速但不关闭测试

> 版本：v0.9（阶段 9）
> 本文描述已实现的 FAST 规则、跳过项与绝不跳过项，以及实测调用次数。

## 1. 适用边界

FAST 面向**短句、局部、目标明确**的修改，例如：

- 「把游戏背景颜色改成蓝色」
- 「把蛇移动速度调快一点」
- 「按钮文字换成中文」

不适用：

- 新游戏从零开发（走 BALANCED）
- 玩法创新、新机制、历史版本分支（走 CREATIVE）
- 需求本身含糊，需要先澄清玩法

## 2. 流程

```
CEO（用户需求）
   ↓
COO（PRD + 决策占位）
   ↓
Engineer（编码 / 修复）
   ↓
机械门禁 + AI Reviewer（完整执行）
   ↓
新版本（REVIEWING → COMPLETED）
```

FAST 不调用 Creative、Delivery、Marketer。

## 3. 自动选择规则

`backend/workflow/sop.py::select_sop`，优先级从高到低：

| 条件                                   | 结果     | 记录原因示例                           |
| -------------------------------------- | -------- | -------------------------------------- |
| 用户手动指定 `sop_mode`                | 该模式   | 「用户手动选择 FAST」                  |
| 带 `source_version_id`                 | CREATIVE | 「基于历史版本 {id} 创建创新玩法分支」 |
| 需求包含创新关键词（玩法/创新/机制等） | CREATIVE | 「需求包含创新玩法关键词…」            |
| 需求长度 ≤ 40 字且包含局部修改关键词   | FAST     | 「需求为短句局部修改，适用极速流程」   |
| 其他                                   | BALANCED | 「常规游戏开发需求，走标准评审流程」   |

- **手动选择永远优先**，自动规则不会覆盖用户。
- 每个自动选择都把可读原因写入 `TaskRecord.sop_reason` 与 `sop.selected` 事件。
- 模型无权选择或跳过 SOP；SOP 由 Python 在 Run 开始时确定。
- 模型也无权跳过审查：FAST 仍然执行机械门禁与 AI Reviewer。

## 4. 跳过与绝不跳过

| 步骤                     | FAST                               |
| ------------------------ | ---------------------------------- |
| Creative / Delivery 冲突 | 跳过                               |
| COO 冲突裁决             | 跳过（`conflict_decision = null`） |
| Engineer 编码            | 执行                               |
| 机械门禁（真实浏览器）   | **执行**                           |
| AI Reviewer              | **执行**                           |
| 修复循环（最多 2 轮）    | **执行**                           |
| Marketer 营销            | 跳过                               |
| 不可变版本记录           | **执行**                           |
| 预算检查与事件留痕       | **执行**                           |

FAST 的「快」来自少调用角色，不是少做验证。

## 5. 极速优化手段（已实现）

| 手段                 | 实现                                                                            |
| -------------------- | ------------------------------------------------------------------------------- |
| 非必要角色不调用     | FAST 只调用 COO / Engineer / Reviewer                                           |
| 适用时并行           | BALANCED 双总监并行；FAST 无并行角色                                            |
| 限制输出长度         | 顾问意见 `OPINION_MAX_OUTPUT_TOKENS=600`；代码仍用全局 `MAX_OUTPUT_TOKENS`      |
| 避免重复上下文       | 冲突上下文只拼接需求 + 必要产物，不重复整段历史                                 |
| 优先增量修改历史版本 | 带 `source_version_id` 时 Engineer 上下文注入父 HTML 并明确「历史版本参考代码」 |
| 保留必要回归测试     | 门禁 + Reviewer + 修复循环完全不跳过                                            |
| 设置模型超时         | `REQUEST_TIMEOUT_SECONDS`（默认 30s），超时不重试                               |
| 控制预算             | 单任务预算、70% 降级轻量模型、100% 阻断、并发上限 2                             |
| 记录实际执行时间     | `TaskRecord.metrics.elapsed_ms`、`model_calls`、`parallel_wall_ms`              |

## 6. 实测调用次数

### 6.1 测试环境（固定脚本化供应商）

`tests/test_sop.py::test_sop_call_count_comparison` 记录同一环境下的确定事实：

| 场景                       | SOP      | 模型调用次数 | 产物                                                  |
| -------------------------- | -------- | ------------ | ----------------------------------------------------- |
| 把背景颜色改成蓝色         | FAST     | **3**        | `prd.md`、`index.html`、`gate.json`、`review.json`    |
| 开发一个经典贪吃蛇小游戏   | BALANCED | **6**        | 上述 + 两份意见 + `conflict_decision.json` + 营销素材 |
| 从历史版本创建创新玩法分支 | CREATIVE | **7**        | BALANCED 产物 + 修订留档，产物同上                    |

测试里的门禁被替换为确定性桩，Reviewer 首轮即 PASS，所以没有修复轮。

### 6.2 真实 Mock 服务端（浏览器手工验收）

在 `MOCK_MODE=true`、`STAGE_MIN_SECONDS=6` 下通过 HTTP 实际运行的三个任务：

| 场景                       | SOP      | 实际状态  | 调用次数 | 实际耗时 | 并行墙钟 |
| -------------------------- | -------- | --------- | -------- | -------- | -------- |
| 把游戏背景颜色改成蓝色     | FAST     | completed | 5        | 38.2 s   | 0 ms     |
| 开发一个经典贪吃蛇小游戏   | BALANCED | completed | 8        | 50.4 s   | 10 ms    |
| 从历史版本创建创新玩法分支 | CREATIVE | completed | 9        | 62.4 s   | 0 ms     |

差异来自 Mock Reviewer 的设计：服务端 Mock 首轮返回 `ITERATE`，因此会多出「Engineer 修复 + Reviewer 复审」两次调用；测试桩则首轮 PASS。**两组数据都真实记录，不能混用。**

**不要预设 FAST 一定更快。** Mock 与脚本化供应商没有真实网络延迟，耗时主要来自 `STAGE_MIN_SECONDS=6` 的阶段补足与门禁，只能证明指标被记录、流程可完成；真实耗时取决于模型、网络、需求复杂度与修复轮数。可以确定的是调用次数与跳过的阶段。

CREATIVE 的 `parallel_wall_ms = 0` 是设计使然：提案 → 挑战 → 修订必须顺序执行，不能并行。

## 7. 示例

### 7.1 自动进入 FAST

需求：`把游戏背景颜色改成蓝色`

- 长度 ≤ 40 字，命中局部修改关键词 → FAST
- 事件：`sop.selected {mode:"fast", reason:"需求为短句局部修改，适用极速流程"}`
- 不生成 `creative_proposal.json` / `delivery_assessment.json` / `marketing_kit.*`
- Reviewer 与门禁照常执行
- 版本记录：`sop_mode=fast`，双方 Talent 版本为 `null`

### 7.2 手动锁定 BALANCED

页面顶部选择 `BALANCED` 后提交任何需求：

- 即使需求很短，也不会自动降级为 FAST
- 事件 `sop.selected.manual = true`
- 两名总监并行、COO 必须给出裁决

### 7.3 从历史版本创建 CREATIVE 分支

在「来源版本 ID」填入某个 `final_version_id`：

- 自动选择 CREATIVE，原因包含父版本 ID
- 父版本文件只复制不改写，SHA-256 写入新任务与版本记录
- Delivery 判定 `risky` / `infeasible` 时，Creative 只修订一次

## 8. 边界与风险

1. 自动关键词规则是启发式，短句也可被手动覆盖；规则改动需同步测试。
2. FAST 跳过营销是产品决定：营销阶段只有在 BALANCED / CREATIVE 且审查 PASS 后运行。
3. 并发上限调到 2 会扩大预算超额窗口（最坏多一次顾问调用）。
4. Mock 的耗时、token 与费用均为估算，不能当作真实模型性能。
5. 预算耗尽时任务 `failed`，但已生成产物全部保留。

## 9. 验收清单

- [x] 手动 FAST / BALANCED / CREATIVE 可提交
- [x] 自动选择记录原因
- [x] FAST 不调用总监与营销
- [x] FAST 不跳过门禁、Reviewer 与修复循环
- [x] 版本记录包含 `sop_mode`、`sop_reason`、`source_version_id`、`run_id`
- [x] 历史版本不可覆盖
- [x] 调用次数与耗时写入 `TaskRecord.metrics`
