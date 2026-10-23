# OneGameStudio 架构说明

> 版本：v0.3（阶段 2：四 Agent 工作流）
> 本文只描述已实现的部分，未实现的内容标注为"规划中"。

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
```

- **Talent**：纯数据，`talents/*.yaml`。
- **Vessel**：执行一个员工，负责模型调用、解析、校验、计量。
- **WorkflowEngine**：确定性编排，负责状态推进与回退循环。
- **TaskStore**：持久化到 `output/{task_id}/`。

## 3. 分层结构

```
frontend/            纯静态页面，无构建链
backend/
    main.py          FastAPI：/api/health、/api/tasks 系列
    config.py        全局配置（LLM_*）
    schemas.py       四类输出契约
    talents.py       Talent 加载与工具白名单校验
    store.py         任务持久化
    models/
        contract.py  TaskStatus / TaskRecord
        talent.py    TalentSpec
        events.py    TraceEvent
    core/vessel.py   员工执行容器
    providers/       base / mock / openai
    workflow/
        state_machine.py  合法迁移表
        engine.py         编排与质量门禁
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

| 当前状态                                   | 允许迁移                                           |
| ------------------------------------------ | -------------------------------------------------- |
| `pending`                                  | `planning`, `failed`                               |
| `planning`                                 | `coding`, `failed`                                 |
| `coding`                                   | `reviewing`, `failed`                              |
| `reviewing`                                | `fixing`, `marketing`, `needs_attention`, `failed` |
| `fixing`                                   | `reviewing`, `needs_attention`, `failed`           |
| `marketing`                                | `completed`, `failed`                              |
| `completed` / `failed` / `needs_attention` | 终态                                               |

迁移只经由 `assert_transition` 校验。模型无法改变状态，只能提供文本。

## 5. 一次任务的执行流程

```
WorkflowEngine.start(task_id)
   ├─ planning   : COO        → prd.md
   ├─ coding     : Engineer   → index.html + 确定性质量门禁
   ├─ reviewing  : Reviewer   → review.json
   │     ├─ passed=true  → marketing
   │     └─ passed=false → fixing（Engineer 依据 issues 修改）
   │                       → reviewing（重新审查）
   │                       → 超过 max_fix_rounds 则 needs_attention
   └─ marketing  : Marketer   → marketing_kit.md → completed
```

每次状态变更都会向 `task.json` 的 `events` 追加一条 `state_changed`。

## 6. 产物

`output/{task_id}/` 下固定产出：

| 文件               | 产出者   | 内容                        |
| ------------------ | -------- | --------------------------- |
| `prd.md`           | COO      | 结构化 PRD 的 Markdown 渲染 |
| `index.html`       | Engineer | 单文件游戏                  |
| `review.json`      | Reviewer | 得分、结论、问题清单        |
| `marketing_kit.md` | Marketer | 营销素材                    |
| `task.json`        | 引擎     | 状态、事件、产物索引        |

写入策略：只新增不删除。任一阶段失败，已产出文件全部保留。

## 7. API

| 方法 | 路径                             | 行为                                            |
| ---- | -------------------------------- | ----------------------------------------------- |
| GET  | `/api/health`                    | 返回运行模式                                    |
| POST | `/api/tasks`                     | 202，创建并在后台执行；同需求运行中任务返回 409 |
| GET  | `/api/tasks/{task_id}`           | 任务状态与事件                                  |
| GET  | `/api/tasks/{task_id}/artifacts` | 产物文件名到内容的映射                          |

后台执行使用 `asyncio.create_task`，HTTP 请求不等待工作流完成。

## 8. 规则落位

| 规则                     | 实现                                          |
| ------------------------ | --------------------------------------------- |
| COO 必须先出 PRD         | 状态机不允许 `pending → coding`               |
| Engineer 依据 PRD        | `engineer` 的上下文包含完整 PRD JSON          |
| Reviewer 不改代码        | 引擎只落盘 `review.json`                      |
| 审查失败由 Engineer 修改 | `fixing` 状态传入 issues 后重新调用 Engineer  |
| 默认最多两次修复         | `max_fix_rounds = 2`                          |
| 上限后终止               | 进入 `needs_attention`                        |
| 通过门禁才进 Marketing   | `review.passed` 且 `game_quality_gate` 无问题 |
| Marketer 不改代码        | 只写 `marketing_kit.md`                       |
| 失败保留产物             | `TaskStore` 只写不删                          |
| 同任务不并发             | `WorkflowEngine._running` 集合                |
| 输入输出结构校验         | `Vessel._validate` + `OUTPUT_SCHEMAS`         |

## 9. 安全边界

- `allowed_tools` 在加载时与白名单求差集，未授权工具直接拒绝。
- 项目无 shell 执行入口；模型输出只作为 JSON 解析，从不执行。
- 生成的 HTML 视为不可信内容，只落盘到独立任务目录，不在服务进程内执行。
- API Key 只从服务端环境变量读取。

## 10. Mini-6 落位情况

| 能力          | 当前状态                                               |
| ------------- | ------------------------------------------------------ |
| Task Contract | 已实现：任务记录 + 四类输出契约                        |
| Tool Policy   | 配置层白名单；运行时拦截待后续阶段                     |
| Quality Gate  | 已实现最小确定性检查（空文件 / `<html>` / `<script>`） |
| Recovery      | 已实现有限重试（`max_fix_rounds`）                     |
| Budget Guard  | `Vessel` 实例内累计熔断，同一任务共用同一 Vessel       |
| Event Trace   | 事件写入 `task.json`，可查询但未做独立事件流           |

## 11. 技术选型约束

- Python 3.12+ / uv / FastAPI / Pydantic / PyYAML / pytest
- 前端原生 HTML/CSS/JS，无 React/Vue/构建工具
- 不使用 LangChain/LangGraph、Redis、PostgreSQL、Docker
