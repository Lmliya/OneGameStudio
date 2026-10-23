# 开发进度

## 阶段 1：Talent / Vessel（已完成）

**日期**：2026-10-23

### 已实现

- 四个 Talent 配置文件：`talents/{coo,engineer,reviewer,marketer}.yaml`
  - 字段：`name`、`role`、`system_prompt`、`model`、`allowed_tools`、`output_schema`
  - `model` 留空，统一由 `LLM_MODEL` 提供，支持按 Talent 单独覆盖
- 输出契约 `backend/schemas.py`：`GamePRD`、`GameArtifact`、`ReviewReport`、`MarketingKit`
- Talent 加载器 `backend/talents.py`：
  - 校验必填字段
  - `allowed_tools` 必须属于系统白名单（当前仅 `read_contract`、`write_artifact`）
  - `output_schema` 必须已注册
- 通用 `Vessel`（`backend/core/vessel.py`）：
  1. 加载 Talent 配置
  2. 选择模型（Talent 覆盖 > 全局默认）
  3. 传系统提示词与任务上下文
  4. 解析 JSON（容忍 ```json 代码块）
  5. Pydantic 校验
  6. 记录耗时与 token 用量
  7. 超时（`REQUEST_TIMEOUT_SECONDS`）与异常统一包装
  8. 返回 `AgentResult`
- 供应商：`MockProvider`、`OpenAICompatibleProvider`
- 配置改为 `LLM_BASE_URL` / `LLM_API_KEY` / `LLM_MODEL`，代码中无硬编码模型名
- 测试：25 个用例全部通过（新增 Talent 加载 7 个、Vessel 11 个）

### 实际验证

```
uv run pytest -q  → 25 passed, 1 warning in 0.81s

四个 Talent 通过同一个 Vessel 执行（Mock 模式）：
coo        schema=prd       model=mock  0ms  贪吃蛇 / arcade / 玩法步数=4
engineer   schema=game      model=mock  0ms  snake.html / html 1319 字符
reviewer   schema=review    model=mock  0ms  score=82 passed=True issues=1
marketer   schema=marketing model=mock  0ms  一条蛇，一块屏幕，无限贪吃
累计花费: $0.0000
```

### 安全约束落地

| 要求                          | 实现位置                                     |
| ----------------------------- | -------------------------------------------- |
| Talent 不得使用未授权工具     | `talents.py` 加载时校验 `ALLOWED_TOOLS`      |
| 不执行模型输出中的 shell 命令 | 全项目无 shell 执行入口；Mock 仅返回 JSON    |
| 模型输出必须经过结构验证      | `Vessel._validate` + `OUTPUT_SCHEMAS`        |
| 解析失败返回明确错误          | `OutputParseError` / `OutputValidationError` |
| Mock 可独立测试所有员工       | `tests/test_vessel.py` 参数化覆盖四个 Talent |

### 未实现（后续阶段）

- 四员工串行编排与 Reviewer 回退（阶段 4）
- Tool Policy 的实际拦截执行（当前仅配置层校验）
- 质量门禁的确定性检查（阶段 3）
- 经验库与事件落盘

### 已知限制

- Mock 不理解需求语义，四个员工的输出固定，只验证结构与流程
- `Vessel` 的预算保护按单次实例累计，跨任务共享尚需上层容器
- 真实供应商尚未做联网实测（无 Key，且规范要求 Mock 优先）

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

- uv 项目初始化，Python 3.12+，目录结构：`backend/`、`frontend/`、`talents/`、`tests/`、`docs/`、`output/`
- FastAPI 应用 `backend/main.py`，提供 `GET /api/health` 与 `POST /api/tasks`
- 前端页面：显示 OneGameStudio 名称、CEO 需求输入框、提交按钮与后端状态徽章
- 最小 Mock 供应商：`backend/providers/mock.py` + `BaseProvider` 抽象
- 全局配置 `.env.example`：默认 `MOCK_MODE=true`，无需 API Key
- `.gitignore`：忽略 `.env`、`.venv/`、`output/*`（保留 `.gitkeep`）
- 文档：`README.md`、`docs/architecture.md`、本文件

### 结构变更说明

上一轮曾使用 `src/onegamestudio/` 布局。本阶段按新规范迁移为 `backend/`，旧目录已删除，功能等价保留，不存在两套代码。
