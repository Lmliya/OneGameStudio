# OneGameStudio

轻量级 AI 游戏开发工作室。输入一句自然语言游戏需求，四个 AI 员工（COO / Engineer / Reviewer / Marketer）协作产出可运行的 HTML5 游戏、审查报告与营销文案。

> 当前进度：**阶段 0（初始化项目）**。已完成环境、骨架、Mock 供应商与最小前端；四个员工的工作流尚未接入，见 `docs/progress.md`。

## 快速开始

```bash
uv sync
cp .env.example .env        # 默认 MOCK_MODE=true，无需任何 API Key
uv run uvicorn backend.main:app --reload
```

打开 <http://127.0.0.1:8000/> 可以看到页面；健康检查：

```bash
curl http://127.0.0.1:8000/api/health
# {"status":"ok","mock_mode":true}
```

创建任务：

```bash
curl -X POST http://127.0.0.1:8000/api/tasks \
  -H 'Content-Type: application/json' \
  -d '{"requirement": "做一个贪吃蛇游戏"}'
```

产物落在 `output/tasks/<task_id>/contract.json`。

## 运行测试

```bash
uv run pytest -q
```

## Mock 模式说明

`MOCK_MODE=true` 时使用 `MockProvider`：**不联网、不消耗 token、结果确定**。

它只替换"内容生成"这一步，不影响"工作流编排"——谁先执行、失败如何回退、产物存到哪里，全部由 Python 代码决定。

切换真实模型只需改 `.env`，代码无需改动：

```bash
MOCK_MODE=false
OPENAI_API_KEY=sk-...
OPENAI_BASE_URL=https://api.openai.com/v1
DEFAULT_MODEL=gpt-4o-mini
```

API Key 只从服务端环境变量读取，不写入任何代码或前端。

## 目录结构

```
backend/
    main.py           FastAPI 入口
    config.py         全局配置
    models/           任务契约、Talent、事件
    core/vessel.py    统一调用与预算保护
    providers/        base / mock / openai
frontend/             index.html / style.css / app.js
talents/              员工定义（阶段 2）
tests/                pytest
docs/                 architecture.md / progress.md
output/               任务产物（不入库）
```

详细设计见 `docs/architecture.md`。

## 设计约束

- 工作流状态由 Python 代码推进，模型无权修改。
- 生成的游戏代码一律视为不可信代码，后续在隔离目录中执行与校验。
- 每个任务使用独立目录，产物不互相覆盖。
- 第一版不引入 LangChain / LangGraph / React / Vue / Redis / PostgreSQL / Docker。
