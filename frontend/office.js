// 像素办公室：Canvas 2D 绘制六名原创像素员工、工位与暖色办公室装饰。
// 员工状态只由后端 agent.status_changed 事件驱动，本文件不含任何计时器模拟进度。
// 同一时刻最多只有一名员工播放工作动画：由 activeAgent 记录当前焦点。
// 点击热区与人物绘制共用 AGENTS 坐标，保证“画在哪里就能点在哪里”。

const Office = (() => {
  const canvas = document.getElementById("office");
  const ctx = canvas.getContext("2d");
  const W = canvas.width;
  const H = canvas.height;
  const FONT = 'ui-monospace, Menlo, "PingFang SC", "Microsoft YaHei", monospace';
  const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)");

  // 3 列 × 2 行：上排 COO / CREATIVE / DELIVERY，下排 ENGINEER / REVIEWER / MARKETER
  // x/y 是桌面中心；热区 = 以 (x, y) 为基准的 HIT 矩形
  const AGENTS = [
    { id: "coo", talent: "coo", name: "COO", role: "产品经理", color: "#5a9fd4", dark: "#2c6496", hair: "#3b2a20", x: 150, y: 178 },
    { id: "creative", talent: "creative", name: "CREATIVE", role: "创意总监", color: "#f08a5d", dark: "#b4552e", hair: "#c0392b", x: 440, y: 178 },
    { id: "delivery", talent: "delivery", name: "DELIVERY", role: "交付总监", color: "#4fb3a9", dark: "#2a7a72", hair: "#2b2b3a", x: 730, y: 178 },
    { id: "engineer", talent: "engineer", name: "ENGINEER", role: "游戏工程师", color: "#f2b134", dark: "#b97a12", hair: "#5a3720", x: 150, y: 384 },
    { id: "reviewer", talent: "reviewer", name: "REVIEWER", role: "质量审查官", color: "#6fbf73", dark: "#2f7a3e", hair: "#7a4a24", x: 440, y: 384 },
    { id: "marketer", talent: "marketer", name: "MARKETER", role: "营销负责人", color: "#b07fd6", dark: "#6a3f92", hair: "#e8c35a", x: 730, y: 384 },
  ];
  const HIT = { left: 96, top: 88, width: 192, height: 156 };

  // 头像外观（含不占工位的备用工程师）
  const LOOKS = Object.fromEntries(AGENTS.map((a) => [a.talent, a]));
  LOOKS.backup_engineer = { color: "#e07a9a", dark: "#a34766", hair: "#2d6a8a", glasses: true };

  const SKIN = "#f6cfa4";
  const SKIN_SHADE = "#e3ae80";
  const INK = "#45291a";

  // 员工状态：值只会在 setAgent() 中被后端事件覆盖
  const state = new Map(
    AGENTS.map((a) => [a.id, { status: "idle", message: "", speech: "", tag: "" }]),
  );
  let activeAgent = null;
  let hovered = null;
  let requirement = "";
  let selectHandler = null;

  const STATUS_TEXT = {
    idle: "待命",
    working: "工作中",
    reviewing: "审查中",
    fixing: "修复中",
    completed: "已完成",
    error: "出错",
  };

  const STATUS_COLOR = {
    idle: "#a88a6c",
    working: "#2c6496",
    reviewing: "#2f7a3e",
    fixing: "#b97a12",
    completed: "#2f7a3e",
    error: "#9c3a31",
  };

  const STATUS_FILL = {
    idle: "#efd39a",
    working: "#cfe4f5",
    reviewing: "#d6efcf",
    fixing: "#fbe3a6",
    completed: "#d6efcf",
    error: "#f4cdc6",
  };

  const ACTIVE = new Set(["working", "reviewing", "fixing"]);
  const SPEAKING = new Set(["working", "reviewing", "fixing", "error"]);

  ctx.imageSmoothingEnabled = false;

  function px(x, y, w, h, color, c = ctx) {
    c.fillStyle = color;
    c.fillRect(Math.round(x), Math.round(y), Math.round(w), Math.round(h));
  }

  // 带 3px 深色描边的像素方框
  function box(x, y, w, h, fill, border = INK, c = ctx) {
    px(x, y, w, h, border, c);
    px(x + 2, y + 2, w - 4, h - 4, fill, c);
  }

  // ---------- 静态房间（只绘制一次到离屏画布） ----------

  function drawWall(c) {
    // 奶油色条纹墙纸 + 木质踢脚线
    px(0, 0, W, 100, "#f6e3c0", c);
    for (let x = 0; x < W; x += 24) px(x, 0, 12, 100, "#f1d9ae", c);
    px(0, 92, W, 12, "#a8693a", c);
    px(0, 92, W, 3, "#c98a50", c);
    px(0, 102, W, 2, "#5a3720", c);

    // 两扇白天的窗户（蓝天 + 白云）
    [36, 650].forEach((wx) => {
      box(wx, 14, 132, 62, "#9fd3f0", "#7a4a24", c);
      px(wx + 3, 60, 126, 13, "#bfe3f6", c);
      px(wx + 64, 14, 4, 62, "#7a4a24", c);
      px(wx + 16, 26, 26, 8, "#ffffff", c);
      px(wx + 22, 22, 14, 4, "#ffffff", c);
      px(wx + 84, 36, 30, 8, "#ffffff", c);
      px(wx + 92, 32, 12, 4, "#ffffff", c);
      px(wx - 4, 74, 140, 6, "#c98a50", c);
    });

    // 原创海报：像素手柄
    box(186, 16, 56, 62, "#fff8e6", "#7a4a24", c);
    px(196, 38, 36, 18, "#d2655a", c);
    px(201, 44, 10, 3, "#fff8e6", c);
    px(204, 41, 3, 9, "#fff8e6", c);
    px(220, 42, 4, 4, "#f2b134", c);
    px(226, 48, 4, 4, "#6fbf73", c);
    px(196, 62, 36, 3, "#c08548", c);

    // 奖杯置物架
    px(806, 50, 66, 6, "#7a4a24", c);
    px(814, 30, 14, 14, "#f2b134", c);
    px(818, 44, 6, 6, "#b97a12", c);
    px(836, 34, 10, 16, "#5a9fd4", c);
    px(852, 28, 12, 22, "#6fbf73", c);

    // 挂钟
    box(600, 20, 36, 36, "#fff8e6", "#7a4a24", c);
    px(617, 27, 2, 12, INK, c);
    px(617, 37, 9, 2, INK, c);
  }

  function drawFloor(c) {
    // 横向木地板，错缝排列
    for (let row = 0, y = 104; y < H; row++, y += 16) {
      px(0, y, W, 16, row % 2 ? "#d9a86a" : "#d2a062", c);
      px(0, y + 15, W, 1, "#b98447", c);
      const offset = (row % 3) * 46;
      for (let x = offset; x < W; x += 138) px(x, y, 2, 15, "#b98447", c);
    }
    // 墙角阴影
    px(0, 104, W, 6, "rgba(90,55,32,0.18)", c);
  }

  function drawRunner(c) {
    // 两排工位之间的走道地毯
    box(60, 262, 760, 32, "#d97a5f", "#9c4a34", c);
    for (let x = 76; x < 810; x += 28) {
      px(x, 274, 8, 8, "#f2c08a", c);
    }
  }

  function drawBookshelf(c) {
    box(4, 112, 42, 108, "#a8693a", "#5a3720", c);
    const colors = ["#d2655a", "#f2b134", "#6fbf73", "#5a9fd4", "#b07fd6"];
    [146, 180, 214].forEach((shelfY, row) => {
      px(6, shelfY, 38, 4, "#5a3720", c);
      for (let i = 0; i < 4; i++) {
        px(9 + i * 9, shelfY - 22 + (i % 2) * 3, 7, 22 - (i % 2) * 3, colors[(row + i) % 5], c);
      }
    });
  }

  function drawCooler(c) {
    px(842, 112, 26, 30, "#9fd3f0", c);
    px(846, 108, 18, 6, "#cdeaf8", c);
    box(834, 140, 42, 70, "#eef1f4", "#5a3720", c);
    px(842, 156, 8, 6, "#5a9fd4", c);
    px(860, 156, 8, 6, "#d2655a", c);
  }

  function drawPlant(x, y, c) {
    px(x + 6, y + 30, 26, 22, "#a8693a", c);
    px(x + 4, y + 28, 30, 5, "#c98a50", c);
    px(x + 16, y + 4, 6, 26, "#2f7a3e", c);
    px(x + 2, y + 8, 14, 10, "#6fbf73", c);
    px(x + 22, y + 2, 14, 10, "#4f9e57", c);
    px(x + 8, y - 6, 12, 10, "#6fbf73", c);
    px(x + 18, y + 16, 12, 8, "#4f9e57", c);
  }

  function drawArcade(c) {
    // 走道上的原创小街机（游戏工作室的标志物）
    const x = 566;
    const y = 232;
    box(x, y, 40, 62, "#d2655a", "#5a3720", c);
    px(x + 6, y + 8, 28, 20, "#2a1d14", c);
    px(x + 10, y + 12, 6, 4, "#6fbf73", c);
    px(x + 20, y + 18, 8, 4, "#f2b134", c);
    px(x + 4, y + 32, 32, 8, "#f6cfa4", c);
    px(x + 10, y + 34, 4, 4, INK, c);
    px(x + 24, y + 34, 4, 4, "#5a9fd4", c);
  }

  function drawCat(c) {
    // 睡在走道地毯上的猫（静态装饰）
    const x = 296;
    const y = 268;
    px(x, y + 8, 40, 14, "#e8a35c", c);
    px(x + 4, y + 8, 30, 3, "#f6c38a", c);
    px(x + 34, y + 2, 16, 16, "#e8a35c", c);
    px(x + 35, y - 2, 4, 5, "#e8a35c", c);
    px(x + 45, y - 2, 4, 5, "#e8a35c", c);
    px(x + 38, y + 8, 3, 2, INK, c);
    px(x + 44, y + 8, 3, 2, INK, c);
    px(x - 10, y + 16, 12, 4, "#e8a35c", c);
    px(x + 10, y + 10, 3, 10, "#c97f3e", c);
    px(x + 20, y + 10, 3, 10, "#c97f3e", c);
  }

  function drawSofa(c) {
    // 底部休息区：沙发 + 茶几
    box(330, 474, 150, 40, "#5a9fd4", "#2c4f73", c);
    px(334, 478, 142, 10, "#7fb6e0", c);
    box(322, 482, 16, 34, "#4a86b8", "#2c4f73", c);
    box(472, 482, 16, 34, "#4a86b8", "#2c4f73", c);
    box(540, 486, 64, 22, "#c98a50", "#5a3720", c);
    px(552, 480, 10, 8, "#fff8e6", c);
    px(578, 482, 14, 6, "#d2655a", c);
  }

  const bg = document.createElement("canvas");
  bg.width = W;
  bg.height = H;
  (() => {
    const c = bg.getContext("2d");
    c.imageSmoothingEnabled = false;
    drawWall(c);
    drawFloor(c);
    drawRunner(c);
    drawBookshelf(c);
    drawCooler(c);
    drawArcade(c);
    drawCat(c);
    drawSofa(c);
    drawPlant(6, 452, c);
    drawPlant(836, 452, c);
    drawPlant(250, 444, c);
  })();

  // ---------- 动态元素 ----------

  function drawTaskBoard() {
    // 墙上白板：显示当前任务需求
    box(276, 12, 300, 66, "#fdfdf8", "#7a4a24");
    px(279, 70, 294, 5, "#e6e0d0");
    px(290, 72, 18, 4, "#d2655a");
    px(312, 72, 18, 4, "#5a9fd4");
    ctx.fillStyle = INK;
    ctx.textAlign = "left";
    ctx.font = `bold 11px ${FONT}`;
    ctx.fillText("今日任务", 288, 30);
    ctx.font = `12px ${FONT}`;
    // 按实测宽度截断，避免长需求溢出白板
    const full = requirement || "等待 CEO 发布任务…";
    let text = full;
    while (text.length > 2 && ctx.measureText(text).width > 274) {
      text = text.slice(0, -1);
    }
    if (text !== full) text = text.slice(0, -1) + "…";
    ctx.fillStyle = requirement ? INK : "#a88a6c";
    ctx.fillText(text, 288, 52);
  }

  function drawStation(agent, phase) {
    const { x, y } = agent;
    const st = state.get(agent.id);
    const focus = activeAgent === agent.id && ACTIVE.has(st.status);

    // 工位地垫：焦点员工按状态着色，悬停时金色描边
    const matBorder = hovered === agent.id ? "#f2b134" : "#b98447";
    box(x - 90, y - 72, 180, 144, focus ? STATUS_FILL[st.status] : "#e3bd84", matBorder);

    // 椅背
    box(x - 24, y - 60, 48, 56, agent.dark, INK);
    px(x - 20, y - 56, 40, 4, agent.color);
  }

  function drawCharacter(agent, phase) {
    const { x, y } = agent;
    const st = state.get(agent.id);
    const focus = activeAgent === agent.id && ACTIVE.has(st.status);
    const still = reduceMotion.matches;
    const bob = focus && !still ? Math.round(Math.sin(phase * 6) * 1.5) : 0;
    const shake = focus && st.status === "fixing" && !still ? Math.round(Math.sin(phase * 22) * 1.5) : 0;
    const cx = x + shake;
    const top = y - 64 + bob;

    // 身体（衬衫 + 领口）
    px(cx - 17, top + 30, 34, 36, INK);
    px(cx - 15, top + 32, 30, 34, agent.color);
    px(cx - 4, top + 32, 8, 6, "#fff8e6");
    px(cx - 15, top + 54, 30, 4, agent.dark);

    // 头部：原创 Q 版大头
    drawHead(ctx, cx - 15, top, LOOKS[agent.talent], {
      blink: !still && (Math.floor(phase * 10 + agent.x) % 37 === 0),
      sad: st.status === "error",
      happy: st.status === "completed",
    });

    // 手：工作时左右交替敲键盘
    const arm = focus && !still ? Math.round(Math.sin(phase * 14) * 2) : 0;
    px(cx - 26, y - 6 + arm, 10, 8, INK);
    px(cx - 24, y - 4 + arm, 6, 4, SKIN);
    px(cx + 16, y - 6 - arm, 10, 8, INK);
    px(cx + 18, y - 4 - arm, 6, 4, SKIN);
  }

  // 头像绘制（办公室与员工档案卡共用），尺寸 30×30
  function drawHead(c, hx, hy, look, mood = {}) {
    look = look || LOOKS.coo;
    px(hx, hy + 2, 30, 28, INK, c);
    px(hx + 2, hy + 4, 26, 24, SKIN, c);
    px(hx + 2, hy + 24, 26, 4, SKIN_SHADE, c);
    // 头发
    px(hx, hy, 30, 10, INK, c);
    px(hx + 2, hy + 2, 26, 8, look.hair, c);
    px(hx + 2, hy + 10, 5, 8, look.hair, c);
    px(hx + 23, hy + 10, 5, 8, look.hair, c);
    px(hx + 12, hy + 10, 8, 3, look.hair, c);
    // 眼睛
    if (mood.blink) {
      px(hx + 8, hy + 16, 4, 1, INK, c);
      px(hx + 18, hy + 16, 4, 1, INK, c);
    } else if (mood.happy) {
      px(hx + 8, hy + 15, 4, 2, INK, c);
      px(hx + 18, hy + 15, 4, 2, INK, c);
    } else {
      px(hx + 9, hy + 14, 3, 4, INK, c);
      px(hx + 18, hy + 14, 3, 4, INK, c);
    }
    if (look.glasses) {
      px(hx + 6, hy + 12, 8, 2, INK, c);
      px(hx + 16, hy + 12, 8, 2, INK, c);
      px(hx + 14, hy + 14, 2, 1, INK, c);
    }
    // 腮红与嘴
    px(hx + 5, hy + 20, 4, 2, "#f29a8a", c);
    px(hx + 21, hy + 20, 4, 2, "#f29a8a", c);
    if (mood.sad) px(hx + 13, hy + 23, 4, 1, INK, c);
    else px(hx + 13, hy + 22, 4, 2, "#b4552e", c);
  }

  // 每个角色桌上的原创道具，帮助一眼认出岗位
  const DESK_ITEMS = {
    coo(x, y) {
      box(x, y - 22, 22, 26, "#fff8e6", "#7a4a24");
      px(x + 8, y - 25, 6, 4, "#a8a8a8");
      px(x + 5, y - 14, 12, 2, "#a88a6c");
      px(x + 5, y - 9, 9, 2, "#a88a6c");
    },
    creative(x, y) {
      box(x, y - 12, 28, 16, "#fff8e6", INK);
      px(x + 5, y - 8, 4, 4, "#d2655a");
      px(x + 12, y - 8, 4, 4, "#f2b134");
      px(x + 19, y - 8, 4, 4, "#5a9fd4");
      px(x + 24, y - 30, 3, 20, "#7a4a24");
      px(x + 23, y - 34, 5, 5, "#b07fd6");
    },
    delivery(x, y) {
      box(x, y - 24, 30, 28, "#fff8e6", INK);
      px(x + 2, y - 22, 26, 6, "#d2655a");
      for (let i = 0; i < 3; i++) for (let j = 0; j < 2; j++) px(x + 5 + i * 8, y - 12 + j * 7, 5, 4, "#a88a6c");
    },
    engineer(x, y) {
      px(x, y - 18, 14, 18, INK);
      px(x + 2, y - 16, 10, 14, "#fff8e6");
      px(x + 2, y - 16, 10, 4, "#7a4a24");
      px(x + 12, y - 12, 5, 6, INK);
      px(x + 20, y - 6, 18, 6, "#c08548");
    },
    reviewer(x, y) {
      box(x, y - 24, 22, 28, "#fff8e6", INK);
      px(x + 5, y - 17, 4, 4, "#6fbf73");
      px(x + 5, y - 9, 4, 4, "#6fbf73");
      px(x + 11, y - 16, 7, 2, "#a88a6c");
      px(x + 11, y - 8, 7, 2, "#a88a6c");
      box(x + 22, y - 18, 14, 14, "#cdeaf8", INK);
      px(x + 34, y - 6, 4, 8, INK);
    },
    marketer(x, y) {
      px(x, y - 18, 10, 12, INK);
      px(x + 2, y - 16, 6, 8, "#f2b134");
      px(x + 8, y - 22, 6, 20, INK);
      px(x + 10, y - 20, 4, 16, "#d2655a");
      px(x + 20, y - 26, 16, 26, "#b07fd6");
      px(x + 23, y - 22, 10, 4, "#fff8e6");
    },
  };

  function drawDesk(agent, phase) {
    const { x, y } = agent;
    const st = state.get(agent.id);
    const focus = activeAgent === agent.id && ACTIVE.has(st.status);
    const still = reduceMotion.matches;

    // 显示器（放在桌面左侧，屏幕朝向观众）
    box(x - 74, y - 44, 44, 36, "#3a2a20", INK);
    const screen = focus ? STATUS_FILL[st.status] : "#4a5a6a";
    px(x - 70, y - 40, 36, 28, screen);
    if (focus) {
      // 屏幕上滚动的代码行，只在后端判定为工作状态时出现
      const scroll = still ? 0 : Math.floor(phase * 6) % 4;
      for (let i = 0; i < 4; i++) {
        const w = [24, 16, 28, 12][(i + scroll) % 4];
        px(x - 66, y - 36 + i * 6, w, 3, STATUS_COLOR[st.status]);
      }
    } else {
      px(x - 66, y - 36, 8, 3, "#6a7a8a");
    }
    px(x - 56, y - 8, 8, 6, INK);

    // 桌面与前挡板
    box(x - 84, y - 4, 168, 16, "#dca464", INK);
    px(x - 81, y - 1, 162, 3, "#f0c48a");
    box(x - 80, y + 10, 160, 36, "#a8693a", INK);
    px(x + 52, y + 18, 22, 20, "#8f5530");
    px(x + 60, y + 26, 6, 3, "#f2b134");

    // 键盘
    px(x - 16, y - 2, 32, 6, "#5a4636");
    px(x - 14, y - 1, 28, 2, "#8a7666");

    (DESK_ITEMS[agent.id] || (() => {}))(x + 38, y - 2);

    // 名牌：名字 + 岗位
    box(x - 76, y + 16, 124, 22, "#fff8e6", INK);
    ctx.textAlign = "center";
    ctx.fillStyle = INK;
    ctx.font = `bold 10px ${FONT}`;
    ctx.fillText(`${agent.name} ${agent.role}`, x - 14, y + 31);

    // 状态牌
    const label = STATUS_TEXT[st.status] || st.status;
    ctx.font = `bold 11px ${FONT}`;
    const tw = Math.ceil(ctx.measureText(label).width) + 22;
    box(x - tw / 2, y + 48, tw, 18, STATUS_FILL[st.status] || "#efd39a", STATUS_COLOR[st.status] || INK);
    px(x - tw / 2 + 5, y + 54, 6, 6, STATUS_COLOR[st.status] || INK);
    ctx.fillStyle = INK;
    ctx.textAlign = "left";
    ctx.fillText(label, x - tw / 2 + 14, y + 61);

    // 岗位标签（如 Engineer 当前默认角色），数据来自 /api/employees
    if (st.tag) {
      ctx.font = `bold 10px ${FONT}`;
      const gw = Math.ceil(ctx.measureText(st.tag).width) + 10;
      box(x + 86 - gw, y - 68, gw, 16, "#f2b134", INK);
      ctx.fillStyle = INK;
      ctx.fillText(st.tag, x + 91 - gw, y - 56);
    }
  }

  // 头顶状态图标：只反映后端状态，动画只是装饰
  function drawStatusIcon(agent, phase) {
    const st = state.get(agent.id);
    const still = reduceMotion.matches;
    const x = agent.x + 22;
    const y = agent.y - 84 + (still ? 0 : Math.round(Math.sin(phase * 3) * 1));
    const focus = activeAgent === agent.id;
    if (st.status === "working" && focus) {
      box(x, y, 26, 14, "#fff8e6", INK);
      const n = still ? 3 : (Math.floor(phase * 3) % 3) + 1;
      for (let i = 0; i < n; i++) px(x + 5 + i * 6, y + 6, 3, 3, STATUS_COLOR.working);
    } else if (st.status === "reviewing" && focus) {
      box(x, y - 2, 14, 14, "#cdeaf8", INK);
      px(x + 12, y + 10, 4, 6, INK);
    } else if (st.status === "fixing" && focus) {
      px(x, y, 18, 4, "#7d7d7d");
      px(x + 14, y - 3, 6, 10, "#7d7d7d");
      px(x - 6, y + 10, 4, 6, "#5a9fd4");
    } else if (st.status === "completed") {
      px(x + 5, y, 4, 14, "#f2b134");
      px(x, y + 5, 14, 4, "#f2b134");
      px(x + 3, y + 3, 8, 8, "#f2b134");
    } else if (st.status === "error") {
      box(x, y - 4, 14, 20, "#d2655a", INK);
      px(x + 5, y, 4, 8, "#fff8e6");
      px(x + 5, y + 10, 4, 3, "#fff8e6");
    }
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
    // 冲突观点（setSpeech）来自真实 conflict.opinion 事件，即使员工已空闲也保留展示；
    // 状态类发言只在“正在干活”或出错时冒泡，避免长期占用画面。
    const text = st.speech || (SPEAKING.has(st.status) ? st.message : "");
    if (!text) return;
    const lines = wrap(text, 13);
    const boxW = Math.max(...lines.map((l) => [...l].length)) * 12 + 18;
    const boxH = lines.length * 15 + 12;
    const bx = Math.min(Math.max(agent.x - boxW / 2, 4), W - boxW - 4);
    const by = agent.y - 90 - boxH;
    const accent = STATUS_COLOR[st.status] || INK;

    px(bx + 3, by + 3, boxW, boxH, "rgba(69,41,26,0.35)");
    box(bx, by, boxW, boxH, "#fffdf5", INK);
    px(bx + 2, by + 2, 4, boxH - 4, accent);
    // 小尾巴
    const tx = Math.min(Math.max(agent.x - 4, bx + 8), bx + boxW - 16);
    px(tx, by + boxH - 2, 10, 4, "#fffdf5");
    px(tx - 2, by + boxH - 2, 2, 6, INK);
    px(tx + 10, by + boxH - 2, 2, 4, INK);
    px(tx, by + boxH + 2, 6, 2, INK);
    px(tx + 6, by + boxH + 2, 4, 2, INK);

    ctx.fillStyle = INK;
    ctx.font = `11px ${FONT}`;
    ctx.textAlign = "left";
    lines.forEach((line, i) => ctx.fillText(line, bx + 10, by + 17 + i * 15));
  }

  function frame(ts) {
    const phase = ts / 1000;
    ctx.drawImage(bg, 0, 0);
    drawTaskBoard();
    // 按 y 排序，保证下排遮挡关系正确
    [...AGENTS]
      .sort((a, b) => a.y - b.y)
      .forEach((agent) => {
        drawStation(agent, phase);
        drawCharacter(agent, phase);
        drawDesk(agent, phase);
        drawStatusIcon(agent, phase);
      });
    AGENTS.forEach(drawBubble);
    requestAnimationFrame(frame);
  }

  // ---------- 点击热区：由 AGENTS 坐标生成，与绘制位置一致 ----------

  function buildHotspots() {
    const layer = document.getElementById("office-hotspots");
    if (!layer) return;
    layer.innerHTML = "";
    AGENTS.forEach((agent) => {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "hotspot";
      button.dataset.agent = agent.id;
      button.style.left = `${((agent.x - HIT.left) / W) * 100}%`;
      button.style.top = `${((agent.y - HIT.top) / H) * 100}%`;
      button.style.width = `${(HIT.width / W) * 100}%`;
      button.style.height = `${(HIT.height / H) * 100}%`;
      const label =
        agent.id === "engineer"
          ? `${agent.name} · ${agent.role}：查看档案并切换主力/备用工程师`
          : `${agent.name} · ${agent.role}：查看员工档案`;
      button.title = label;
      button.setAttribute("aria-label", label);
      button.addEventListener("click", () => {
        if (selectHandler) selectHandler(agent.id, agent.talent);
      });
      const enter = () => (hovered = agent.id);
      const leave = () => {
        if (hovered === agent.id) hovered = null;
      };
      button.addEventListener("mouseenter", enter);
      button.addEventListener("focus", enter);
      button.addEventListener("mouseleave", leave);
      button.addEventListener("blur", leave);
      layer.appendChild(button);
    });
  }

  // ---------- 对外接口 ----------

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

  // 只更新观点气泡，不改变员工状态；文本必须来自后端 conflict.* 事件
  function setSpeech(agentId, text) {
    const entry = state.get(agentId);
    if (!entry) return;
    entry.speech = (text || "").trim();
  }

  // 工位标签（纯展示），例如 Engineer 岗位当前默认启用的角色
  function setTag(agentId, text) {
    const entry = state.get(agentId);
    if (entry) entry.tag = (text || "").trim();
  }

  function resetAgents() {
    state.forEach((entry) => {
      entry.status = "idle";
      entry.message = "";
      entry.speech = "";
    });
    activeAgent = null;
  }

  function onSelect(handler) {
    selectHandler = handler;
  }

  // 在任意 canvas 上绘制员工头像（员工档案卡使用）
  function drawPortrait(target, talentName) {
    const c = target.getContext("2d");
    const look = LOOKS[talentName] || LOOKS.coo;
    c.imageSmoothingEnabled = false;
    c.clearRect(0, 0, target.width, target.height);
    const s = target.width / 32;
    c.save();
    c.scale(s, s);
    px(0, 0, 32, 32, "#f7e3b5", c);
    px(5, 24, 22, 8, INK, c);
    px(7, 26, 18, 6, look.color, c);
    px(13, 26, 6, 3, "#fff8e6", c);
    drawHead(c, 1, -1, look, {});
    c.restore();
  }

  buildHotspots();
  requestAnimationFrame(frame);

  return { setAgent, setRequirement, setSpeech, setTag, resetAgents, onSelect, drawPortrait };
})();
