# OneGameStudio 开发交接文档

> 生成时间：2026-10-24（阶段 10 完成后更新）
> 仓库状态：分支 `main`，最新提交 `8058ab3 完成了最初版本`，已推送 `origin/main`（仓库为 private）；工作区仅有 `backend/providers/__init__.py` 一处未提交改动
> 本文描述的是**实际代码与实测结果**，未实现的功能统一放在「未完成模块」。

---

## 1. 项目简介

OneGameStudio 是一个轻量级「AI 游戏开发工作室」演示项目。

- 输入：CEO 的一句自然语言需求（如「做一个能计分的贪吃蛇小游戏」）。
- 过程：六名 AI 员工按 SOP（FAST / BALANCED / CREATIVE）协作，Python 状态机负责推进，模型无权改状态或跳过审查。
- 输出：可运行的**单文件 HTML5 游戏**、机械门禁报告、AI 审查报告、冲突决策、营销素材（JSON + Markdown）与不可变游戏版本。
- 展示：浏览器里的六人像素办公室 + 右侧驾驶舱，实时显示员工状态、对立观点、COO 裁决、SOP 模式与事件流。

当前已有能力：三种 SOP、双总监冲突协作、完整工作流、双层审查与自动修复、隔离预览、实时事件推送、六项运行保障机制（Mini-6 Harness）、AI 员工自进化、不可变游戏版本与历史分支。

---

## 2. 实际技术架构

### 2.1 技术栈（均已在 `pyproject.toml` 中声明）

