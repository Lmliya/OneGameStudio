# OneGameStudio 架构说明

> 版本：v0.1（阶段 0）
> 本文只描述已实现的部分，未实现的内容标注为"规划中"。

## 1. 项目定位

用户输入一句自然语言游戏需求，四个 AI 员工协作产出可运行的 HTML5 游戏、审查报告与营销文案：

| 员工 | 职责 |
|---|---|
| COO | 分析与拆解需求，生成 PRD |
| Engineer | 生成可运行的 HTML5 游戏 |
| Reviewer | 确定性质检 + AI 审查，发现问题退回 Engineer（最多 2 次） |
| Marketer | 根据实际游戏内容生成营销素材 |

阶段 0 只搭建环境与骨架，四员工工作流为规划中。

## 2. 分层结构

```
frontend/           纯静态页面，无构建链
    index.html      页面骨架
    style.css       样式
    app.js          fetch 调用后端 API

backend/
    main.py         FastAPI 入口：/api/health、/api/tasks、静态托管
    config.py       全局配置（.env 驱动）
    models/         数据契约
        contract.py   TaskContract / TaskCreateRequest
        talent.py     TalentSpec（身份、提示词、工具权限、模型）
        events.py     TraceEvent / Tracer（事件记录）
    core/
        vessel.py     Vessel：统一调用、用量统计、预算保护
    providers/
        base.py       BaseProvider 抽象 + ProviderResponse
        mock.py       MockProvider（离线、零成本、确定性）
        openai.py     OpenAICompatProvider（真实调用）

talents/            员工定义与提示词（阶段 2 填充）
tests/              pytest 测试
docs/               架构与进度文档
output/             任务产物（每个任务一个子目录，不入库）
```

## 3. 一次请求的数据流

```
浏览器输入需求
   ↓ POST /api/tasks
backend/main.py 生成 TaskContract
   ↓
写入 output/tasks/<task_id>/contract.json
   ↓
返回 task_id / status / stage
```

阶段 0 到此为止。阶段 4 会在写完契约后调用 Vessel 依次驱动四个员工。

## 4. 为什么 Mock 与真实模型共用接口

`Vessel` 只依赖 `BaseProvider`：

```python
class BaseProvider(ABC):
    async def complete(self, system: str, user: str, *, model: str) -> ProviderResponse: ...
```

- `MockProvider`：按关键词返回模板，不联网、不花钱、结果确定。
- `OpenAICompatProvider`：调用 OpenAI 兼容接口，需要服务端 `OPENAI_API_KEY`。

这样切换 `MOCK_MODE` 不需要改动任何工作流代码，也让自动化测试不依赖网络。

## 5. 工作流与模型的职责边界

| 层面 | 负责者 | 说明 |
|---|---|---|
| 阶段推进、失败回退、产物落盘 | Python 代码 | 确定性，可测试 |
| 文本内容生成 | Provider（Mock 或真实模型） | 非确定性，可替换 |

模型无权改变工作流状态，这是全局规范第 11 条的落地方式。

## 6. Mini-6 落位情况

| 能力 | 当前状态 |
|---|---|
| Task Contract | 已实现基础结构（`models/contract.py`） |
| Tool Policy | 仅定义字段（`TalentSpec.allowed_tools`），未执行 |
| Quality Gate | 规划中（阶段 3） |
| Recovery | 仅定义 `max_fix_rounds` 配置，未实现 |
| Budget Guard | 已在 `Vessel` 中实现累计花费熔断 |
| Event Trace | 内存版 `Tracer`，阶段 3 落盘 |

## 7. 技术选型约束

- Python 3.12+ / uv / FastAPI / Pydantic / pytest
- 前端原生 HTML/CSS/JS，无 React/Vue/构建工具
- 不使用 LangChain/LangGraph、Redis、PostgreSQL、Docker
- API Key 只存服务端环境变量，前端永不接触
