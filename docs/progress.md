# 开发进度

## 阶段 1：骨架与契约（已完成）

**日期**：2026-10-23

### 已实现

- uv 项目初始化，Python 3.12+，src-layout（`src/onegamestudio/`）
- 全局配置 `Settings`：`MOCK_MODE`、API Key、数据目录、预算、修复轮次
- 数据契约：
  - `TaskContract` / `TaskCreateRequest`（任务契约）
  - `TalentSpec`（员工身份、工具白名单、输出契约）
  - `TraceEvent` / `Tracer`（事件记录，Mini-6 第 6 项雏形）
- 模型层：`BaseLLM` 统一接口 + `MockLLM` + `OpenAICompatLLM`
- 执行层：`Vessel`（预算检查、事件记录、错误包装、用量累计）
- API：`GET /health`、`POST /api/tasks`
- 测试：10 个用例全部通过

### 验证方式

```bash
cd OneGameStudio
uv sync
uv run pytest -q
uv run uvicorn onegamestudio.api.main:app --reload
curl http://127.0.0.1:8000/health
```

实测结果：`10 passed, 1 warning in 0.84s`；接口返回 `{"status":"ok","mock_mode":true}`。

### 未实现（后续阶段）

- 四个员工的实际工作流与提示词
- Reviewer 质量门禁与最多 2 次自动修复
- WebSocket 与像素办公室前端
- Experience Evolution 知识库
- 工具权限、恢复、预算的完整 Mini-6 实现

### 已知限制

- `MockLLM` 仅按关键词返回模板，不代表真实理解能力
- `Tracer` 仅在内存中，服务重启即丢失（阶段 3 落盘）
- 测试中出现的 `StarletteDeprecationWarning` 来自第三方库，不影响结果
