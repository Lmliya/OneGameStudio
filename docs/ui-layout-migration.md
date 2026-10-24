# UI 位置迁移清单（开罗式像素经营风格重设计）

> 状态：**最终版**（2026-10-24 改造完成并经浏览器回归，验证状态为实测结果）
> 基线：提交 `5189d78`，`uv run pytest -q` → 122 passed
> 原则：只改位置与外观，不改控件功能；所有元素 `id` 与事件绑定保持不变。

## 0. 基线审计结论

| 项 | 实际情况 |
|---|---|
| 技术栈 | 原生 HTML + CSS + JS + Canvas 2D，无框架、无构建，FastAPI 静态托管 `frontend/` |
| 页面结构 | 顶栏（品牌 / CEO 表单 / 状态徽章）+ 左 55% 像素办公室 + 右 45% 六标签 + 底部事件条 |
| 状态管理 | `app.js` 全局 `state`；`office.js` 内部 `Map`；`talent.js` 闭包；`localStorage.ogs_task` |
| API | health / demo / tasks（列表、创建）/ task / artifacts / history / versions / final-version / preview / employees / positions switch |
| WebSocket | `/ws/tasks/{id}`：`task.snapshot` + 增量事件，指数退避重连 1→8s |
| 办公室点击 | **不存在**（Canvas 无任何事件） |
| Engineer 主/备切换 | 只在 Employee 标签「设为启用」按钮；后端只写岗位指针，引擎不读取，不影响当前 Run |
| 自动接管开关 | **不存在**（NOT_APPLICABLE） |
| Talent 自进化 UI | 后端 API 存在，**前端无入口**（NOT_APPLICABLE，本次不新增业务界面） |
| PRD 标签 | **不存在**（`prd.md` 只在 artifacts 中，前端未渲染） |
| 取消 / 重试按钮 | **不存在**（后端有 cancel API，前端未接） |
| 版本并排比较 | **不存在**；只有 Review 标签「版本记录」按钮切换预览 |
| 窄屏 | 980px 断点单列，但顶栏表单与 Game 工具条严重挤压 |

## 1. 功能入口迁移表

| # | 控件（id） | 原位置 | 原功能 | 新位置 | 交互变化 | 关联文件 | 验证状态 |
|---|---|---|---|---|---|---|---|
| 1 | 品牌标识 `.brand` | 顶栏左 | 展示 | 顶栏左「木质招牌」 | 无 | index.html / style.css | PASS |
| 2 | 需求输入 `#requirement` | 顶栏中 | 输入需求（required, maxlength 200） | 办公室下方「CEO 指令台」 | 仅位置 | index.html / app.js | PASS |
| 3 | SOP 选择 `#sop-mode` | 顶栏中 | auto/fast/balanced/creative | CEO 指令台 | 仅位置 | 同上 | PASS |
| 4 | 来源版本 `#source-version` | 顶栏中 | 从历史任务版本继续开发 | CEO 指令台 | 仅位置 | 同上 | PASS |
| 5 | 开始开发 `#submit` | 顶栏中 | 提交表单 | CEO 指令台右侧大按钮 | 仅位置 | 同上 | PASS |
| 6 | 模式徽章 `#mode-badge` | 顶栏右 | DEMO/LIVE | 顶栏右 HUD | 仅外观 | 同上 | PASS |
| 7 | SOP 徽章 `#sop-badge` | 顶栏右 | 当前任务 SOP | 顶栏右 HUD | 仅外观 | 同上 | PASS |
| 8 | 连接徽章 `#conn` | 顶栏右 | WS 状态 | 顶栏右 HUD | 仅外观 | 同上 | PASS |
| 9 | 任务状态 `#task-status` | 顶栏右 | 任务状态 | 顶栏右 HUD | 仅外观 | 同上 | PASS |
| 10 | 任务 ID `#task-id` | 顶栏右 | 展示 | 顶栏右 HUD | 仅外观 | 同上 | PASS |
| 11 | 办公室 `#office` | 左面板 | 6 员工状态动画、气泡 | 左面板（视觉中心） | 重绘为暖色像素办公室 | office.js | PASS |
| 12 | 当前任务 `#office-task` | 办公室标题栏 | 展示需求 | 办公室标题栏 | 无 | app.js | PASS |
| 13 | （新增）员工点击热区 | 无 | — | 办公室每个工位 | 新增快捷入口：打开「员工」标签并选中该员工；Engineer 工位选中当前岗位启用角色，可在档案中切换主/备 | office.js / talent.js | PASS |
| 14 | 标签 Game | 右面板 | 预览 | 「游戏工作台」标签「游戏」 | 仅文字/外观 | index.html | PASS |
| 15 | 标签 Studio | 右面板 | SOP 指标/观点/裁决/版本记录 | 标签「企划」 | 仅文字/外观 | 同上 | PASS |
| 16 | 标签 Review | 右面板 | 审查与门禁 | 标签「审查」 | 仅文字/外观 | 同上 | PASS |
| 17 | 标签 Marketing | 右面板 | 营销素材 | 标签「宣传」 | 仅文字/外观 | 同上 | PASS |
| 18 | 标签 Employee | 右面板 | 岗位/角色/切换 | 标签「员工」 | 仅文字/外观 | 同上 | PASS |
| 19 | 标签 Logs | 右面板 | 全量事件 | 标签「日志」 | 仅文字/外观 | 同上 | PASS |
| 20 | 版本下拉 `#version-select` | Game 工具条 | 切换预览版本 | 游戏标签工具条 | 无 | app.js | PASS |
| 21 | 回退到此版本 `#rollback-version` | Game 工具条 | 设为最终版本（POST final-version） | 游戏标签工具条 | 无 | app.js | PASS |
| 22 | 刷新预览 `#reload-preview` | Game 工具条 | 重载 iframe | 游戏标签工具条 | 无 | app.js | PASS |
| 23 | 游戏 iframe `#game-frame` | Game 标签 | sandbox="allow-scripts" 隔离预览 | 游戏标签「街机屏」 | 无，沙箱属性不变 | index.html | PASS |
| 24 | Review「版本记录」按钮 | Review 标签 | 切换历史快照并跳到 Game | 审查标签 | 无 | app.js | PASS |
| 25 | Employee「设为启用」 | Employee 列表 | POST positions switch | 员工标签档案列表 | 无 | talent.js | PASS |
| 26 | Employee 角色详情 | Employee 右栏 | 基础信息/完成任务 | 员工标签「员工档案卡」 | 仅外观 | talent.js | PASS |
| 27 | 底部事件条 `#log-strip` | 页面底部 | 最近 4 条事件 | 页面底部「公司广播」 | 仅外观 | app.js | PASS |

