# OneGameStudio 路演演示

这是可离线打开的原生 HTML 演示稿，包含内嵌 CSS 与 JavaScript。演示使用项目随附的截图和已存档小游戏，不访问 CDN 或模型服务。

## 打开方式

在浏览器中打开 `pitch/pitch.html` 即可。若浏览器限制本地文件 iframe，可在项目根目录启动静态服务器：

```bash
python3 -m http.server 8000
```

然后打开 `http://127.0.0.1:8000/pitch/pitch.html`。保持 `pitch/assets/` 和 `demo/tasks/` 目录在项目内原有位置；页面引用 `assets/office-1920x1080.png` 和已存档的贪吃蛇 HTML。

## 演示操作

- 左右方向键切换场景；空格进入下一场；底部按钮和进度点也可鼠标点击。
- `F` 或“全屏”按钮切换全屏；`Esc` 关闭员工档案或讲者备注。
- “讲者备注 N”打开隐藏的演示者提示；普通观众视图默认不显示。
- “重播”回到首页并重置场景动画。
- 场景 3：点击岗位查看员工档案；Engineer 可切换 Primary / Backup。
- 场景 4：点击“开始回放”按记录顺序点亮流程；右侧游戏是本地存档 HTML，用方向键或 WASD 控制、空格暂停、Enter 在结束后重开。
- 场景 5：点击 v1 / v2 查看对应记录说明；“播放机制预览”只演示规划中的自动接管，不会调用 Agent。
- 场景 6：点击 FAST / BALANCED / CREATIVE 切换流程图；可重新播放 Talent 进化机制示意。

游戏 iframe 独立接收方向键，不会触发演示翻页。浏览器处于游戏焦点时，先点击演示页面空白处再继续翻页。

## 数据来源与真实性

- **真实项目素材**：开场与办公室照片取自 `docs/screenshots/pixel-ui/office-1920x1080.png`；演示中副本位于 `pitch/assets/`。员工岗位、SOP、API、门禁、审查、版本与 Talent 进化机制来自当前代码和项目文档。
- **REPLAY**：场景 4 回放 `demo/tasks/b1ee53da7c4c/task.json` 的已存档历史任务（2026-10-24）。该任务的供应商是 Mock，不是现场模型执行；记录含 5 次 Mock 调用、39.75 秒记录耗时、Reviewer 首轮 ITERATE、一次修复、复审 PASS。token 标记为 estimated。
- **REPLAY / GATE**：`gate.json` 记录 9 项 PASS、`prd_acceptance` 的“随机食物”检查为 UNVERIFIED；演示原样保留这一限制。
- **可玩产物**：场景 4 内嵌 `demo/tasks/b1ee53da7c4c/versions/b1ee53da7c4c-v1.html`。这是已存档任务的可运行 HTML，不代表本次路演现场生成。
- **SAMPLE**：场景 5 的 v2 版本关系仅作示例。存档中的 v2 元数据说明它是 Demo 数据；随附 HTML 与 v1 相同，页面不声称有代码差异或真实开发事件。
- **DEMO**：岗位档案点击、任务回放动画、版本说明切换、SOP 流程切换和 Talent 进化动画都由本地页面预设，不会调用后端或模型。
- **PLANNED**：Primary 失败后由 Backup Engineer 自动接管尚未接入任务执行流程。场景 5 的接管动画是机制预览；工程师角色目前可手动切换。
- **已实现但当前不是实测记录**：BALANCED / CREATIVE 编排、Talent 经验提取、确定性 Mock 回归、批准与回滚 API。随仓库 Demo 快照仅含 Talent v1；自进化 UI 目前不在正式前端。
- **LIVE**：本路演没有 LIVE 模型运行。真实模型端到端与真实模型 Talent 评估尚未验证。

## 验证范围

已完成静态 HTML 解析、7 个场景结构检查、ID 唯一性检查、本地素材路径检查，以及内嵌 JavaScript 的 `node --check` 语法检查。没有声称本 HTML 经过项目 pytest 套件测试。

本次 Codex 浏览器策略拒绝打开 `file://` 页面，并明确禁止通过其他浏览器入口或本地服务绕过限制，因此无法完成实际浏览器交互、全屏、1280×720 溢出和控制台验证。对应浏览器验收仍需在本机直接打开页面完成；项目文档中已有的历史浏览器结果不等于本演示稿的当前验收结果。

## 配置项目链接

- GitHub 链接位于 `pitch.html` 的 `https://github.com/Lmliya/OneGameStudio` 按钮。该仓库目前为私有；如仓库迁移，请替换该 `href` 和旁边的仓库文字。
- 在线 Demo 尚未部署。获得正式 URL 后，将“在线 Demo · 待部署”按钮改为 `<a href="真实地址">打开在线 Demo ↗</a>`，并更新场景 7 的地址说明。当前按钮明确禁用。
