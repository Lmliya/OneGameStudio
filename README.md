# OneGameStudio

轻量级 AI 游戏开发工作室。输入一句自然语言游戏需求，四个 AI 员工（COO / Engineer / Reviewer / Marketer）协作产出可运行的 HTML5 游戏、审查报告与营销文案。

> 当前进度：**阶段 5（像素办公室与实时驾驶舱）**。Mock 模式下可完整跑通
> `COO → Engineer → Reviewer → Engineer → Reviewer → Marketer`，
> 并在浏览器里实时观看四个 AI 员工工作、直接试玩生成结果。

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

## 界面

顶部输入需求点「开始开发」，左边像素办公室里四个员工会依次开工，右边四个标签页实时更新：

| 标签          | 内容                                           |
| ------------- | ---------------------------------------------- |
| **Game**      | 隔离 iframe 中直接试玩；可切换修复前的历史版本 |
| **Review**    | AI 裁决、问题清单、机械门禁 10 项检查表        |
| **Marketing** | 定位、Slogan、两篇小红书文案、七天推广计划     |
| **Logs**      | 全量事件流                                     |

底部事件条滚动显示最近事件。刷新页面会自动恢复当前任务，WebSocket 断线后自动重连（1s → 8s 退避）。所有员工状态都来自后端事件，没有前端伪造的进度动画。

## 创建一个任务

```bash
curl -X POST http://127.0.0.1:8000/api/tasks \
  -H 'Content-Type: application/json' \
  -d '{"requirement": "做一个贪吃蛇游戏"}'
# 202，返回 task_id 与 status=pending，工作流在后台执行
```

查询进度与产物：

```bash
curl http://127.0.0.1:8000/api/tasks/<task_id>
curl http://127.0.0.1:8000/api/tasks/<task_id>/artifacts
curl http://127.0.0.1:8000/api/tasks/<task_id>/history
```

实时事件走 WebSocket（连上立即收到 `task.snapshot` 快照）：

```bash
websocat ws://127.0.0.1:8000/ws/tasks/<task_id>
```

游戏预览（只允许 `index.html` 与 `history/index.v{n}.html`）：

```
http://127.0.0.1:8000/preview/<task_id>/index.html
```

产物位置：

```
output/{task_id}/
    prd.md
    index.html
    gate.json
    review.json
    marketing_kit.json
    marketing_kit.md
    task.json
    history/index.v1.html
    history/gate.v1.json
```

## 质量审查

生成的游戏必须通过两层审查才会交付：

1. **机械门禁**：Playwright 在隔离浏览器中真实加载页面，检查页面加载、未处理 JS 错误、游戏区域、方向键、计分、结束后重开，默认阻断一切外部网络请求。
2. **AI Reviewer**：读取 PRD、门禁报告与游戏代码，输出 `PASS / ITERATE`。

门禁失败时，AI 给出的 PASS 会被强制改为 ITERATE；修复最多 2 次，每次修复前把旧版本存入 `history/`。

```bash
uv run playwright install chromium   # 可选；失败时自动回退到系统 Chrome
```

产物目录同时包含 `gate.json`（最新门禁报告）与 `review.json`（最终裁决）。

## 营销素材

审查通过后 Marketer 会产出两份文件：

- `marketing_kit.json`：游戏定位、Slogan、两篇小红书文案、七天推广计划，供前端渲染
- `marketing_kit.md`：同一内容的人读版

只能宣传机械门禁已验证的功能；一旦检测到编造的「用户数 / 下载量」等表述，营销阶段失败，但已通过审查的游戏文件会保留。

## 运行测试

```bash
uv run pytest -q
```

## 工作流

```
pending → planning(COO) → coding(Engineer) → reviewing(Reviewer)
        → [fixing(Engineer) → reviewing] × 最多 2 次
        → marketing(Marketer) → completed
```

未通过且修复次数用尽 → `needs_attention`；任一阶段异常 → `failed`，已产出文件保留。

状态由 Python 状态机推进，模型无权修改。

## 配置项

| 变量                      | 说明                                      |
| ------------------------- | ----------------------------------------- |
| `MOCK_MODE`               | `true` 时使用 MockProvider，不联网不花钱  |
| `LLM_BASE_URL`            | OpenAI 兼容接口地址                       |
| `LLM_API_KEY`             | 服务端密钥，仅在真实模式需要              |
| `LLM_MODEL`               | 全局默认模型，可被 Talent 的 `model` 覆盖 |
| `REQUEST_TIMEOUT_SECONDS` | 单次调用超时                              |
| `BUDGET_USD`              | 单任务成本预算                            |

模型名与密钥不出现在业务代码中。

## 目录结构

```
backend/
    main.py           FastAPI 入口（API / WebSocket / 隔离预览）
    bus.py            进程内事件总线
    config.py         全局配置
    schemas.py        输出契约
    talents.py        Talent 加载与校验
    store.py          任务持久化
    models/           TaskRecord / TalentSpec / TraceEvent
    core/vessel.py    员工执行容器
    providers/        base / mock / openai
    gate/             机械门禁（Playwright）
    workflow/         状态机与编排引擎
frontend/             index.html / style.css / office.js / app.js
talents/              四个员工的 YAML
tests/                pytest
docs/                 architecture.md / progress.md
output/               任务产物（不入库）
```

详细设计见 `docs/architecture.md`。

## 设计约束

- 工作流状态由 Python 代码推进，模型无权修改。
- Reviewer 只审查不改代码，Marketer 只写营销不改游戏。
- 生成的游戏代码视为不可信内容，只在独立目录落盘，不在服务进程内执行。
- 第一版不引入 LangChain / LangGraph / React / Vue / Redis / PostgreSQL / Docker。