## 2. 不存在的功能（不新增，不伪造）

PRD 标签、取消/重试按钮、版本并排比较、自动接管开关、Talent 自进化前端（经验/提案/评估/审批/回滚）、设置面板。

## 3. 最终验证说明（迁移表中各行 PASS 的依据）

- 所有原有 `id`、`data-tab` 值、事件绑定保持不变；`app.js` 只新增只读的 `window.OGS.getTask()`，并把 Slogan 颜色改为 token。
- 第 13 行热区：6 个热区的位置由 `office.js` 的 `AGENTS` 坐标生成，实测与 Canvas 逻辑坐标一致（如 coo 热区左上角为 (54, 90) = (150−96, 178−88)），1440 / 820 / 390 宽度下都能点击或触摸点开对应员工。
- 第 21 行回退：选择 `versions/<id>-v1.html` 后点击，后端 `final_version_id` 被设为该版本；选择 `history/index.v1.html` 时按后端原有语义清空指针（`None`）。
- 第 23 行 iframe：`sandbox="allow-scripts"`、`referrerpolicy="no-referrer"` 不变；在 iframe 中访问 `parent.document` 抛出 `SecurityError`。
- 第 25 行切换：在任务运行中把 Engineer 切为 Backup，任务完成后 `talent_versions.engineer` 仍为 `engineer@v1`；测试结束后岗位已切回 `engineer`。

## 4. 新增但不改业务的展示项

| 项 | 位置 | 数据来源 | 说明 |
|---|---|---|---|
| 员工像素头像 | 员工档案卡 | `Office.drawPortrait`（原创 Canvas） | 纯装饰 |
| 「当前任务实际」 | 员工档案卡 | `TaskRecord.talent_versions`（只读） | 区分「岗位默认」和「本次 Run 实际使用」 |
| 切换提示 | 员工档案卡 | 切换接口成功后显示 | 文案：正在运行的任务不受影响 |
| 工位标签「默认:主力/备用」 | Engineer 工位 | `/api/employees` 的 `active_talent` | 只读 |

## 5. 2.5D 等距办公室升级（2026-10-25，未提交）

本轮只改视觉与场景渲染，**所有功能入口位置不变**，新增入口如下：

| 控件 | 位置 | 功能 | 说明 | 验证状态 |
|---|---|---|---|---|
| `#office-zoom-out` / `#office-zoom-in` | 像素办公室标题栏右侧 | 场景缩放（0.75×–1.75×） | 新增，纯视觉 | PASS |
| `#office-zoom` | 同上 | 缩放读数（如 130%） | 新增，纯视觉 | PASS |
| `#office-reset` | 同上 | 恢复默认自适应视角 | 新增，纯视觉 | PASS |

场景变化：办公室由平面绘制升级为 2:1 等距世界坐标场景（地板/双墙/立体家具/六岗位角色/深度排序/投影生成的点击热区）。员工点击行为不变：仍打开「员工」标签并选中对应角色；Engineer 仍进入当前岗位启用角色并可切换主/备。缩放、拖动、复位不改变任何业务状态。真实浏览器逐热区点击验收 6/6 PASS，截图见 `docs/screenshots/pixel-ui/`。
