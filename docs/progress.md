# 开发进度

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
- 测试：契约、Mock 供应商、Vessel、API 共 12 个用例

### 结构变更说明

上一轮曾使用 `src/onegamestudio/` 布局。本阶段按新规范迁移为 `backend/`，旧目录已删除，功能等价保留，不存在两套代码。

### 验证方式

```bash
cd OneGameStudio
uv sync
uv run pytest -q
uv run uvicorn backend.main:app --reload
```

- `GET /api/health` → `{"status":"ok","mock_mode":true}`
- 浏览器打开 `http://127.0.0.1:8000/` 可看到页面
- `POST /api/tasks` → 生成 `output/tasks/<task_id>/contract.json`

### 未实现（后续阶段）

- 四个员工的工作流与提示词（阶段 2—4）
- 确定性质量门禁、自动修复回退
- WebSocket 实时事件与像素办公室
- 经验知识库

### 已知限制

- `MockProvider` 仅按关键词返回模板，不代表真实理解能力
- `Tracer` 仅在内存中，服务重启丢失（阶段 3 落盘）
- 测试中的 `StarletteDeprecationWarning` 来自第三方库，不影响结果
