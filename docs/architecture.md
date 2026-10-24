# OneGameStudio 架构说明

> 版本：v0.5（阶段 4：Vibe Marketing）
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
Review   = Mechanical Gate + AI Reviewer
```

## 3. 分层结构

```
frontend/            纯静态页面，无构建链
backend/
    main.py          FastAPI：/api/health、/api/tasks 系列
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

## 8. API

| 方法 | 路径                             | 行为                                    |
| ---- | -------------------------------- | --------------------------------------- |
| GET  | `/api/health`                    | 返回运行模式                            |
| POST | `/api/tasks`                     | 202，后台执行；同需求运行中任务返回 409 |
| GET  | `/api/tasks/{task_id}`           | 任务状态与事件                          |
| GET  | `/api/tasks/{task_id}/artifacts` | 产物文件名到内容的映射                  |

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

## 10. Mini-6 落位情况

| 能力          | 当前状态                                         |
| ------------- | ------------------------------------------------ |
| Task Contract | 已实现：任务记录 + 四类输出契约                  |
| Tool Policy   | 配置层白名单；运行时拦截待后续阶段               |
| Quality Gate  | 已实现双层：Playwright 机械门禁 + AI 审查        |
| Recovery      | 已实现有限重试（`max_fix_rounds`）+ 版本快照     |
| Budget Guard  | `Vessel` 实例内累计熔断，同一任务共用同一 Vessel |
| Event Trace   | 状态、审查拒绝、修复请求均写入 `task.json`       |

## 11. 运行依赖

- Python 3.12+ / uv / FastAPI / Pydantic / PyYAML / pytest
- Playwright（运行时）：优先自带 Chromium，失败时回退系统 Chrome
- 前端原生 HTML/CSS/JS，无 React/Vue/构建工具
- 不使用 LangChain/LangGraph、Redis、PostgreSQL、Docker
