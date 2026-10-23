# OneGameStudio

轻量级 AI 游戏开发工作室。输入一句自然语言游戏需求，四个 AI 员工（COO / Engineer / Reviewer / Marketer）协作产出可运行的 HTML5 游戏、审查报告与营销文案。

> 当前进度：**阶段 1（骨架与契约）**。四个员工的实际工作流尚未接入，见 `docs/progress.md`。

## 快速开始

```bash
uv sync
cp .env.example .env        # 默认 MOCK_MODE=true，无需任何 API Key
uv run uvicorn onegamestudio.api.main:app --reload
```

打开 <http://127.0.0.1:8000/health>，应返回：

```json
{"status": "ok", "mock_mode": true}
```

创建任务：

```bash
curl -X POST http://127.0.0.1:8000/api/tasks \
  -H 'Content-Type: application/json' \
  -d '{"requirement": "做一个贪吃蛇游戏"}'
```

产物落在 `data/tasks/<task_id>/contract.json`。

## 运行测试

```bash
uv run pytest -q
```

## Mock 模式说明

`MOCK_MODE=true` 时，模型调用被替换为 `MockLLM`：**不联网、不消耗 token、结果确定**。

它影响的是"内容生成"这一步，不影响"工作流编排"——谁先执行、失败如何回退、产物存到哪里，全部由 Python 代码决定。

切换为真实模型只需改 `.env`，代码无需改动：

```bash
MOCK_MODE=false
OPENAI_API_KEY=sk-...
OPENAI_BASE_URL=https://api.openai.com/v1
DEFAULT_MODEL=gpt-4o-mini
```

API Key 只从服务端环境变量读取，不写入任何代码或前端。

## 目录结构

```
src/onegamestudio/
├── config.py          全局配置（.env 驱动）
├── models/
│   ├── contract.py    TaskContract：任务输入输出契约
│   ├── talent.py      TalentSpec：员工身份与工具权限
│   └── events.py      TraceEvent + Tracer：事件记录
├── core/
│   ├── llm.py         BaseLLM / MockLLM / OpenAICompatLLM
│   └── vessel.py      Vessel：统一调用、用量统计、预算保护
└── api/
    └── main.py        FastAPI 入口
```

## 设计约束

- 工作流状态由 Python 代码推进，模型无权修改。
- 生成的游戏代码一律视为不可信代码，后续在隔离目录中执行与校验。
- 每个任务使用独立目录，产物不互相覆盖。
- 第一版不引入 LangChain / LangGraph / React / Vue / Redis / PostgreSQL / Docker。
