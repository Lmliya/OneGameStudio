# 开发进度

## 阶段 2：四 Agent 工作流（已完成）

**日期**：2026-10-23

### 已实现

- 确定性状态机 `backend/workflow/state_machine.py`
  - 状态：`pending / planning / coding / reviewing / fixing / marketing / completed / failed / needs_attention`
  - 非法迁移抛 `InvalidTransitionError`，终态不可再迁移
- 工作流引擎 `backend/workflow/engine.py`
  - COO → Engineer → Reviewer →（不通过）Engineer 修复 → 再审查 → Marketer
  - 默认最多修复 2 次，用尽后进入 `needs_attention`
  - 每次状态变更写入 `state_changed` 事件
  - 确定性质量门禁 `game_quality_gate`：空文件、缺 `<html>`、缺 `<script>` 直接判失败
- 任务持久化 `backend/store.py`
  - `output/{task_id}/` 下产出 `prd.md`、`index.html`、`review.json`、`marketing_kit.md`、`task.json`
  - 只新增不删除，任一阶段失败已产出内容保留
- API（`backend/main.py`）
  - `POST /api/tasks` → 202，后台执行；相同需求的运行中任务返回 409
  - `GET /api/tasks/{task_id}`
  - `GET /api/tasks/{task_id}/artifacts`
- Mock 供应商支持审查轮次：默认第 1 次不通过、第 2 次通过，用于演示完整修复闭环
- 测试 39 个全部通过（新增工作流 7 个、状态机 6 个、API 8 个）

### 角色边界

| 规则                               | 实现                                                      |
| ---------------------------------- | --------------------------------------------------------- |
| Reviewer 不得改代码                | 引擎只把审查结果写入 `review.json`，从不回写 `index.html` |
| Marketer 不得改代码                | 只写 `marketing_kit.md`                                   |
| 只有通过质量门禁才能进入 Marketing | `review.passed` 为真且 `game_quality_gate` 无问题         |
| 同一任务不得并发执行               | `WorkflowEngine._running` + `TaskAlreadyRunningError`     |
| 任一阶段失败保留产物               | `TaskStore.write_artifact` 只写不删                       |

### 实际验证

```
uv run pytest -q  → 39 passed in 0.45s
```

Mock 模式端到端实际运行：

```
task_id: 4c7cee59e708
status : completed
fix    : 1

状态轨迹:
  pending    -> planning
  planning   -> coding
  coding     -> reviewing
  reviewing  -> fixing
  fixing     -> reviewing
  reviewing  -> marketing
  marketing  -> completed

产物文件:
  index.html        1319 bytes
  marketing_kit.md   264 bytes
  prd.md             291 bytes
  review.json         51 bytes
  task.json         3000 bytes
```

### 未实现（后续阶段）

- 像素办公室前端与 WebSocket 实时推送（阶段 5）
- 独立的 Quality Gate 模块（当前门禁内嵌在引擎中）
- 经验知识库
- `needs_attention` 任务的人工重试入口

### 已知限制

- Mock 输出与需求文本无关，四个员工的产物固定
- 后台任务使用进程内 `asyncio.Task`，服务重启后运行中任务不会自动续跑
- 产物查询接口一次性返回全部文件内容，任务较大时需要分页或按名读取
- `store.find_active_by_requirement` 每次提交都会扫描全部任务目录，任务量很大时需要索引

---

## 阶段 1：Talent / Vessel（已完成）

**日期**：2026-10-23

### 已实现

- 四个 Talent 配置文件：`talents/{coo,engineer,reviewer,marketer}.yaml`
  - 字段：`name`、`role`、`system_prompt`、`model`、`allowed_tools`、`output_schema`
  - `model` 留空，统一由 `LLM_MODEL` 提供，支持按 Talent 单独覆盖
- 输出契约 `backend/schemas.py`：`GamePRD`、`GameArtifact`、`ReviewReport`、`MarketingKit`
- Talent 加载器 `backend/talents.py`
  - 校验必填字段
  - `allowed_tools` 必须属于系统白名单（当前仅 `read_contract`、`write_artifact`）
  - `output_schema` 必须已注册
- 通用 `Vessel`（`backend/core/vessel.py`）
- 供应商：`MockProvider`、`OpenAICompatibleProvider`
- 配置改为 `LLM_BASE_URL` / `LLM_API_KEY` / `LLM_MODEL`，代码中无硬编码模型名
- 测试 25 个全部通过
- 依赖：新增 `pyyaml`（Talent 配置解析）与 dev 依赖 `httpx2`（消除 Starlette TestClient 告警）

### 安全约束落地

| 要求                          | 实现位置                                        |
| ----------------------------- | ----------------------------------------------- |
| Talent 不得使用未授权工具     | `talents.py` 加载时校验 `ALLOWED_TOOLS`         |
| 不执行模型输出中的 shell 命令 | 全项目无 shell 执行入口；模型输出只当 JSON 解析 |
| 模型输出必须经过结构验证      | `Vessel._validate` + `OUTPUT_SCHEMAS`           |
| 解析失败返回明确错误          | `OutputParseError` / `OutputValidationError`    |

---

## 阶段 0：初始化项目（已完成）

**日期**：2026-10-23

### 环境检查

| 项      | 版本         | 结论                             |
| ------- | ------------ | -------------------------------- |
| macOS   | 26.3 (arm64) | 正常                             |
| Python  | 3.13.9       | 满足 3.12+                       |
| uv      | 0.13.4       | 正常                             |
| Node.js | v25.8.2      | 仅用于本地静态预览，项目无构建链 |
| Git     | 2.50.1       | 已初始化仓库，工作区干净         |

### 已实现

- uv 项目初始化，Python 3.12+
- 目录：`backend/`、`frontend/`、`talents/`、`tests/`、`docs/`、`output/`
- FastAPI 应用，`GET /api/health`
- 前端页面：项目名称、CEO 需求输入框、状态徽章
- 最小 Mock 供应商 + `BaseProvider` 抽象
- 配置模板、`.gitignore`、`README.md`、`docs/architecture.md`

### 结构变更说明

曾使用 `src/onegamestudio/` 布局，阶段 0 按规范迁移为 `backend/`，旧目录已删除，功能等价保留。
