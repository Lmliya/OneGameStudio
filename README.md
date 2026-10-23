# OneGameStudio

轻量级 AI 游戏开发工作室。输入一句自然语言游戏需求，四个 AI 员工（COO / Engineer / Reviewer / Marketer）协作产出可运行的 HTML5 游戏、审查报告与营销文案。

> 当前进度：**阶段 1（Talent / Vessel）**。四个员工已能通过同一个 Vessel 独立执行；串行编排与回退逻辑尚未实现（阶段 4）。

## 快速开始

```bash
uv sync
cp .env.example .env        # 默认 MOCK_MODE=true，无需任何 API Key
uv run uvicorn backend.main:app --reload
```

打开 <http://127.0.0.1:8000/>，健康检查：

```bash
curl http://127.0.0.1:8000/api/health
# {"status":"ok","mock_mode":true}
```

## 运行测试

```bash
uv run pytest -q
```

## 直接运行一个员工

```python
import asyncio
from pathlib import Path
from backend.core.vessel import Vessel
from backend.providers.mock import MockProvider

async def main():
    vessel = Vessel(MockProvider(), talents_dir=Path("talents"), default_model="gpt-4o-mini")
    result = await vessel.execute("coo", "做一个贪吃蛇游戏")
    print(result.output)

asyncio.run(main())
```

## Talent 配置

`talents/*.yaml`，每个员工一份：

```yaml
name: COO
role: 需求分析
system_prompt: |
  ...
model: null # 留空则用全局 LLM_MODEL
allowed_tools: [] # 必须在系统白名单内
output_schema: prd # 必须已注册
```

白名单当前为 `read_contract`、`write_artifact`；填写其他工具会在加载时直接报错。

## 配置项

| 变量                      | 说明                                      |
| ------------------------- | ----------------------------------------- |
| `MOCK_MODE`               | `true` 时使用 MockProvider，不联网不花钱  |
| `LLM_BASE_URL`            | OpenAI 兼容接口地址                       |
| `LLM_API_KEY`             | 服务端密钥，仅在真实模式需要              |
| `LLM_MODEL`               | 全局默认模型，可被 Talent 的 `model` 覆盖 |
| `REQUEST_TIMEOUT_SECONDS` | 单次调用超时                              |
| `BUDGET_USD`              | 单实例成本预算                            |

模型名与密钥不出现在业务代码中，全部来自配置。

## 目录结构

```
backend/
    main.py           FastAPI 入口
    config.py         全局配置
    schemas.py        输出契约注册表
    talents.py        Talent 加载与校验
    models/           TaskContract / TalentSpec / TraceEvent
    core/vessel.py    统一执行容器
    providers/        base / mock / openai
frontend/             index.html / style.css / app.js
talents/              四个员工的 YAML
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
