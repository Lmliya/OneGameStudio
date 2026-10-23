# OneGameStudio 架构说明

> 版本：v0.2（阶段 1：Talent / Vessel）
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
```

- **Talent** 是纯数据：身份、提示词、模型、工具权限、输出契约。存在 `talents/*.yaml`。
- **Vessel** 是执行容器：加载 Talent、调模型、解析、校验、计量、报错。
- 四个员工共用同一个 Vessel 类，只有配置不同。

## 3. 分层结构

```
frontend/            纯静态页面，无构建链
    index.html / style.css / app.js

backend/
    main.py          FastAPI 入口：/api/health、/api/tasks、静态托管
    config.py        全局配置（.env 驱动，LLM_* 变量）
    schemas.py       四个输出契约 + OUTPUT_SCHEMAS 注册表
    talents.py       Talent 加载器 + 工具白名单校验
    models/
        contract.py  TaskContract
        talent.py    TalentSpec
        events.py    TraceEvent / Tracer
    core/vessel.py   统一执行容器
    providers/
        base.py      BaseProvider / ProviderResponse
        mock.py      MockProvider（按 schema 返回合法 JSON）
        openai.py    OpenAICompatibleProvider

talents/             coo / engineer / reviewer / marketer 的 YAML
tests/               pytest
docs/                architecture.md / progress.md
output/              任务产物（不入库）
```

## 4. 一次员工执行的完整流程

````
Vessel.execute(talent_id, context)
   ↓ 1. load_talent()        读取 YAML，校验工具与 schema
   ↓ 2. 选择模型              talent.model or LLM_MODEL
   ↓ 3. 预算检查              已花费 >= BUDGET_USD 则拒绝
   ↓ 4. provider.complete()   asyncio.wait_for 包裹超时
   ↓ 5. _extract_json()       去掉 ``` 围栏，定位 JSON 对象
   ↓ 6. schema.model_validate Pydantic 结构校验
   ↓ 7. AgentResult           输出 + token + 耗时 + 成本
````

任何一步失败都会抛出明确的 `VesselError` 子类，不会静默降级。

## 5. 错误分类

| 异常                    | 触发场景                                        |
| ----------------------- | ----------------------------------------------- |
| `TalentNotFoundError`   | 配置不存在、字段缺失、工具未授权、schema 未注册 |
| `ProviderTimeoutError`  | 调用超过 `REQUEST_TIMEOUT_SECONDS`              |
| `ProviderCallError`     | 网络、鉴权、HTTP 错误等                         |
| `OutputParseError`      | 输出中没有合法 JSON                             |
| `OutputValidationError` | JSON 合法但不符合契约                           |
| `BudgetExceededError`   | 累计花费超预算                                  |

## 6. 为什么 Mock 必须按 schema 返回

`Vessel` 对 Mock 和真实模型走完全相同的解析与校验路径。如果 Mock 返回自由文本，就测不出"契约是否写对"。当前 Mock 的四个输出都严格符合 `OUTPUT_SCHEMAS`，因此四个员工可以在无 Key 环境下被独立测试。

## 7. 安全边界

- `allowed_tools` 在加载时与 `ALLOWED_TOOLS` 求差集，出现未授权工具直接拒绝启动该 Talent。
- 项目当前不存在任何 shell 执行入口；模型输出只被当作 JSON 数据解析，不会被执行。
- 输出必须通过 Pydantic 校验，类型、长度、枚举、分值范围都在契约中约束。
- API Key 只从服务端环境变量读取，前端永不接触。

## 8. Mini-6 落位情况

| 能力          | 当前状态                                       |
| ------------- | ---------------------------------------------- |
| Task Contract | 已实现 `TaskContract` + 四类输出契约           |
| Tool Policy   | 配置层白名单校验已实现，运行时拦截待阶段 3     |
| Quality Gate  | 规划中（阶段 3）                               |
| Recovery      | 仅定义 `max_fix_rounds` 配置，未实现           |
| Budget Guard  | `Vessel` 单实例累计熔断已实现                  |
| Event Trace   | 内存版 `Tracer`，可挂载到 Vessel，落盘待阶段 3 |

## 9. 技术选型约束

- Python 3.12+ / uv / FastAPI / Pydantic / PyYAML / pytest
- 前端原生 HTML/CSS/JS，无 React/Vue/构建工具
- 不使用 LangChain/LangGraph、Redis、PostgreSQL、Docker
