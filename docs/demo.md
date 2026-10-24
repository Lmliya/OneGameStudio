# Demo 模式说明

## 1. 它是什么

Demo 模式用于公开演示，**不调用任何真实模型、不产生模型费用**。页面展示的是随仓库提交的、
已经通过审查与机械门禁的历史任务记录，而不是临时伪造的“实时输出”。

启动：

```bash
APP_MODE=demo MOCK_MODE=true uv run uvicorn backend.main:app --port 8000
# 或者
node cli/bin.js --demo
```

公开部署必须同时设置 `DEMO_READ_ONLY=true`，此时创建任务会返回 403。

## 2. 演示内容

| 能力           | 数据来源                                             | 说明                                             |
| -------------- | ---------------------------------------------------- | ------------------------------------------------ |
| 像素办公室     | `demo/tasks/{task_id}/task.json` 的事件列表          | WebSocket 先发送空事件快照，再按顺序回放历史事件 |
| Agent 协作过程 | 同一事件列表                                         | 员工状态与观点气泡来自当时真实产生的事件         |
| 游戏版本切换   | `demo/tasks/{task_id}/versions/*.json` 与 `history/` | 不可变版本，可在前端切换预览                     |
| 最终版本       | `task.json` 的 `final_version_id`                    | 展示当时选定的最终版本                           |
| Talent 记录    | `demo/evolution/`（部署时通过 `EVOLUTION_DIR` 指向） | 版本、检查清单与岗位启用状态                     |

演示任务（按更新时间从新到旧，前端自动加载第一个）：

- `demo/tasks/b1ee53da7c4c`：需求为「做一个红色背景的贪吃蛇小游戏」，由 Mock 供应商生成。
  包含两个不可变版本：`V1` 原始贪吃蛇与 `V2` 红色主题；`V2` 为当前最终版本，可在版本下拉框中切换预览或回退。
- `demo/tasks/adc5c4474a83`：需求为「把游戏背景颜色改成蓝色」，由 Mock 供应商生成。

## 3. 明确标识

- 顶部状态栏的 **DEMO 徽章**（悬停显示完整说明）标明「只读历史任务回放，不会调用真实模型，也不会产生费用」。
- `/api/health` 返回 `mock_mode: true`（Demo 依赖 Mock 供应商）。
- `task.json` 中记录的模型名是 `mock`，不会冒充真实模型结果。
- Talent 页面保留当时记录，不做任何“实时进化”伪造。

## 4. 回放机制

1. 前端启动时请求 `/api/health`，发现 `mode=demo`。
2. 请求 `/api/demo` 获取仓库内的历史任务列表。
3. 自动选中第一个已完成任务，并连接 `/ws/tasks/{task_id}`。
4. 后端发送 `task.snapshot`（事件列表清空），随后按 `DEMO_REPLAY_MS`（默认 350ms）逐条发送历史事件。
5. 像素办公室与界面按事件重新播放；刷新页面会重新回放。

回放只重放当时保存的事件，不会重新执行工作流，也不会重新调用模型。

## 5. 修改演示数据

1. 在本地 Mock 或 Live 模式跑一个完整任务，确认 `task.json` 状态为 `completed`。
2. 复制 `output/{task_id}` 到 `demo/tasks/{task_id}`。
3. 如需展示 Talent 记录，把对应的 `output/evolution` 快照复制到 `demo/evolution`。
4. 重新启动 Demo 服务，确认 `/api/demo` 能列出新任务。
5. 不要把包含真实 API Key、用户隐私或未完成任务的目录放进 `demo/`。

## 6. 限制

- Demo 只读（公开部署），不能提交新任务。
- 回放速度是固定的，不代表真实执行耗时。
- Demo 不验证模型能力，不能把回放结果当作实时模型评测。
- 若部署平台没有把 `EVOLUTION_DIR` 指向 Demo 快照，Employee/Talent 面板会显示运行实例自己的版本库。
