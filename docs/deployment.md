# 部署说明

> 当前状态：**未实际部署**。仓库内已准备好 Dockerfile、`render.yaml` 与全部环境变量说明；
> 由于本轮没有用户的 Render / GitHub / 模型服务凭据，没有创建线上实例，也没有可宣称的线上地址。
> 需要用户执行的操作见文末。

## 1. 运行环境审计

| 项目         | 现状                                                                          |
| ------------ | ----------------------------------------------------------------------------- |
| Python       | `>=3.12`，使用 `uv` 管理                                                      |
| Web 框架     | FastAPI + uvicorn，提供 REST 与 WebSocket                                     |
| 长连接       | `/ws/tasks/{task_id}`，需要平台支持 WebSocket 升级                            |
| 浏览器自动化 | 机械门禁在 **Live 执行任务时** 使用 Playwright + Chromium；仅浏览 Demo 不需要 |
| 存储         | 文件系统：`output/{task_id}/` 保存 `task.json`、游戏、版本、审查、营销产物    |
| 版本历史     | 不可变 `versions/*.json` + `history/*.html`，依赖持久化磁盘                   |
| 密钥         | 仅从服务端环境变量读取，前端不接触 `LLM_API_KEY`                              |
| CORS         | 前端由同一个 FastAPI 进程托管，同源，无需 CORS；分离部署时才需要白名单        |

结论：**不能使用纯静态托管**（Vercel / Netlify / GitHub Pages 无法运行 Python 工作流）。
需要支持常驻进程、WebSocket 与持久化磁盘的平台。

## 2. 平台对比

| 平台                        | WebSocket | 持久化磁盘 | 休眠              | 浏览器依赖               | 结论                      |
| --------------------------- | --------- | ---------- | ----------------- | ------------------------ | ------------------------- |
| Render（Docker，Starter+）  | 支持      | 支持 Disk  | Starter 不休眠    | Docker 内可安装 Chromium | **推荐**                  |
| Render 免费 Web Service     | 支持      | 不支持     | 15 分钟无流量休眠 | 原生构建难装 Chromium    | 仅适合只读 Demo，历史会丢 |
| Fly.io（Machines + Volume） | 支持      | Volume     | 可保持 1 台常驻   | Docker 内可安装          | 可选                      |
| Railway（Volume）           | 支持      | Volume     | 视计划            | Docker 内可安装          | 可选                      |
| Vercel / Netlify            | 无长驻 WS | 无         | 函数级            | 无法运行持续工作流       | **不适用**                |

费用：Render Starter 实例与磁盘均会产生费用（以官网实时价格为准）；免费层会休眠且无磁盘。
Live 模式还会产生模型 API 费用，默认受 `BUDGET_USD`、并发与频率限制约束。

## 3. 推荐方案：Render + Docker + Disk

仓库已包含：

- `Dockerfile`：Python 3.12 + uv + Playwright Chromium。
- `render.yaml`：Demo 默认配置、`/data` 持久化磁盘、健康检查 `/api/health`。
- `.dockerignore`：排除 `.env`、`output/`、测试与本地缓存。

### 3.1 用户需要执行的操作

1. 在 GitHub 把 `Lmliya/OneGameStudio` 从 private 转为 public（仓库已推送，转换需用户确认）。
2. 在 Render 新建 Blueprint，选择该仓库，识别 `render.yaml`。
3. 确认实例计划支持 Disk（Starter 及以上），挂载 `/data`。
4. 仅当需要 Live 时，在 Render 控制台手动添加：
   - `LLM_API_KEY`（必填，服务端保存）
   - `LLM_MODEL`（必填）
   - `LLM_BASE_URL`（OpenAI 兼容网关地址）
   - `ACCESS_TOKEN`（必填，调用方需携带 `X-OGS-Token`）
   - 将 `APP_MODE` 改为 `live`、`MOCK_MODE` 改为 `false`、`DEMO_READ_ONLY` 改为 `false`
5. 部署完成后访问 `https://<service>.onrender.com/api/health`，确认返回 `mode` 与 `live_ready`。

### 3.2 环境变量

