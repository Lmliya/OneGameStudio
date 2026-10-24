// 像素办公室：Canvas 2D 绘制四名员工、办公桌与装饰。
// 员工状态只由后端 agent.status_changed 事件驱动，本文件不含任何计时器模拟进度。
// 同一时刻最多只有一名员工播放动画：由 activeAgent 记录当前焦点。

const Office = (() => {
  const canvas = document.getElementById("office");
  const ctx = canvas.getContext("2d");
  const W = canvas.width;
  const H = canvas.height;

  const AGENTS = [
    {
      id: "coo",
      name: "COO",
      role: "产品经理",
      color: "#58a6ff",
      hair: "#1f3b6e",
      skin: "#f2c9a0",
      x: 150,
      y: 156,
    },
    {
      id: "engineer",
      name: "ENGINEER",
      role: "游戏工程师",
      color: "#f0883e",
      hair: "#7a3d12",
      skin: "#f2c9a0",
      x: 520,
      y: 156,
    },
    {
      id: "reviewer",
      name: "REVIEWER",
      role: "质量审查官",
      color: "#7ee787",
      hair: "#255c2c",
      skin: "#f2c9a0",
      x: 150,
      y: 380,
    },
    {
      id: "marketer",
      name: "MARKETER",
      role: "营销负责人",
      color: "#c792ea",
      hair: "#4a2a6a",
      skin: "#f2c9a0",
      x: 520,
      y: 380,
    },
  ];

  // 员工状态：值只会在 setAgent() 中被后端事件覆盖
  const state = new Map(
    AGENTS.map((a) => [a.id, { status: "idle", message: "" }]),
  );
  // 当前唯一允许播放动画的员工；同一时刻只可能有一个
  let activeAgent = null;
  let requirement = "";

  const STATUS_TEXT = {
    idle: "待命",
    working: "工作中",
    reviewing: "审查中",
    fixing: "修复中",
    completed: "已完成",
    error: "出错",
  };

  const STATUS_COLOR = {
    idle: "#8490b0",
    working: "#58a6ff",
    reviewing: "#7ee787",
    fixing: "#ffd866",
    completed: "#7ee787",
    error: "#ff6b81",
  };

  // 会让人物产生动作的状态
  const ACTIVE = new Set(["working", "reviewing", "fixing"]);
  // 会显示对话气泡的状态
  const SPEAKING = new Set(["working", "reviewing", "fixing", "error"]);

  ctx.imageSmoothingEnabled = false;

  function px(x, y, w, h, color) {
    ctx.fillStyle = color;
    ctx.fillRect(Math.round(x), Math.round(y), Math.round(w), Math.round(h));
  }

  // ---------- 房间与装饰 ----------

  function drawFloor() {
    for (let y = 70; y < H; y += 40) {
      for (let x = 0; x < W; x += 40) {
        const dark = ((x / 40 + y / 40) | 0) % 2 === 0;
        px(x, y, 40, 40, dark ? "#232838" : "#1d2230");
      }
    }
  }

  function drawWall() {
    px(0, 0, W, 70, "#151a27");
    px(0, 62, W, 8, "#10141f");
    px(0, 62, W, 2, "#2b3347");

    // 窗户（夜色 + 星星）
    [110, 380, 650].forEach((wx) => {
      px(wx, 14, 120, 44, "#0b1020");
      px(wx, 14, 120, 4, "#3a4460");
      px(wx, 54, 120, 4, "#3a4460");
      px(wx, 14, 4, 44, "#3a4460");
      px(wx + 116, 14, 4, 44, "#3a4460");
      px(wx + 24, 24, 3, 3, "#e8ecff");
      px(wx + 62, 34, 2, 2, "#ffe9a3");
      px(wx + 92, 22, 2, 2, "#e8ecff");
    });

    // 左侧海报
    px(20, 10, 66, 46, "#3a4460");
    px(23, 13, 60, 40, "#1f2536");
    px(38, 24, 10, 7, "#7ee787");
    px(48, 24, 10, 7, "#58a6ff");
    px(30, 37, 46, 3, "#3a4460");
    px(34, 44, 34, 3, "#3a4460");

    // 任务牌左侧的置物架
    px(238, 34, 64, 5, "#6b4b2a");
    px(238, 34, 64, 2, "#8a6338");
    ["#ff6b81", "#ffd866", "#7ee787", "#58a6ff", "#c792ea"].forEach(
      (color, index) => px(242 + index * 11, 20, 8, 14, color),
    );

    // 任务牌右侧的白板与便签
    px(580, 10, 62, 46, "#3a4460");
    px(583, 13, 56, 40, "#dfe6f5");
    px(590, 20, 14, 10, "#ffd866");
    px(607, 20, 14, 10, "#7ee787");
    px(590, 34, 31, 3, "#3a4460");
    px(590, 41, 22, 3, "#3a4460");

    // 右侧挂钟
    px(796, 12, 36, 36, "#3a4460");
    px(799, 15, 30, 30, "#0b1020");
    px(813, 20, 2, 10, "#e8ecff");
    px(813, 28, 8, 2, "#e8ecff");
    px(813, 15, 3, 3, "#ffd866");
  }

  function drawRug() {
    px(225, 252, 230, 114, "#2a3247");
    px(232, 259, 216, 100, "#323b52");
    // 菱形花纹
    [282, 340, 398].forEach((x) => {
      px(x, 292, 12, 12, "#3e4a66");
      px(x + 3, 295, 6, 6, "#2a3247");
    });
  }

  function drawCat() {
    // 睡在地毯上的猫（静态装饰）
    px(330, 318, 46, 16, "#e0a45c");
    px(330, 318, 46, 4, "#f0b874");
    px(368, 312, 18, 16, "#e0a45c");
    px(369, 307, 5, 6, "#e0a45c");
    px(380, 307, 5, 6, "#e0a45c");
    px(318, 324, 14, 4, "#e0a45c");
    px(314, 318, 6, 8, "#e0a45c");
    px(338, 322, 3, 10, "#c98a45");
    px(346, 322, 3, 10, "#c98a45");
    px(374, 318, 3, 2, "#1b1f2b");
    px(381, 318, 3, 2, "#1b1f2b");
  }

  function drawBookshelf() {
    px(8, 96, 46, 112, "#3a2a1a");
    px(8, 96, 46, 4, "#6b4b2a");
    [132, 168, 204].forEach((shelfY, row) => {
      px(8, shelfY, 46, 4, "#6b4b2a");
      const colors = ["#ff6b81", "#ffd866", "#7ee787", "#58a6ff", "#c792ea"];
      for (let i = 0; i < 5; i++) {
        const color = colors[(row + i) % colors.length];
        px(11 + i * 8, shelfY - 16 + (i % 2) * 2, 6, 14, color);
      }
    });
  }

  function drawCooler() {
    // 饮水机
    px(834, 108, 28, 34, "#9fd3ff");
    px(838, 104, 20, 8, "#cfeaff");
    px(826, 142, 44, 56, "#c9d4e8");
    px(826, 142, 44, 4, "#eef3ff");
    px(834, 158, 10, 6, "#58a6ff");
    px(852, 158, 10, 6, "#ff6b81");
    px(832, 196, 10, 8, "#22263a");
    px(854, 196, 10, 8, "#22263a");
  }

  function drawFloorLamp() {
    const lx = 690;
    px(lx + 18, 250, 4, 164, "#3a4460");
    px(lx, 242, 40, 10, "#ffd866");
    px(lx + 4, 252, 32, 2, "#c9a83f");
    px(lx + 10, 414, 16, 6, "#2b3145");
  }

  function drawPlant(x, y) {
    px(x, y + 20, 26, 18, "#6b4b2a");
    px(x, y + 20, 26, 4, "#8a6338");
    px(x + 10, y - 6, 6, 26, "#255c2c");
    px(x, y + 2, 12, 8, "#2f7a3a");
    px(x + 16, y - 2, 10, 8, "#255c2c");
    px(x + 2, y - 8, 10, 8, "#2f7a3a");
  }

  function drawBin() {
    px(643, 444, 36, 6, "#3a4460");
    px(646, 450, 30, 34, "#2b3145");
    px(652, 458, 2, 22, "#1b1f2b");
    px(662, 458, 2, 22, "#1b1f2b");
    px(672, 458, 2, 22, "#1b1f2b");
  }

  function drawTaskBoard() {
    if (!requirement) return;
    px(W / 2 - 130, 16, 260, 30, "#1f2536");
    px(W / 2 - 130, 16, 260, 2, "#3a4460");
    px(W / 2 - 130, 44, 260, 2, "#3a4460");
    ctx.fillStyle = "#e8ecff";
    ctx.font = "12px ui-monospace, monospace";
    ctx.textAlign = "center";
    // 按实测宽度截断，避免长需求溢出任务牌
    const full = `任务：${requirement}`;
    let text = full;
    while (text.length > 4 && ctx.measureText(text).width > 238) {
      text = text.slice(0, -1);
    }
    if (text !== full) text = text.slice(0, -1) + "…";
    ctx.fillText(text, W / 2, 36);
  }

  function drawRoom() {
    drawFloor();
    drawWall();
    drawRug();
    drawBookshelf();
    drawCooler();
    drawFloorLamp();
    drawPlant(24, 428);
    drawPlant(824, 420);
    drawBin();
    drawCat();
    drawTaskBoard();
  }

  // ---------- 办公桌与人物 ----------

  function drawDesk(agent, phase) {
    const { x, y } = agent;
    const st = state.get(agent.id);
    const focus = activeAgent === agent.id && ACTIVE.has(st.status);

    // 地面投影
    px(x - 96, y + 74, 192, 6, "#0a0d14");

    // 桌腿与桌面
    px(x - 84, y + 40, 10, 40, "#2b1f13");
    px(x + 74, y + 40, 10, 40, "#2b1f13");
    px(x - 94, y + 26, 188, 16, "#6b4b2a");
    px(x - 94, y + 26, 188, 4, "#8a6338");
    px(x - 94, y + 38, 188, 4, "#4a3219");

    // 显示器：员工面向桌子，观众看到的是背面
    px(x - 66, y - 30, 74, 56, "#3a4460");
    px(x - 62, y - 26, 66, 44, "#141a26");
    for (let i = 0; i < 4; i++) px(x - 50, y - 18 + i * 8, 30, 2, "#222a3a");
    px(x + 4, y + 10, 4, 4, focus ? "#7ee787" : "#3a4460");
    px(x - 10, y + 26, 24, 4, "#2b3145");
    px(x - 16, y + 30, 36, 3, "#222a3a");

    // 工作时的屏幕背光
    if (focus) {
      ctx.globalAlpha = 0.1 + 0.06 * Math.sin(phase * 5);
      px(x - 74, y - 38, 90, 68, STATUS_COLOR[st.status]);
      ctx.globalAlpha = 1;
    }

    // 键盘与鼠标
    px(x + 22, y + 28, 54, 10, "#2c3444");
    px(x + 26, y + 30, 46, 4, "#455268");
    px(x + 80, y + 30, 8, 10, "#2c3444");

    // 台灯
    px(x - 88, y - 2, 4, 30, "#3a4460");
    px(x - 96, y - 10, 20, 8, "#ffd866");
    px(x - 96, y - 10, 20, 2, "#ffe9a3");
    if (focus) {
      ctx.globalAlpha = 0.1;
      px(x - 102, y - 2, 34, 34, "#ffd866");
      ctx.globalAlpha = 1;
    }

    // 文件、咖啡杯与桌面小盆栽
    px(x + 64, y - 2, 14, 12, "#dfe6f5");
    px(x + 66, y, 10, 2, "#3a4460");
    px(x + 66, y + 4, 8, 2, "#3a4460");
    px(x + 78, y + 4, 8, 10, "#3a4460");
    px(x - 84, y + 8, 12, 10, "#6b4b2a");
    px(x - 82, y - 2, 8, 10, "#2f7a3a");
  }

  function drawChair(agent) {
    const { x, y } = agent;
    // 椅背两侧会从人物身后露出来
    px(x - 28, y + 30, 56, 30, "#232a3c");
    px(x - 28, y + 30, 56, 4, "#313a50");
    // 坐垫
    px(x - 30, y + 58, 60, 8, "#2b3145");
    px(x - 30, y + 58, 60, 2, "#3a4460");
    // 椅腿
    px(x - 26, y + 66, 8, 20, "#1d2230");
    px(x + 18, y + 66, 8, 20, "#1d2230");
  }

  function drawCharacter(agent, phase) {
    const { x, y } = agent;
    const st = state.get(agent.id);
    // 只有当前焦点员工会动；其余人完全静止
    const focus = activeAgent === agent.id && ACTIVE.has(st.status);
    const bob = focus ? Math.sin(phase * 4.5) * 1.5 : 0;
    const shake =
      focus && st.status === "fixing" ? Math.sin(phase * 24) * 1.5 : 0;
    const cx = Math.round(x + shake);
    const cy = y + 14 + bob; // 肩部基准

    // 腿与鞋（坐在椅子前沿）
    px(cx - 16, y + 60, 12, 24, "#2b3348");
    px(cx + 4, y + 60, 12, 24, "#2b3348");
    px(cx - 18, y + 84, 16, 6, "#1b1f2b");
    px(cx + 2, y + 84, 16, 6, "#1b1f2b");

    // 背部躯干
    px(cx - 20, cy, 40, 44, agent.color);
    px(cx - 20, cy, 40, 4, "#ffffff22");
    px(cx - 20, cy + 40, 40, 4, "#00000022");
    px(cx - 2, cy + 6, 4, 30, "#00000018");

    // 手臂：工作时左右交替敲键盘
    const arm = focus ? Math.sin(phase * 10) * 3 : 0;
    px(cx - 27, cy + 8 + arm, 7, 24, agent.color);
    px(cx + 20, cy + 8 - arm, 7, 24, agent.color);
    px(cx - 27, cy + 30 + arm, 7, 6, agent.skin);
    px(cx + 20, cy + 30 - arm, 7, 6, agent.skin);

    // 脖子
    px(cx - 4, cy - 8, 8, 8, agent.skin);

    // 后脑勺：背对观众，不画五官
    px(cx - 11, cy - 28, 22, 22, agent.skin);
    px(cx - 11, cy - 30, 22, 12, agent.hair);
    px(cx - 13, cy - 22, 4, 16, agent.hair);
    px(cx + 9, cy - 22, 4, 16, agent.hair);
    px(cx - 2, cy - 18, 3, 3, "#00000022");

    // 耳机，强调背对视角
    px(cx - 15, cy - 26, 30, 4, "#1b1f2b");
    px(cx - 16, cy - 22, 5, 12, "#2b3145");
    px(cx + 11, cy - 22, 5, 12, "#2b3145");

    // 状态装饰
    if (st.status === "error") {
      px(cx - 2, cy - 46, 4, 10, "#ff6b81");
      px(cx - 2, cy - 32, 4, 4, "#ff6b81");
    }

    // 姓名与状态（放在椅子下方，避开下一排的气泡）
    ctx.textAlign = "center";
    ctx.font = "bold 11px ui-monospace, monospace";
    ctx.fillStyle = "#e8ecff";
    ctx.fillText(`${agent.name} · ${agent.role}`, x, y + 106);
    ctx.font = "10px ui-monospace, monospace";
    ctx.fillStyle = STATUS_COLOR[st.status];
    ctx.fillText(STATUS_TEXT[st.status] || st.status, x, y + 120);
  }

  function wrap(text, max) {
    const chars = [...text];
    const lines = [];
    let line = "";
    for (const ch of chars) {
      line += ch;
      if ([...line].length >= max) {
        lines.push(line);
        line = "";
      }
    }
    if (line) lines.push(line);
    return lines.slice(0, 2);
  }

  function drawBubble(agent) {
    const st = state.get(agent.id);
    // 只在"正在干活"或出错时冒泡，已完成/待命不长期占用画面
    if (!SPEAKING.has(st.status) || !st.message) return;
    const lines = wrap(st.message, 13);
    const boxW = Math.max(...lines.map((l) => [...l].length)) * 12 + 16;
    const boxH = lines.length * 15 + 12;
    const bx = Math.min(Math.max(agent.x - boxW / 2, 4), W - boxW - 4);
    const by = agent.y - 92 - (lines.length - 1) * 6;

    px(bx + 2, by + 2, boxW, boxH, "#05060a");
    px(bx, by, boxW, boxH, "#1f2536");
    px(bx, by, boxW, 2, STATUS_COLOR[st.status]);
    px(bx, by + boxH - 2, boxW, 2, STATUS_COLOR[st.status]);
    px(bx, by, 2, boxH, STATUS_COLOR[st.status]);
    px(bx + boxW - 2, by, 2, boxH, STATUS_COLOR[st.status]);
    // 小尾巴
    px(bx + boxW / 2 - 4, by + boxH, 8, 4, STATUS_COLOR[st.status]);
    px(bx + boxW / 2 - 4, by + boxH + 4, 4, 3, STATUS_COLOR[st.status]);

    ctx.fillStyle = "#e8ecff";
    ctx.font = "11px ui-monospace, monospace";
    ctx.textAlign = "left";
    lines.forEach((line, i) => ctx.fillText(line, bx + 8, by + 16 + i * 15));
  }

  function frame(ts) {
    const phase = ts / 1000;
    ctx.clearRect(0, 0, W, H);
    drawRoom();
    // 按 y 排序，保证下排角色遮挡关系正确
    [...AGENTS]
      .sort((a, b) => a.y - b.y)
      .forEach((agent) => {
        drawDesk(agent, phase);
        drawChair(agent);
        drawCharacter(agent, phase);
      });
    AGENTS.forEach(drawBubble);
    requestAnimationFrame(frame);
  }

  function setAgent(agentId, status, message) {
    const entry = state.get(agentId);
    if (!entry) return;
    if (status) {
      entry.status = status;
      // 同一时刻只允许一名员工成为动画焦点
      if (ACTIVE.has(status)) activeAgent = agentId;
      else if (activeAgent === agentId) activeAgent = null;
    }
    if (message) entry.message = message;
  }

  function setRequirement(text) {
    requirement = (text || "").trim();
  }

  function resetAgents() {
    state.forEach((entry) => {
      entry.status = "idle";
      entry.message = "";
    });
    activeAgent = null;
  }

  requestAnimationFrame(frame);

  return { setAgent, setRequirement, resetAgents };
})();
