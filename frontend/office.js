// 像素办公室：Canvas 2D 绘制四名员工、工作桌与状态气泡。
// 员工状态只由后端 agent.status_changed 事件驱动，本文件不含任何计时器模拟进度。

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
      y: 168,
    },
    {
      id: "engineer",
      name: "ENGINEER",
      role: "游戏工程师",
      color: "#f0883e",
      hair: "#7a3d12",
      skin: "#f2c9a0",
      x: 520,
      y: 168,
    },
    {
      id: "reviewer",
      name: "REVIEWER",
      role: "质量审查官",
      color: "#7ee787",
      hair: "#255c2c",
      skin: "#f2c9a0",
      x: 150,
      y: 372,
    },
    {
      id: "marketer",
      name: "MARKETER",
      role: "营销负责人",
      color: "#c792ea",
      hair: "#4a2a6a",
      skin: "#f2c9a0",
      x: 520,
      y: 372,
    },
  ];

  // 员工状态：值只会在 setAgent() 中被后端事件覆盖
  const state = new Map(
    AGENTS.map((a) => [a.id, { status: "idle", message: "" }]),
  );
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

  ctx.imageSmoothingEnabled = false;

  function px(x, y, w, h, color) {
    ctx.fillStyle = color;
    ctx.fillRect(Math.round(x), Math.round(y), Math.round(w), Math.round(h));
  }

  function drawRoom() {
    // 地板：棋盘格
    for (let y = 70; y < H; y += 40) {
      for (let x = 0; x < W; x += 40) {
        const dark = ((x / 40 + y / 40) | 0) % 2 === 0;
        px(x, y, 40, 40, dark ? "#232838" : "#1d2230");
      }
    }
    // 后墙
    px(0, 0, W, 70, "#151a27");
    px(0, 66, W, 4, "#0b0e16");
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
    // 墙上任务牌
    if (requirement) {
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
  }

  function drawDesk(agent, phase) {
    const { x, y } = agent;
    const st = state.get(agent.id);
    const color = STATUS_COLOR[st.status];
    const working = ["working", "reviewing", "fixing"].includes(st.status);

    // 桌腿与桌面
    px(x - 84, y + 42, 168, 10, "#3a2a1a");
    px(x - 84, y + 52, 8, 26, "#2b1f13");
    px(x + 76, y + 52, 8, 26, "#2b1f13");
    px(x - 90, y + 30, 180, 14, "#6b4b2a");
    px(x - 90, y + 30, 180, 4, "#8a6338");

    // 显示器：工作中屏幕有光标闪烁
    px(x - 62, y - 24, 66, 52, "#0b0e16");
    px(x - 66, y - 28, 74, 56, "#3a4460");
    px(x - 62, y - 24, 66, 48, working ? "#0f2033" : "#0d131d");
    if (working) {
      const glow = 0.35 + 0.25 * Math.sin(phase * 6);
      ctx.globalAlpha = glow;
      px(x - 62, y - 24, 66, 48, color);
      ctx.globalAlpha = 1;
      const lines = 4;
      for (let i = 0; i < lines; i++) {
        const ly = y - 18 + i * 9;
        const width = 18 + ((i * 13 + ((phase * 20) | 0)) % 34);
        px(x - 54, ly, width, 3, "#7ee787");
      }
      px(x - 4, y + 2, 4, 10, "#3a2a1a"); // 支架
    }

    // 键盘
    px(x + 18, y + 20, 58, 10, "#2c3444");
    px(x + 22, y + 22, 50, 4, "#455268");

    // 椅子
    px(x - 18, y + 34, 40, 8, "#2b2f45");
    px(x - 16, y + 42, 6, 16, "#22263a");
    px(x + 14, y + 42, 6, 16, "#22263a");

    // 咖啡杯 / 盆栽点缀
    px(x + 62, y + 16, 10, 14, st.status === "working" ? "#ffd866" : "#8490b0");
    px(x - 78, y + 8, 10, 22, "#255c2c");
    px(x - 80, y + 26, 14, 8, "#6b4b2a");
  }

  function drawCharacter(agent, phase) {
    const { x, y } = agent;
    const st = state.get(agent.id);
    const working = ["working", "reviewing", "fixing"].includes(st.status);
    const bob = working ? Math.sin(phase * 5) * 2 : Math.sin(phase * 1.6) * 1;
    const shake = st.status === "fixing" ? Math.sin(phase * 26) * 2 : 0;
    const cx = x - 26 + shake;
    const cy = y - 6 + bob;

    // 身体
    px(cx - 12, cy - 30, 26, 26, agent.color);
    px(cx - 12, cy - 30, 26, 4, "#ffffff22");
    // 手臂：工作时交替抬起
    const armY = working ? Math.sin(phase * 10) * 3 : 0;
    px(cx - 18, cy - 26 + armY, 6, 16, agent.color);
    px(cx + 14, cy - 26 - armY, 6, 16, agent.color);
    // 头
    px(cx - 10, cy - 50, 22, 20, agent.skin);
    px(cx - 10, cy - 56, 22, 8, agent.hair);
    px(cx - 10, cy - 48, 3, 10, agent.hair);
    px(cx + 9, cy - 48, 3, 10, agent.hair);
    // 眼睛
    px(cx - 5, cy - 42, 3, 3, "#1b1f2b");
    px(cx + 4, cy - 42, 3, 3, "#1b1f2b");
    // 状态装饰
    if (st.status === "idle") {
      ctx.fillStyle = "#8490b0";
      ctx.font = "10px ui-monospace, monospace";
      ctx.textAlign = "left";
      ctx.fillText("z", cx + 14, cy - 58 - Math.abs(Math.sin(phase)) * 3);
    }
    if (st.status === "error") {
      px(cx - 2, cy - 68, 4, 10, "#ff6b81");
      px(cx - 2, cy - 54, 4, 4, "#ff6b81");
    }

    // 姓名与状态
    ctx.textAlign = "center";
    ctx.font = "bold 11px ui-monospace, monospace";
    ctx.fillStyle = "#e8ecff";
    ctx.fillText(`${agent.name} · ${agent.role}`, x, y + 82);
    ctx.font = "10px ui-monospace, monospace";
    ctx.fillStyle = STATUS_COLOR[st.status];
    ctx.fillText(STATUS_TEXT[st.status] || st.status, x, y + 96);
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
    if (
      !["working", "reviewing", "fixing", "error"].includes(st.status) ||
      !st.message
    ) {
      return;
    }
    const lines = wrap(st.message, 13);
    const boxW = Math.max(...lines.map((l) => [...l].length)) * 12 + 16;
    const boxH = lines.length * 15 + 12;
    const bx = Math.min(Math.max(agent.x - boxW / 2, 4), W - boxW - 4);
    const by = agent.y - 118 - (lines.length - 1) * 6;

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
        drawCharacter(agent, phase);
      });
    AGENTS.forEach(drawBubble);
    requestAnimationFrame(frame);
  }

  function setAgent(agentId, status, message) {
    const entry = state.get(agentId);
    if (!entry) return;
    if (status) entry.status = status;
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
  }

  requestAnimationFrame(frame);

  return { setAgent, setRequirement, resetAgents };
})();