| 变量                                         | 默认               | 说明                                  |
| -------------------------------------------- | ------------------ | ------------------------------------- |
| `APP_MODE`                                   | `demo`             | `demo` 只读历史；`live` 调用真实模型  |
| `DEMO_READ_ONLY`                             | `false`            | 公开部署必须 `true`                   |
| `MOCK_MODE`                                  | `true`             | `false` 才会调用真实模型              |
| `OUTPUT_DIR`                                 | `output`           | 建议 `/data/output`                   |
| `EVOLUTION_DIR`                              | `output/evolution` | 建议 `/data/evolution`                |
| `DEMO_DIR`                                   | `demo/tasks`       | 预验证历史任务                        |
| `ACCESS_TOKEN`                               | 空                 | 非空时创建任务必须携带 `X-OGS-Token`  |
| `TASK_RATE_LIMIT_PER_MINUTE`                 | `30`               | 单 IP 每分钟任务数                    |
| `MAX_ACTIVE_TASKS`                           | `3`                | 活跃任务上限                          |
| `BUDGET_USD`                                 | `1.0`              | 单任务预算                            |
| `MAX_CONCURRENT_CALLS`                       | `2`                | 单任务并发模型调用                    |
| `LLM_API_KEY` / `LLM_MODEL` / `LLM_BASE_URL` | 空                 | Live 必填                             |
| `MODEL_PRICES`                               | 空                 | JSON 价格表；为空时费用标记为 unknown |

### 3.3 持久化与重启

- Demo 数据随镜像发布，重启不丢。
- Live 任务的 `task.json`、版本与历史 HTML 写入 `OUTPUT_DIR`；Talent 版本与经验写入 `EVOLUTION_DIR`。
- 必须把这两个目录挂到持久化磁盘，否则实例重启或重新部署后历史版本会丢失。
- 单机文件存储不支持多实例共享；横向扩容前需要改用共享文件系统或对象存储。

### 3.4 WebSocket 与代理

- Render / Fly / Railway 均支持 WebSocket 升级；不要在前面加会缓冲的静态 CDN。
- 前端使用同源相对路径，无需配置 CORS。
- 如果确实要把前端拆到独立域名，需要在 FastAPI 增加显式 CORS 白名单，不能用 `*` 搭配凭据。

## 4. Live 模式安全边界

- `LLM_API_KEY` 只存在服务端环境变量，不返回给浏览器，也不写入日志。
- Live 模式缺少密钥时，`POST /api/tasks` 直接返回 503，不会发起真实调用。
- 设置 `ACCESS_TOKEN` 后，未携带正确 `X-OGS-Token` 的请求返回 401。
- 单 IP 频率限制 + 活跃任务上限 + 单任务预算 + 模型调用超时 + 最大并发共同限制资源消耗。
- 进程内限流只在单实例内有效；多实例部署需要 Redis 等共享限流，本阶段未实现。
- 生成的 HTML 只在 `sandbox` + 严格 CSP 的 iframe 中运行，只能读取白名单产物文件。

## 5. 验收清单（部署后逐项执行）

1. 公开地址能打开首页。
2. `/api/health` 返回 `status: ok`。
3. Demo 模式徽章明确显示，历史任务自动加载。
4. 像素办公室按事件回放，员工状态来自真实历史事件。
5. 版本切换、最终版本、游戏试玩正常。
6. 刷新页面后任务与版本仍在。
7. 重启服务后历史版本仍在（验证持久化磁盘）。
8. Live 模式在提供令牌后能真实调用模型；不提供令牌时返回 401/503。
9. 日志中不出现 API Key、令牌或完整请求头。
10. `DEMO_READ_ONLY=true` 时 `POST /api/tasks` 返回 403。

## 6. 已知限制

- 没有实现多租户账号体系；Live 授权是单令牌共享，不是用户级计费。
- 进程内限流与任务队列不跨实例。
- Playwright 使镜像体积较大、冷启动较慢；纯 Demo 部署可以删掉 Chromium 安装以减小镜像。
- 免费平台休眠会中断正在执行的任务；Live 必须使用不休眠的计划。