| 层       | 技术                                 | 说明                                                                                                                   |
| -------- | ------------------------------------ | ---------------------------------------------------------------------------------------------------------------------- |
| 运行时   | Python >= 3.12（本机 3.13.9）        | 包管理用 `uv`（本机 0.13.4）                                                                                           |
| Web      | FastAPI + Uvicorn                    | API、WebSocket、静态文件托管                                                                                           |
| 数据模型 | Pydantic v2 + pydantic-settings      | 输入输出契约、任务记录、配置                                                                                           |
| 配置     | `.env` + 环境变量                    | 全部可调参数集中在 [config.py](file:///Users/lmliyascarlet/Desktop/项目/OneManCompany/OneGameStudio/backend/config.py) |
| 模型调用 | OpenAI 兼容 HTTP（httpx）            | 真实模式；Mock 模式不联网                                                                                              |
| 机械门禁 | Playwright（Chromium / 系统 Chrome） | 真实加载、按键、点击、状态读取                                                                                         |
| 前端     | 原生 HTML + CSS + JS + Canvas 2D     | 无框架、无构建步骤                                                                                                     |
| 测试     | pytest + pytest-asyncio              | 119 个用例                                                                                                             |

Node.js（本机 v25.8.2）**不参与服务运行**：前端由 FastAPI 直接托管；Node 仅用于 `cli/bin.js` 启动脚本与 npm 包入口。

### 2.2 核心公式

```
Employee = Talent（YAML 数据）+ Vessel（运行时容器）
Task     = WorkflowEngine（状态机与编排）+ TaskStore（落盘）
Review   = Mechanical Gate（确定性）+ AI Reviewer（语义）
Conflict = Creative ∥ Delivery（意见）+ COO（裁决）
SOP      = select_sop（Python 规则）+ 按模式调用角色
Version  = 不可变 GameVersion（含 SOP / 裁决 / Talent 版本 / 父版本哈希）
Realtime = EventBus（进程内）+ WebSocket
```

### 2.3 模块地图

| 路径                                | 职责                                                                                               |
| ----------------------------------- | -------------------------------------------------------------------------------------------------- |
| `backend/main.py`                   | FastAPI 入口：任务 API、取消、产物读取、WebSocket、隔离预览、静态托管                              |
| `backend/config.py`                 | 全局 `Settings`，环境变量映射                                                                      |
| `backend/models/contract.py`        | `TaskStatus`（10 态）、`TERMINAL_STATUSES`、`TaskRecord`（含 SOP/版本/指标）、`TaskCreateRequest`  |
| `backend/models/events.py`          | `EventType`、`AgentStatus`、`TokenUsage`、`TraceEvent`、`Tracer`                                   |
| `backend/models/sop.py`             | `SOPMode`、`ConflictDecision`、`RunMetrics`                                                        |
| `backend/models/version.py`         | 不可变 `GameVersion`                                                                               |
| `backend/models/talent.py`          | `TalentSpec`（id/name/role/system_prompt/model/allowed_tools/output_schema）                       |
| `backend/schemas.py`                | 六个输出契约 + 门禁报告契约 + `OUTPUT_SCHEMAS` 注册表                                              |
| `backend/talents.py`                | 加载并校验 `talents/*.yaml`（工具、schema、角色授权）                                              |
| `backend/tools.py`                  | Harness 2：12 个工具显式注册表、`ROLE_TOOLS`、加载期与运行时双重校验                               |
| `backend/budget.py`                 | Harness 5：`TaskBudget`、`BudgetGuard`、价格表解析                                                 |
| `backend/evolution/`                | 阶段 8：Talent 版本库、经验库、提案、固定回归评估、审批/回滚 API                                   |
| `backend/core/vessel.py`            | 员工执行容器：预算检查、限并发、有限重试、契约校验、输出上限、调用轨迹                             |
| `backend/providers/base.py`         | `BaseProvider` / `ProviderResponse` / `usage_source`                                               |
| `backend/providers/mock.py`         | 离线确定性 Mock（游戏 HTML、审查、顾问意见与裁决）                                                 |
| `backend/providers/openai.py`       | OpenAI 兼容真实调用，支持 `max_tokens`                                                             |
| `backend/gate/mechanical.py`        | Harness 3：Playwright 机械门禁与 PRD 验收映射                                                      |
| `backend/workflow/state_machine.py` | `ALLOWED_TRANSITIONS` + `assert_transition`（含 FAST 直达完成）                                    |
| `backend/workflow/sop.py`           | SOP 自动选择与原因                                                                                 |
| `backend/workflow/engine.py`        | 编排：SOP / 冲突阶段 / 修复循环 / 取消 / 版本 / 指标 / 事件落盘与广播                              |
| `backend/store.py`                  | 任务持久化：`output/{task_id}/`、快照、不可变版本、分支复制、原子写                                |
| `backend/bus.py`                    | 进程内 `EventBus`，每任务 `asyncio.Queue(256)`，满则丢最旧                                         |
| `backend/marketing.py`              | 营销 Markdown 渲染 + 编造数据正则拦截                                                              |
| `frontend/index.html`               | 驾驶舱骨架（顶部 / 左办公室 / 右六标签 / 底部事件条）                                              |
| `frontend/style.css`                | 像素风：硬边框、阶梯阴影、无圆角、响应式单列                                                       |
| `frontend/office.js`                | Canvas 2D 像素办公室，6 员工动画与观点气泡由事件驱动                                               |
| `frontend/app.js`                   | WebSocket、快照恢复、SOP 选择、Studio 面板、产物渲染、版本切换、隔离预览                           |
| `frontend/talent.js`                | Employee 面板：6 个职位/角色、岗位启用切换、角色基础信息与已完成任务（任务 ID + 名称）             |
| `talents/*.yaml`                    | COO / Creative / Delivery / Engineer / Reviewer / Marketer 六份在岗配置 + Backup Engineer 备用配置 |
| `cli/bin.js`                        | 本地启动 CLI：环境检查、Demo/Live 模式、端口与浏览器打开                                           |
| `package.json`                      | npm 包 `onegamestudio`（`private: true`，尚未发布）                                                |
| `Dockerfile` / `render.yaml`        | Python 3.12 + uv + Chromium；Render 部署含 `/data` 持久化磁盘                                      |
| `demo/`                             | 预验证历史任务与 Talent 快照，Demo 模式只读                                                        |
| `tests/*.py`                        | 11 个测试文件，119 个用例                                                                          |

### 2.4 数据流

```
POST /api/tasks
   └─ TaskStore.create() → output/{task_id}/task.json（status=pending）
   └─ asyncio 后台任务 → WorkflowEngine.start()

WorkflowEngine.start()
   选择 SOP（手动优先 / 自动规则）→ sop.selected
   pending → planning
        FAST：COO → prd.md
        BALANCED：Creative ∥ Delivery → COO 裁决 → prd.md + conflict_decision.json
        CREATIVE：Creative → Delivery 挑战 →（≤1 轮修订）→ COO 裁决 → 同上
           → coding    Engineer → index.html（分支任务注入父版本代码）
                       ↓
                 Mechanical Gate（Playwright）→ gate.json
                       ↓
           → reviewing Reviewer → review.json
                       ↓ ITERATE
           → fixing    Engineer（先快照 history/index.v{n}.html）
                       ↓
                 重新门禁 + 重新审查（最多 2 轮）
                       ↓ PASS
        FAST：→ completed（跳过营销）
        其他：→ marketing Marketer → marketing_kit.json / marketing_kit.md → completed
                       ↓
            _finalize_version → versions/{task_id}-vN.json/.html（不可变）

每个状态变化 / 员工状态 / 工具调用 / 产物 / 冲突意见 / 预算：
   TraceEvent → 追加到 record.events → 写入 task.json → EventBus 广播 → WebSocket 推送

自进化（与任务流程解耦，通过 API / 前端 Talent 面板触发）：
   任务终态 → 提取经验 → 诊断漏检 → 提案 → 固定回归评估 → 用户批准 → active.json 切换
   WorkflowEngine 每次调用把实际版本写入 task.json.talent_versions
```

---

## 3. 已完成模块（有代码或测试可验证）

| 阶段 | 内容                                           | 验证方式                                                                                       |
| ---- | ---------------------------------------------- | ---------------------------------------------------------------------------------------------- |
| 1    | FastAPI 骨架、提交需求、返回 task_id           | `tests/test_api.py`                                                                            |
| 2    | Talent YAML + Vessel 执行 + Mock/真实 Provider | `tests/test_vessel.py`                                                                         |
| 3    | 机械门禁 + AI 审查 + 自动修复循环              | `tests/test_gate.py`、`tests/test_workflow.py`                                                 |
| 4    | Marketer 营销素材 + 真实性约束                 | `tests/test_workflow.py`、`backend/marketing.py`                                               |
| 5    | 像素办公室、驾驶舱、WebSocket、隔离预览        | `tests/test_api.py` + 浏览器手工验证                                                           |
| 6    | Mini-6 Harness（六项机制）                     | `tests/test_harness.py`、`docs/harness.md`                                                     |
| 8    | AI 员工自进化（版本/经验/提案/评估/审批/回滚） | `tests/test_evolution.py`、`docs/talent-evolution.md`                                          |
| 9    | 双角色冲突协作、三种 SOP、不可变版本与分支     | `tests/test_sop.py`、`tests/test_versions.py`、`docs/conflict-protocol.md`、`docs/fast-sop.md` |

### 3.1 AI 员工（六名在岗 + 一名备用）

| 员工              | Talent 文件                    | 角色       | 工具（授权表来源 `backend/tools.py`）                         | 输出契约                                     |
| ----------------- | ------------------------------ | ---------- | ------------------------------------------------------------- | -------------------------------------------- |
| COO               | `talents/coo.yaml`             | 需求分析   | `read_requirement`、`write_prd`、`write_decision`             | `prd` → `GamePRD`（含冲突裁决）              |
| Creative Director | `talents/creative.yaml`        | 创意总监   | `read_requirement`、`read_prd`、`read_game`、`write_creative` | `creative_proposal` → `CreativeProposal`     |
| Delivery Director | `talents/delivery.yaml`        | 交付总监   | `read_requirement`、`read_prd`、`write_delivery`              | `delivery_assessment` → `DeliveryAssessment` |
| Engineer          | `talents/engineer.yaml`        | 游戏开发   | `read_prd`、`write_game`、`read_review`                       | `game` → `GameArtifact`                      |
| Backup Engineer   | `talents/backup_engineer.yaml` | 备用工程师 | `read_prd`、`write_game`、`read_review`                       | `game` → `GameArtifact`                      |
| Reviewer          | `talents/reviewer.yaml`        | 质量审查   | `read_game`、`run_tests`、`write_review`                      | `review` → `ReviewReport`                    |
| Marketer          | `talents/marketer.yaml`        | 营销素材   | `read_prd`、`read_review`、`write_marketing`                  | `marketing` → `MarketingKit`                 |

- 员工数量：**6 名在岗 + 1 名备用（Backup Engineer）**；备用工程师与 Engineer 共用工程师岗位，不占像素办公室工位，也不改变当前 Run 的执行角色。
- Talent 的 `model` 目前全为 `null`，即统一使用 `LLM_MODEL`（Mock 模式下为 `mock`）。
- 工具在加载期（`talents.py`）与运行时（`engine._use_tool`）各校验一次；注册表拒绝 `shell/exec/subprocess/system/eval` 前缀的工具名。
- 两名总监复用同一 Vessel 执行器，支持独立提示词、结构化输出、工具权限、模型配置、Token 统计、Talent 版本化与后续自进化。

### 3.2 工作流

```
选择 SOP：手动优先 / source 分支 → CREATIVE / 创新关键词 → CREATIVE
          / 短句局部修改 → FAST / 其余 → BALANCED
pending → planning → coding → reviewing → [fixing → reviewing] × ≤2 → marketing → completed
                                  ↓          ↓                       ↓
                            needs_attention  failed                 failed
FAST：reviewing（PASS）→ completed（跳过 marketing）
任意非终态 → cancelled（用户取消）
```

- 状态迁移只经 `state_machine.assert_transition`，非法迁移抛 `InvalidTransitionError`。
- `reviewing → completed` 只允许 FAST 使用；`fixing → completed` 仍然禁止，避免绕过审查。
- 修复次数用尽 → `needs_attention`，并写入 `error` 文案。
- 终态：`completed / failed / needs_attention / cancelled`，不可再执行或取消。

### 3.3 双层审查与自动修复

1. **机械门禁**（[mechanical.py](file:///Users/lmliyascarlet/Desktop/项目/OneManCompany/OneGameStudio/backend/gate/mechanical.py)）
   - 真实 Chromium（失败回退系统 Chrome / `OGS_BROWSER_PATH`）加载 HTML。
   - 检查项：`html_structure`、`page_load`、`js_errors`、`network_isolation`、`game_area`、`restart_control`、`arrow_keys`、`score_updates`、`restart_after_gameover`、`prd_acceptance`、`gameplay`。
   - 无法确定性验证的项标 `unverified`，绝不写成 `pass`；`passed = 没有任何 fail`。
   - 网络隔离通过 `route.abort` 阻断非 `data:/about:/blob:` 请求，并记录 `blocked_requests`。
2. **AI Reviewer** 读取 PRD + 门禁报告 + 游戏代码，输出 `PASS / ITERATE`。
3. **后端裁决**：门禁 fail 时即使 AI 说 PASS 也强制改 `ITERATE`（`forced_by_gate=true`）；Reviewer 输出无法解析则任务 `failed`。
4. **修复循环**：默认最多 2 轮（`MAX_FIX_ROUNDS`），每轮修复前把 `index.html` 快照为 `history/index.v{n}.html`，门禁报告同步留档 `history/gate.v{n}.json`。

### 3.4 游戏版本管理（阶段 9 起）

- 每个完成的任务写入不可变 `GameVersion`：`output/{task_id}/versions/{task_id}-v{n}.json` 与同名 `.html`。
- 记录字段：`sop_mode`、`sop_reason`、`conflict_decision`、`creative_talent_version`、`delivery_talent_version`、`source_version_id`、`source_sha256`、`run_id`、`parent_version_id`、`artifact_path`。
- 版本号在同任务内 `max+1`；文件存在即拒绝覆盖，历史版本永不修改。
- 跨任务分支：`POST /api/tasks` 带 `source_version_id` 时，把父 HTML 复制到新任务 `source/{task_id}.html` 并记录 SHA-256，父版本哈希不变。
- 修复过程中的中间快照仍保留在 `history/index.v{n}.html`；`index.html` 始终是当前工作版本。
- 前端 Game 标签读取 `GET /api/tasks/{id}/history` 切换中间版本；Studio 标签读取 `/versions` 展示不可变版本。
- 预览 URL 带 `?t=时间戳` 防止 iframe 复用旧页面。

### 3.5 像素办公室与 WebSocket

- Canvas 逻辑尺寸 880×520，CSS 自适应（`object-fit: contain`）。
- 6 张桌子 + 6 名员工（背对观众坐姿，3 列 × 2 行）+ 任务牌 + 装饰（地毯、猫、书架、饮水机、落地灯、挂钟、海报、白板、植物、垃圾桶等）。
- 6 种员工状态：`idle / working / reviewing / fixing / completed / error`，**全部来自后端 `agent.status_changed` 事件**，前端没有计时器伪造进度。
- 冲突观点气泡只由 `conflict.opinion` / `conflict.resolved` 事件填充，不生成文案；Studio 标签展示提案、交付判断、COO 裁决、版本记录与指标。
- 同一时刻最多一名员工播放动画（`activeAgent`），播放顺序即实际工作流顺序；每阶段由后端 `STAGE_MIN_SECONDS`（默认 6 秒）保证时长。
- WebSocket `/ws/tasks/{task_id}`：首帧 `task.snapshot`（含完整 `TaskRecord` 与 `events`），之后推送增量事件，20 秒无事件发 `ping`。
- 前端断线重连：指数退避 1s → 2s → 4s → 8s 封顶；`localStorage` 键 `ogs_task` 记录最近任务，刷新后按快照恢复。
- `EventBus` 为进程内实现，每任务 `asyncio.Queue(256)`，满时丢弃最旧事件，避免慢消费者阻塞工作流。

### 3.6 隔离预览

- `GET /preview/{task_id}/{filename}` 仅允许 `index.html` 与 `history/index.v{n}.html`。
- `task_id` 正则 `^[0-9a-f]{6,32}$`；文件名白名单正则，双重防路径穿越。
- 响应头：严格 CSP（`default-src 'none'`、`connect-src 'none'`、`frame-ancestors 'self'` 等）+ `nosniff` + `no-store`。
- iframe `sandbox="allow-scripts"`（不含 `allow-same-origin`），游戏运行在 opaque origin，读不到主站点 DOM/Cookie/localStorage。

### 3.7 Mini-6 Harness（阶段 6，已完成）

| Harness         | 实现位置                                          | 要点                                                              |
| --------------- | ------------------------------------------------- | ----------------------------------------------------------------- |
| 1 Task Contract | `models/contract.py`、`workflow/state_machine.py` | Pydantic 强校验、10 态状态机、终态保护、错误分层                  |
| 2 Tool Policy   | `tools.py`、`talents.py`、`engine._use_tool`      | 9 个显式工具、角色授权、双重校验、无 shell 能力                   |
| 3 Quality Gate  | `gate/mechanical.py`、`engine._review`            | 机械断言 + AI 审查 + 后端强制裁决                                 |
| 4 Recovery      | `vessel.py`、`engine.cancel`                      | 异常重试（超时不重试）、取消、终态不可重跑、产物保留              |
| 5 Budget Guard  | `budget.py`、`vessel.py`                          | 单任务预算、70% 降级、100% 阻断、限并发、未知费用标记             |
| 6 Event Trace   | `models/events.py`、`engine._call`                | 统一字段 `model/duration_ms/token_usage/result/error`，3 类新事件 |

详细边界与验收证据见 [harness.md](file:///Users/lmliyascarlet/Desktop/项目/OneManCompany/OneGameStudio/docs/harness.md)。

### 3.8 AI 员工自进化（阶段 8）

完整说明见 [talent-evolution.md](file:///Users/lmliyascarlet/Desktop/项目/OneManCompany/OneGameStudio/docs/talent-evolution.md)。

- **版本库**：`output/evolution/talents/{name}/versions/v{n}.json` 只读；`active.json` 决定启用版本；启动时从 YAML 播种 v1，幂等。
- **经验库**：`candidate / verified / rejected`；`verified` 必须有可追溯证据；门禁失败自动生成 verified，审查问题生成 candidate。
- **提案**：只接受同员工的 verified 经验；只允许改 `prompt` / `checklist`；当前实现是规则型，prompt 不变、只追加 checklist。
- **评估**：四角色各有固定回归用例（Reviewer 5 条、其余各 4 条），阈值写死（检出率 ≥0.9、不低于基线、误报 ≤0.1、Token ≤2.0x）；`engine=mock` 明确标注模拟。
- **审批与回滚**：未评估或评估失败不能批准；启用时校验安全字段与基线一致；任意非候选版本可回滚并写审计。
- **运行时**：`Vessel` 使用启用版本，`TaskRecord.talent_versions` 记录每次 Run 实际使用的版本（如 `reviewer@v2`）。

### 3.9 双角色冲突与 SOP（阶段 9）

完整说明见 [conflict-protocol.md](conflict-protocol.md) 与 [fast-sop.md](fast-sop.md)。

- **SOP 选择**：`backend/workflow/sop.py`，手动选择优先；自动规则为 source 分支 / 创新关键词 → CREATIVE、短句局部修改 → FAST、其余 → BALANCED；原因写入 `TaskRecord.sop_reason` 与 `sop.selected` 事件。
- **BALANCED 并行**：Creative 与 Delivery 用 `asyncio.gather` 真实并行（`MAX_CONCURRENT_CALLS=2`）；只执行调用，结束后串行落盘与发事件，避免并发写坏 `task.json`。
- **CREATIVE 有限讨论**：Creative → Delivery（挑战上下文）→ 若 `feasibility != feasible` 则 Creative 修订恰好 1 轮，修订前提案留档。
- **COO 裁决**：必须输出 `conflict_decision`（adopt / simplify / reject + 理由）；缺失即 `StageExecutionError`，任务失败。
- **FAST 边界**：跳过双总监与 Marketer，但不跳过门禁、Reviewer、修复循环、预算与版本记录。
- **指标**：`TaskRecord.metrics` 记录 `elapsed_ms / model_calls / parallel_wall_ms`。
- **前端**：SOP 下拉、来源版本输入、Studio 标签、六人观点气泡；Mock 模式明确标注。

#### 3.11 Demo / Live 双模式与启动（阶段 10）

- `APP_MODE=demo`（默认）：读取 `demo/tasks` 的预验证历史任务；顶部状态栏的 DEMO 徽章明确标记；
  WebSocket 先发空事件快照，再按 `DEMO_REPLAY_MS` 回放历史事件；`DEMO_READ_ONLY=true` 时创建任务返回 403。
- `APP_MODE=live`：必须 `MOCK_MODE=false`、`LLM_MODEL`、服务端 `LLM_API_KEY` 同时存在，否则返回 503；
  `ACCESS_TOKEN` 非空时创建任务必须携带 `X-OGS-Token`，否则 401。
- 资源限制：单 IP 每分钟任务数、活跃任务上限、单任务预算、并发模型调用上限、请求超时。
- `cli/bin.js`：本地启动、`--check`、`--demo/--live`、端口与自动打开浏览器；npm 包未发布。
- 部署：`Dockerfile` + `render.yaml`，持久化 `/data`；说明见 `docs/deployment.md`。

### 3.10 配置项（真实存在）

见 [.env.example](file:///Users/lmliyascarlet/Desktop/项目/OneManCompany/OneGameStudio/.env.example)：`APP_MODE`、`DEMO_READ_ONLY`、`DEMO_DIR`、`ACCESS_TOKEN`、`TASK_RATE_LIMIT_PER_MINUTE`、`MAX_ACTIVE_TASKS`、`DEMO_REPLAY_MS`、`MOCK_MODE`、`LLM_BASE_URL`、`LLM_API_KEY`、`LLM_MODEL`、`REQUEST_TIMEOUT_SECONDS`、`STAGE_MIN_SECONDS`、`PROVIDER_MAX_RETRIES`、`PROVIDER_RETRY_BACKOFF_SECONDS`、`BUDGET_USD`、`BUDGET_SOFT_RATIO`、`LIGHT_MODEL`、`MAX_OUTPUT_TOKENS`、`OPINION_MAX_OUTPUT_TOKENS`（默认 600）、`MODEL_PRICES`、`MAX_CONCURRENT_CALLS`（默认 2，冲突阶段并行所需）；另有 `MAX_FIX_ROUNDS`、`TALENTS_DIR`、`OUTPUT_DIR`、`EVOLUTION_DIR`（代码默认值 `output/evolution`）。

---

## 4. 未完成模块（规划 / 不存在）

以下内容**当前代码中没有任何实现**，不要按已实现对待：

1. **真实模型评估（live 引擎）**：阶段 8 的自进化评估只实现 `engine=mock` 的确定性回归；`MOCK_MODE=false` 时服务层会明确报错，不会用模拟结果冒充真实评测。提示词自动改写也未实现（当前提案只追加 checklist）。
2. **独立第三方裁决 Agent**：冲突裁决只由 COO 输出；CREATIVE 的额外修订轮数固定为 1，不可配置。
3. **npx 启动与线上部署**：没有 `package.json`、没有容器化、没有反向代理/域名/TLS 配置，也没有多进程部署方案。
4. **Project / Run 领域模型**：代码里没有 `Project` 实体，只有 `TaskRecord`（一次需求即一个 task）与 `run_id` 字符串。多任务归组、项目级历史、跨任务统计均不存在。
5. **数据库与持久队列**：没有 SQLite/PostgreSQL/Redis；任务、版本与事件都在文件 + 内存中。
6. **成本对账**：没有供应商账单拉取与核对，只有「配置单价 × token 估算」。
7. **用户系统 / 权限 / 多租户**：API 无鉴权。
8. **前端端到端自动化测试**：仓库里没有 Playwright 前端 E2E 用例（门禁用的是后端 Playwright）。
9. **驾驶舱折叠按钮（手柄图标）**：该 UI 改动已在文件恢复时被撤销，当前界面**没有**折叠按钮，右侧驾驶舱始终展开。
10. **任务/事件归档与清理**：事件数组无上限，`output/` 无保留策略。

---

## 5. 关键架构决策

| 决策                                                         | 原因与后果                                                                                                   |
| ------------------------------------------------------------ | ------------------------------------------------------------------------------------------------------------ |
| 用 Python 状态机掌握流程，模型只产出内容                     | 防止模型自由跳步；非法迁移会直接抛错。代价是流程固定、扩展新阶段需改代码。                                   |
| Employee = Talent(YAML) + Vessel                             | 角色是纯数据，可单独测试与替换模型；`Vessel` 统一负责超时、重试、预算、契约校验。                            |
| 双层审查，后端做最终裁决                                     | 机械门禁只信真实浏览器行为，AI 只做语义补充；避免「AI 说通过就通过」。代价是门禁依赖本机浏览器。             |
| 文件系统即真相，`task.json` 是唯一状态源                     | 事件先写 `task.json` 再广播，刷新/重连可用快照完整恢复；无需数据库，便于黑客松演示。代价是不支持多 worker。  |
| 生成游戏只在独立目录落盘，隔离预览执行                       | 生成代码视为不可信；CSP + iframe `sandbox`（无 same-origin）阻止访问主站资源。                               |
| 不引入 LangChain / React / Vue / Redis / PostgreSQL / Docker | 降低复杂度与演示环境依赖，全部用原生能力实现。                                                               |
| 模型名与价格全部配置化                                       | 避免硬编码过时模型；无价格时费用标记 `unknown`，不伪造为 0。                                                 |
| Mock 模式一等公民                                            | 无 API Key 也能完整演示与跑测试；Mock 输出结构合法，审查默认 ITERATE → PASS，展示修复闭环。                  |
| 阶段最少 6 秒，动画独占                                      | 让像素办公室动画可读；时长由后端控制，前端不做假动画。                                                       |
| 预算用锁 + 信号量限制并发                                    | 检查与调用之间存在时间窗，串行化记账 + 限并发把超额控制在一次调用内。                                        |
| Talent 版本只读 + `active.json` 指针切换                     | 回滚只移动指针，不复制内容；历史版本永不丢，启用/回滚都有审计。                                              |
| 提案只追加 checklist，不改写 prompt                          | 来源可追溯、token 增长可控；提示词级改写需要真实模型对比评估，本阶段不伪造。                                 |
| 验收阈值写死在代码里                                         | 防止「先看结果再调标准」；提案与模型无权修改阈值。                                                           |
| 真实评估未接入时明确报错                                     | 宁可拒绝，也不用 mock 结果冒充真实模型评测。                                                                 |
| SOP 由 Python 选择，模型无权跳步                             | 手动优先，自动选择写原因；FAST 仍保留门禁与审查，避免「极速=关闭测试」。代价是规则是启发式，需要维护关键词。 |
| 冲突阶段并行执行、串行提交                                   | 两名总监真实并行缩短墙钟时间；只执行不写 `TaskRecord`，结束后串行落盘，避免共享状态竞态。                    |
| 讨论轮数上限 1，COO 必须给理由                               | 防止无限辩论；裁决缺失直接失败，而不是静默采用某一方。                                                       |
| 游戏版本不可变，分支只复制父 HTML                            | 历史永不覆盖，分支可追溯；SHA-256 证明父版本未被改动。代价是磁盘随版本增长，暂无清理策略。                   |

---

## 6. 当前 API

服务默认 `http://127.0.0.1:8000`。所有响应均为 JSON，除非注明。

| 方法     | 路径                                        | 请求                                                                                                  | 响应                                                                                                                |
| -------- | ------------------------------------------- | ----------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------- |
| GET      | `/api/health`                               | —                                                                                                     | `{"status":"ok","mode":"demo\|live","mock_mode":bool,"read_only":bool,"live_ready":bool}`                           |
| GET      | `/api/demo`                                 | —                                                                                                     | Demo 历史任务列表（`demo/tasks`，只读）                                                                             |
| POST     | `/api/tasks`                                | `{"requirement": "非空字符串", "sop_mode"?: "fast\|balanced\|creative", "source_version_id"?: "..."}` | Demo 只读 → `403`；Live 未配置 → `503`；令牌错误 → `401`；限流/并发 → `429`；其余同下                               |
| POST     | `/api/tasks`（正常路径）                    | 同上，Live 需 `X-OGS-Token`                                                                           | `202` + `TaskRecord`；同一需求有活跃任务时 `409`（`detail` 含 `task_id`、`status`）；非法版本 `400`，缺失版本 `404` |
| GET      | `/api/tasks/{task_id}`                      | —                                                                                                     | `TaskRecord`；非法 id 或不存在 → `404`                                                                              |
| POST     | `/api/tasks/{task_id}/cancel`               | —                                                                                                     | `202` + `TaskRecord`；终态任务 → `409`                                                                              |
| GET      | `/api/tasks/{task_id}/artifacts`            | —                                                                                                     | `{文件名: 文件内容}`（只含已登记产物）                                                                              |
| GET      | `/api/tasks/{task_id}/artifacts/{filename}` | 路径含子目录，如 `history/index.v1.html`                                                              | `text/plain`；不在白名单或不存在 → `404`                                                                            |
| GET      | `/api/tasks/{task_id}/history`              | —                                                                                                     | `["history/index.v1.html", ...]`，按名称排序                                                                        |
| GET      | `/api/tasks/{task_id}/versions`             | —                                                                                                     | 不可变 `GameVersion` 列表（按版本号升序）                                                                           |
| GET      | `/preview/{task_id}/{filename}`             | 仅 `index.html`、`history/index.v{n}.html`                                                            | `text/html` + CSP/nosniff/no-store；否则 `404`                                                                      |
| WS       | `/ws/tasks/{task_id}`                       | —                                                                                                     | 首帧 `{"type":"task.snapshot","task": {...}}`，之后为事件消息；空闲 20s 发 `ping`；非法/未知任务关闭码 `4404`       |
| GET      | `/api/talents`                              | —                                                                                                     | 员工当前启用版本 + 已完成任务数量与名称                                                                             |
| GET      | `/api/employees`                            | —                                                                                                     | 6 个职位、角色、任务统计与岗位级 `active_talent`（仅工程师职位有两个角色）                                          |
| POST     | `/api/positions/{position}/switch`          | `{"talent_name": "..."}`                                                                              | 切换岗位启用角色；角色不属于该岗位 → `409`，岗位不存在 → `404`                                                      |
| GET      | `/api/talents/{talent}`                     | —                                                                                                     | 版本、经验、提案、评估、审计、回归用例与阈值                                                                        |
| POST     | `/api/talents/{talent}/diagnose`            | —                                                                                                     | 跑固定回归集，生成 verified 经验                                                                                    |
| POST     | `/api/talents/{talent}/rollback`            | `{"version": n, "reason": "..."}`                                                                     | 回滚到非候选版本；候选版本 → `409`                                                                                  |
| GET      | `/api/lessons`                              | `?talent=` 可选                                                                                       | 经验列表                                                                                                            |
| POST     | `/api/lessons/{id}/verify`                  | `{"verification": "证据"}`                                                                            | candidate → verified；无证据 → `400`                                                                                |
| POST     | `/api/lessons/{id}/reject`                  | —                                                                                                     | candidate → rejected；verified → `409`                                                                              |
| POST     | `/api/tasks/{task_id}/lessons`              | —                                                                                                     | 从终态任务产物提取经验；非终态 → `409`                                                                              |
| GET/POST | `/api/evolution/proposals`                  | POST：`{"talent","lesson_ids"}`                                                                       | 提案列表 / 新建提案（仅 verified 经验）                                                                             |
| GET      | `/api/evolution/proposals/{id}`             | —                                                                                                     | 单个提案                                                                                                            |
| POST     | `/api/evolution/proposals/{id}/evaluate`    | —                                                                                                     | 固定回归评估，写 `engine=mock` 报告                                                                                 |
| POST     | `/api/evolution/proposals/{id}/approve`     | —                                                                                                     | 评估通过后批准并启用；未通过 → `409`                                                                                |
| POST     | `/api/evolution/proposals/{id}/reject`      | —                                                                                                     | 拒绝提案与候选版本                                                                                                  |
| GET      | `/api/evolution/evaluations/{id}`           | —                                                                                                     | 评估报告                                                                                                            |

`TaskRecord` 字段：

```json
{
  "task_id": "12 位十六进制",
  "requirement": "原始需求",
  "status": "pending | planning | coding | reviewing | fixing | marketing | completed | failed | needs_attention | cancelled",
  "fix_attempts": 0,
  "max_fix_rounds": 2,
  "artifacts": { "prd.md": "prd.md" },
  "events": [
    {
      "task_id": "...",
      "type": "task.created",
      "message": "...",
      "stage": "...",
      "created_at": "...",
      "data": {}
    }
  ],
  "error": null,
  "budget": {
    "task_id": "...",
    "budget_usd": 1.0,
    "spent_usd": 0.0,
    "calls": 0,
    "unknown_usage_calls": 0,
    "unknown_cost_calls": 0,
    "downgraded_calls": 0,
    "blocked_calls": 0,
    "models": {}
  },
  "cancel_requested_at": null,
  "talent_versions": { "reviewer": "reviewer@v2", "coo": "coo@v1" },
  "sop_mode": "fast | balanced | creative",
  "sop_reason": "用户手动选择 FAST / 需求包含创新玩法关键词…",
  "source_version_id": null,
  "source_sha256": null,
  "run_id": "16 位十六进制",
  "final_version_id": "12 位十六进制-v1",
  "conflict_decision": {
    "decision": "simplify",
    "summary": "...",
    "rationale": "...",
    "adopted_from": "both"
  },
  "creative_talent_version": "creative@v1 | null",
  "delivery_talent_version": "delivery@v1 | null",
  "metrics": { "elapsed_ms": 1234, "model_calls": 6, "parallel_wall_ms": 120 },
  "created_at": "...",
  "updated_at": "..."
}
```

事件类型（`TraceEvent.type`，即 WebSocket 的 `type`）：

`task.created`、`task.status_changed`、`agent.status_changed`、`tool.called`、`artifact.created`、`fix.requested`、`review.completed`、`budget.updated`、`task.completed`、`task.failed`、`task.cancelled`、`sop.selected`、`conflict.opinion`、`conflict.resolved`；Vessel 内部还有 `stage.started / stage.completed / stage.failed`（不直接推给前端）。

WebSocket 消息统一字段：

```json
{
  "type": "budget.updated",
  "task_id": "...",
  "agent": "coo",
  "status": null,
  "stage": "planning",
  "message": "...",
  "ts": "ISO8601",
  "data": {},
  "model": "mock",
  "duration_ms": 12,
  "token_usage": {
    "input_tokens": 0,
    "output_tokens": 0,
    "total_tokens": 0,
    "source": "estimated"
  },
  "result": "ok",
  "error": null
}
```

---

## 7. 数据存储

**没有数据库。** 全部是文件 + 进程内状态。

### 7.1 任务目录（`OUTPUT_DIR`，默认 `output/`，已在 `.gitignore` 中）

```
output/{task_id}/
    task.json                 唯一状态源：状态、SOP、事件数组、产物索引、预算快照、指标、取消时间
    prd.md                    COO 产出
    creative_proposal.json    Creative 产出（BALANCED/CREATIVE）
    delivery_assessment.json  Delivery 产出（BALANCED/CREATIVE）
    conflict_decision.json    COO 裁决（含理由）
    index.html                Engineer 最新版本（交付文件）
    gate.json                 最新一轮机械门禁报告
    review.json               最终 AI 审查报告
    marketing_kit.json        Marketer 结构化素材
    marketing_kit.md          Marketer 人读版
    history/index.v{n}.html   每次修复前的旧版本
    history/gate.v{n}.json    每轮门禁报告留档
    history/creative_proposal.round1.json  CREATIVE 修订前提案
    versions/{task_id}-v{n}.json          不可变 GameVersion
    versions/{task_id}-v{n}.html          不可变版本 HTML
    source/{task_id}.html     分支任务的父版本副本
```

写入策略：**只新增，不删除**。任一阶段失败或取消，已产出文件全部保留。

### 7.2 自进化目录（`EVOLUTION_DIR`，默认 `output/evolution`，已被 `output/*` 忽略）

```
output/evolution/
    talents/{talent}/versions/v{n}.json   不可变 Talent 版本
    talents/{talent}/active.json          启用指针 + 启用/回滚审计
    lessons/{lesson_id}.json              经验（candidate/verified/rejected）
    proposals/{proposal_id}.json          进化提案
    evaluations/{evaluation_id}.json      新旧版本回归评估报告
```

### 7.3 各类数据的实际保存方式

| 概念          | 实际实现                                                           | 位置                                          |
| ------------- | ------------------------------------------------------------------ | --------------------------------------------- |
| Task          | `TaskRecord` → `task.json`                                         | `output/{task_id}/task.json`                  |
| Version       | 不可变 `GameVersion` + HTML；修复中间快照另有 `history/`           | `output/{task_id}/versions/`、`history/`      |
| Run           | 只有 `TaskRecord.run_id` 字符串；一次 `POST /api/tasks` 即一次运行 | `task.json.run_id`                            |
| Project       | **不存在**                                                         | —                                             |
| Talent        | YAML 基线 + `output/evolution` 版本库（v1 由 YAML 播种）           | `talents/*.yaml`、`output/evolution/talents/` |
| Lesson        | 一条经验一个 JSON 文件                                             | `output/evolution/lessons/`                   |
| Proposal      | 一个提案一个 JSON 文件                                             | `output/evolution/proposals/`                 |
| Evaluation    | 一个评估报告一个 JSON 文件                                         | `output/evolution/evaluations/`               |
| Event         | `TraceEvent` 数组，随 `task.json` 落盘                             | `task.json.events`                            |
| Budget        | `TaskBudget` 快照，随 `task.json` 落盘                             | `task.json.budget`                            |
| 事件订阅队列  | 进程内 `asyncio.Queue(256)`                                        | 内存，重启即失                                |
| 预算累计      | `BudgetGuard._state` 字典                                          | 内存，重启清零                                |
| 运行/取消标记 | `WorkflowEngine._running / _cancel_requested`                      | 内存                                          |

### 7.4 敏感数据

- `LLM_API_KEY` 只存在于服务端 `.env` / 环境变量，`.env` 已被 `.gitignore` 忽略。
- 代码中没有任何硬编码密钥、Token 或密码。
- 本交接文档不包含任何密钥值。

---

## 8. 启动命令（已验证）

环境：macOS（Apple Silicon），Python 3.13.9，uv 0.13.4。

```bash
# 1. 安装依赖（会创建/同步 .venv）
uv sync

# 2. 准备配置（默认 MOCK_MODE=true，无需 API Key）
cp .env.example .env

# 3. 启动服务
uv run uvicorn backend.main:app --reload
# 打开 http://127.0.0.1:8000/

# 4. 健康检查
curl http://127.0.0.1:8000/api/health
# {"status":"ok","mock_mode":true}

# 5. 运行全部测试
uv run pytest -q
```

本次交接实测：

| 命令                                                | 结果                                         |
| --------------------------------------------------- | -------------------------------------------- |
| `uv run pytest -q`                                  | **119 passed in 79.54s**                     |
| `uv run python -c "import backend.main"`            | `app ok OneGameStudio 0.10.0 mock=True`      |
| 临时端口启动 `uvicorn backend.main:app --port 8123` | `/api/health` 200、`/` 200、`/style.css` 200 |
| 前端构建                                            | 不需要；FastAPI 直接挂载 `frontend/`         |

机械门禁需要浏览器：

```bash
uv run playwright install chromium     # 可选
# 若无法下载，会自动回退系统 Chrome；也可设置 OGS_BROWSER_PATH
```

本机 `~/Library/Caches/ms-playwright` 为空，测试实际走的是**系统 Chrome**回退路径，全部通过。

真实模型模式：

```bash
# .env
MOCK_MODE=false
LLM_BASE_URL=https://你的兼容端点/v1
LLM_API_KEY=...
LLM_MODEL=...
```

---

## 9. 当前问题

### 9.1 未修复 Bug / 限制

1. EventBus 与 BudgetGuard 都是**进程内**状态：重启清零，多 worker 各算各的（多 worker 下快照与推送会错乱）。
2. 取消是**协作式**：不会中断在途模型 HTTP 请求，最长需等待一次超时或阶段展示时长。
3. 事件数组无上限：长任务会让 `task.json` 持续增大，读取与 WebSocket 快照成本上升。
4. 调用前无法预知输入 token，最后一次调用可能让花费**有限超额**（最多一次调用）。
5. `TaskStore.find_active_by_requirement` 每次提交都遍历 `output/` 下所有任务（O(n)）。
6. 机械门禁的玩法断言依赖游戏暴露 `window.__ogsProbe`；未暴露时方向键/计分/重开只能标 `unverified`。
7. Mock 模式费用是「配置单价 × 估算 token」，与真实账单无关；未配置 `MODEL_PRICES` 时 `cost_status="unknown"`。
8. 自进化评估只有 `engine=mock`：基于清单关键词覆盖判定，不代表真实模型能力；`MOCK_MODE=false` 时服务层明确报错。
9. 进化提案是规则型：只追加 checklist，不改写 prompt；提示词级进化需要真实模型对比评估。
10. `active.json` 审计为追加数组，暂无归档；`output/evolution` 无清理策略。

### 9.2 技术债务

- 无数据库 / 无迁移机制；任务只存在于单机磁盘。
- 无日志轮转与任务归档。
- `frontend/app.js` 单文件 582 行，渲染逻辑与网络逻辑耦合，缺少模块拆分。
- 前端没有构建链，也意味着无法使用 TypeScript / 组件化。
- 文档与代码存在同步风险（`docs/architecture.md`、`docs/progress.md` 需随手更新）。

### 9.3 测试缺口

- **真实模型模式未被自动化覆盖**：`providers/openai.py` 没有基于真实端点的测试（需要 Key），只有 Mock 路径被验证。
- 前端没有 E2E 测试；像素办公室、标签切换、断线重连只做过人工/临时脚本验证。
- WebSocket 重连与快照恢复没有自动化用例。
- 机械门禁测试依赖本机 Chrome，CI 上可能因浏览器缺失而失败。
- 预算的并发边界（多任务同时调用）没有压力测试。
- Talent 面板没有浏览器点击级自动化测试，只通过 `node --check`、HTTP 接口与 JSON 结构验证。
- 自进化只覆盖 Mock 评估，真实模型评估链路没有测试。

### 9.4 已知安全问题

- API **无鉴权、无速率限制**，只适合本地演示；暴露公网前必须加认证与配额。
- `output/` 产物目录未做大小限制，恶意/异常模型输出可能写满磁盘。
- 预览隔离依赖 CSP + iframe sandbox；这是纵深防御，不是完整沙箱（不防浏览器 0day）。
- `LLM_API_KEY` 若被错误提交到 `.env` 之外的位置会泄露；当前 `.gitignore` 已覆盖 `.env`。

### 9.5 尚未解决的设计决策

1. 是否引入 Project/Run 领域模型，还是继续「一需求一 Task」。
2. 预算与事件是否需要迁到 Redis / SQLite 以支持多 worker。
3. 员工自进化已落地为「版本库 + 经验文件 + checklist 注入」；是否引入「独立反思 Agent」或提示词改写仍未决定。
4. 双角色冲突协作如何与现有固定状态机共存（新增状态还是并行分支）。
5. 部署形态：npx 单命令起服务，还是 Docker + 反向代理。
6. 是否给生成游戏引入版本号字段与回滚接口（当前只有文件快照）。

---

## 10. 后续开发计划

> 注意：Mini-6 Harness（阶段 6）、AI 员工自进化（阶段 8）与双角色冲突协作 / 三种 SOP（阶段 9）**均已完成**。阶段 9 见 [conflict-protocol.md](conflict-protocol.md) 与 [fast-sop.md](fast-sop.md)。下一阶段应从下面的列表开始。

建议顺序：

1. **真实模型评估（live 引擎）**
   - 目标：把阶段 8 的固定回归集交给真实模型执行，用真实检出率/误报率/Token 替换 Mock 判定。
   - 约束：必须保留同一组用例与写死的验收阈值；评估失败与未知用量要如实标注。
2. **前端 E2E 与演示交付**
   - 目标：覆盖提交需求 → SOP 选择 → 观看六人动画与观点气泡 → 预览游戏 → 查看审查/营销/Talent/Studio → 取消/重连。
   - 需要补：真实模型模式冒烟测试（廉价模型 + 预算上限）、CI 中的 Chromium 安装、演示数据清理脚本。
3. **npx 启动与线上部署**
   - 目标：一条命令起服务；补 `package.json`、启动脚本、生产环境配置。
   - 需要处理：单 worker 限制（当前进程内状态）、鉴权、HTTPS、静态资源缓存。
4. **Project / Run 领域模型（可选）**
   - 目标：多任务归组、项目级版本历史与跨任务统计；当前只有 `run_id` 字符串。

---

## 11. 交接验收记录

| 项目      | 结果                                                                                                                                                                                                                                                   |
| --------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| 测试命令  | `uv run pytest -q`                                                                                                                                                                                                                                     |
| 测试结果  | **119 passed**                                                                                                                                                                                                                                         |
| 测试文件  | `test_api.py`(18) / `test_contract.py`(6) / `test_evolution.py`(21) / `test_gate.py`(9) / `test_harness.py`(14) / `test_modes.py`(6) / `test_sop.py`(6) / `test_talents.py`(9) / `test_versions.py`(5) / `test_vessel.py`(11) / `test_workflow.py`(12) |
| 应用导入  | 通过（FastAPI `OneGameStudio` v0.10.0，`mock_mode=True`）                                                                                                                                                                                              |
| HTTP 冒烟 | `/api/health`、`/`、`/style.css`、`/talent.js` 均 200                                                                                                                                                                                                  |
| Git 状态  | `main`；`origin` 指向私有的 `github.com/Lmliya/OneGameStudio`；阶段 9/10 已提交并推送（`8058ab3`），工作区仅 `backend/providers/__init__.py` 未提交                                                                                                    |
| 手工验收  | 浏览器：SOP 下拉 / 六员工 / BALANCED 徽章 / Studio（提案、裁决、版本、指标）/ Game 预览全部通过，控制台无 JS 报错；HTTP 实跑 FAST 5 次 38.2s、BALANCED 8 次 50.4s、CREATIVE 9 次 62.4s（均为 Mock）                                                    |
| 未验证项  | 真实 LLM 端到端、真实模型评估（live）、实际线上部署、npm 包发布、GitHub 转 public、多 worker 部署、npx 启动、预算并发压力测试                                                                                                                          |

### 交接时的 Git 信息

```text
branch : main
commit : 8058ab3 完成了最初版本
remote : origin https://github.com/Lmliya/OneGameStudio.git（private，已推送）
status : M backend/providers/__init__.py
```

本轮未执行 `git add / commit / push`；唯一未提交改动是 Live 缺密钥时的占位供应商。

---

## 12. 给下一个 Agent 的第一句话

> 先读 `docs/HANDOFF.md`（本文）→ `docs/architecture.md` → `docs/harness.md` → `docs/talent-evolution.md` → `docs/conflict-protocol.md` → `docs/fast-sop.md` → `docs/progress.md` → `docs/deployment.md` → `docs/demo.md`，然后跑 `uv run pytest -q` 确认 119 passed。阶段 6（Mini-6 Harness）、阶段 8（AI 员工自进化）、阶段 9（双角色冲突 / 三种 SOP / 不可变版本）与阶段 10（本地启动 CLI / Demo-Live 双模式 / 部署配置）均已完成，不要重做。改动前先读现有代码与文档，保持「状态由 Python 控制、费用不伪造、产物只增不删、安全边界不可被进化触碰」四条底线。
