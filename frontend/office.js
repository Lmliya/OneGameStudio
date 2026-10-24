// OneGameStudio 原创 2.5D 等距像素办公室。
// 世界坐标、投影、绘制与 DOM 热区共用同一数据源；员工状态只来自后端事件。
const Office = (() => {
  const canvas = document.getElementById("office");
  const ctx = canvas.getContext("2d");
  const W = 960;
  const H = 600;
  const TILE_W = 64;
  const TILE_H = 32;
  const HEIGHT = 32;
  const ORIGIN = { x: 480, y: 184 };
  const FONT = 'ui-monospace, Menlo, "PingFang SC", "Microsoft YaHei", monospace';
  const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)");
  const INK = "#45291a";
  const SKIN = "#f6cfa4";
  const SKIN_SHADE = "#e3ae80";
  const ACTIVE = new Set(["working", "reviewing", "fixing"]);
  const SPEAKING = new Set(["working", "reviewing", "fixing", "error"]);

  // x/y/z 均为世界坐标；屏幕位置只能由 project() 得出。
  const AGENTS = [
    { id: "coo", talent: "coo", name: "COO", role: "产品经理", color: "#5a9fd4", dark: "#2c6496", hair: "#3b2a20", x: 1.8, y: 1.7 },
    { id: "creative", talent: "creative", name: "CREATIVE", role: "创意总监", color: "#f08a5d", dark: "#b4552e", hair: "#c0392b", x: 4.8, y: 1.7 },
    { id: "delivery", talent: "delivery", name: "DELIVERY", role: "交付总监", color: "#4fb3a9", dark: "#2a7a72", hair: "#2b2b3a", x: 7.8, y: 1.7 },
    { id: "engineer", talent: "engineer", name: "ENGINEER", role: "游戏工程师", color: "#f2b134", dark: "#b97a12", hair: "#5a3720", x: 1.8, y: 4.55 },
    { id: "reviewer", talent: "reviewer", name: "REVIEWER", role: "质量审查官", color: "#6fbf73", dark: "#2f7a3e", hair: "#7a4a24", x: 4.8, y: 4.55 },
    { id: "marketer", talent: "marketer", name: "MARKETER", role: "营销负责人", color: "#b07fd6", dark: "#6a3f92", hair: "#e8c35a", x: 7.8, y: 4.55 },
  ];
  const LOOKS = Object.fromEntries(AGENTS.map((a) => [a.talent, a]));
  LOOKS.backup_engineer = { color: "#e07a9a", dark: "#a34766", hair: "#2d6a8a", glasses: true };
  const STATUS_TEXT = { idle: "待命", working: "工作中", reviewing: "思考中", fixing: "修复中", completed: "已完成", error: "出错" };
  const STATUS_COLOR = { idle: "#a88a6c", working: "#2c6496", reviewing: "#2f7a3e", fixing: "#b97a12", completed: "#2f7a3e", error: "#9c3a31" };
  const STATUS_FILL = { idle: "#efd39a", working: "#cfe4f5", reviewing: "#d6efcf", fixing: "#fbe3a6", completed: "#d6efcf", error: "#f4cdc6" };

  const state = new Map(AGENTS.map((a) => [a.id, { status: "idle", message: "", speech: "", tag: "", noticeUntil: 0 }]));
  const positions = new Map(AGENTS.map((a) => [a.id, { x: a.x + 0.2, y: a.y - 0.58 }]));
  const hotspots = new Map();
  const camera = { zoom: 1.3, panX: 0, panY: 0 };
  let activeAgent = null;
  let hovered = null;
  let selected = null;
  let requirement = "";
  let selectHandler = null;
  let dirty = true;
  let staticDirty = true;
  let dpr = 1;
  let lastFrame = 0;
  let dragging = null;

  const bg = document.createElement("canvas");
  bg.width = W;
  bg.height = H;
  const bgCtx = bg.getContext("2d");
  bgCtx.imageSmoothingEnabled = false;

  function px(x, y, w, h, color, c = ctx) {
    c.fillStyle = color;
    c.fillRect(Math.round(x), Math.round(y), Math.max(1, Math.round(w)), Math.max(1, Math.round(h)));
  }

  function box(x, y, w, h, fill, border = INK, c = ctx) {
    px(x, y, w, h, border, c);
    px(x + 2, y + 2, w - 4, h - 4, fill, c);
  }

  function poly(points, fill, c = ctx, stroke = null) {
    c.beginPath();
    points.forEach((p, i) => (i ? c.lineTo(Math.round(p.x), Math.round(p.y)) : c.moveTo(Math.round(p.x), Math.round(p.y))));
    c.closePath();
    c.fillStyle = fill;
    c.fill();
    if (stroke) {
      c.strokeStyle = stroke;
      c.lineWidth = Math.max(1, camera.zoom);
      c.stroke();
    }
  }

  function project(x, y, z = 0) {
    const rx = ORIGIN.x + (x - y) * (TILE_W / 2);
    const ry = ORIGIN.y + (x + y) * (TILE_H / 2) - z * HEIGHT;
    return {
      x: W / 2 + (rx - W / 2) * camera.zoom + camera.panX,
      y: H / 2 + (ry - H / 2) * camera.zoom + camera.panY,
    };
  }

  function isoBox(c, x, y, z, w, d, h, colors) {
    const top = [project(x, y, z + h), project(x + w, y, z + h), project(x + w, y + d, z + h), project(x, y + d, z + h)];
    const front = [project(x, y + d, z), project(x + w, y + d, z), project(x + w, y + d, z + h), project(x, y + d, z + h)];
    const side = [project(x + w, y, z), project(x + w, y + d, z), project(x + w, y + d, z + h), project(x + w, y, z + h)];
    poly(front, colors.front, c, colors.edge || INK);
    poly(side, colors.side, c, colors.edge || INK);
    poly(top, colors.top, c, colors.edge || INK);
  }

  function wallRectY(c, x, z, w, h, fill, border = null) {
    const points = [project(x, 0, z), project(x + w, 0, z), project(x + w, 0, z + h), project(x, 0, z + h)];
    poly(points, fill, c, border);
  }

  function wallRectX(c, y, z, d, h, fill, border = null) {
    const points = [project(0, y, z), project(0, y + d, z), project(0, y + d, z + h), project(0, y, z + h)];
    poly(points, fill, c, border);
  }

  function drawFloor(c) {
    // 地板厚度先画，前缘让房间成为有边界的实体而不是平面背景。
    isoBox(c, 0, 0, -0.22, 10, 8, 0.22, { top: "#dca464", front: "#8f5530", side: "#70401f", edge: "#5a3720" });
    for (let x = 0; x < 10; x += 1) {
      for (let y = 0; y < 8; y += 1) {
        const fill = (x + y) % 2 ? "#d8a565" : "#e2b474";
        poly([project(x, y), project(x + 1, y), project(x + 1, y + 1), project(x, y + 1)], fill, c, "#bd874b");
        if ((x * 3 + y) % 4 === 0) {
          poly([project(x + 0.15, y + 0.42, 0.005), project(x + 0.65, y + 0.42, 0.005), project(x + 0.65, y + 0.47, 0.005), project(x + 0.15, y + 0.47, 0.005)], "rgba(122,74,36,0.18)", c);
        }
      }
    }
    // 中央走道地毯，仍严格落在地面世界坐标上。
    poly([project(0.8, 3.25, 0.01), project(9.2, 3.25, 0.01), project(9.2, 3.85, 0.01), project(0.8, 3.85, 0.01)], "#b95f4b", c, "#7f4032");
    for (let x = 1; x < 9; x += 0.65) {
      const p = project(x, 3.55, 0.02);
      const s = 3 * camera.zoom;
      poly([{ x: p.x, y: p.y - s }, { x: p.x + s * 2, y: p.y }, { x: p.x, y: p.y + s }, { x: p.x - s * 2, y: p.y }], "#efb67d", c);
    }
  }

  function drawWalls(c) {
    const wallY = [project(0, 0, 0), project(10, 0, 0), project(10, 0, 3.55), project(0, 0, 3.55)];
    const wallX = [project(0, 0, 0), project(0, 8, 0), project(0, 8, 3.55), project(0, 0, 3.55)];
    poly(wallY, "#f4dfb8", c, "#7a4a24");
    poly(wallX, "#e8cda2", c, "#7a4a24");
    for (let x = 0.35; x < 10; x += 0.75) wallRectY(c, x, 0.18, 0.16, 3.25, "rgba(192,133,72,0.10)");
    for (let y = 0.35; y < 8; y += 0.75) wallRectX(c, y, 0.18, 0.16, 3.25, "rgba(122,74,36,0.09)");
    wallRectY(c, 0, 0.08, 10, 0.18, "#a8693a", "#7a4a24");
    wallRectX(c, 0, 0.08, 8, 0.18, "#936039", "#7a4a24");

    // 后墙窗户与左墙窗户。
    [[0.75, 1.65], [7.65, 1.65]].forEach(([x, z]) => {
      wallRectY(c, x - 0.08, z - 0.08, 1.9, 1.35, "#7a4a24");
      wallRectY(c, x, z, 1.74, 1.18, "#9fd3f0");
      wallRectY(c, x, z, 1.74, 0.28, "#cdeaf8");
      wallRectY(c, x + 0.82, z, 0.08, 1.18, "#7a4a24");
      wallRectY(c, x + 0.25, z + 0.68, 0.48, 0.14, "#fff8e6");
      wallRectY(c, x + 1.15, z + 0.42, 0.38, 0.14, "#fff8e6");
    });
    wallRectX(c, 1.1, 1.65, 1.9, 1.35, "#7a4a24");
    wallRectX(c, 1.18, 1.73, 1.74, 1.18, "#8fc5e5");
    wallRectX(c, 2.0, 1.73, 0.08, 1.18, "#7a4a24");
    wallRectX(c, 1.45, 2.35, 0.52, 0.14, "#fff8e6");

    // 今日任务白板（面向玩家的墙面标牌，绘制在动态层）与原创海报。
    wallRectX(c, 4.15, 1.42, 1.05, 1.35, "#7a4a24");
    wallRectX(c, 4.25, 1.52, 0.85, 1.15, "#fff8e6");
    wallRectX(c, 4.43, 1.85, 0.5, 0.34, "#d2655a");
    wallRectX(c, 4.53, 1.95, 0.1, 0.14, "#fff8e6");
    wallRectX(c, 4.78, 2.02, 0.08, 0.08, "#f2b134");
    wallRectX(c, 4.78, 1.89, 0.08, 0.08, "#6fbf73");
  }

  function renderStatic() {
    bgCtx.clearRect(0, 0, W, H);
    px(0, 0, W, H, "#6b4226", bgCtx);
    // 像素墙角环境光：不使用模糊滤镜。
    px(0, 0, W, H, "#6b4226", bgCtx);
    drawWalls(bgCtx);
    drawFloor(bgCtx);
    staticDirty = false;
  }

  function drawDesk(agent, phase) {
    const { x, y } = agent;
    const st = state.get(agent.id);
    const focus = activeAgent === agent.id && ACTIVE.has(st.status);
    const wood = { top: "#e5ad68", front: "#a8693a", side: "#84502c", edge: INK };
    [[0.12, 0.12], [1.67, 0.12], [0.12, 0.78], [1.67, 0.78]].forEach(([dx, dy]) => {
      isoBox(ctx, x + dx, y + dy, 0.03, 0.13, 0.13, 0.65, wood);
    });
    isoBox(ctx, x + 1.38, y + 0.18, 0.15, 0.42, 0.55, 0.48, { top: "#c98a50", front: "#8f5530", side: "#70401f", edge: INK });
    isoBox(ctx, x, y, 0.66, 1.95, 1.0, 0.15, wood);
    // 抽屉把手。
    const handle = project(x + 1.54, y + 0.74, 0.43);
    px(handle.x - 4 * camera.zoom, handle.y, 8 * camera.zoom, 2 * camera.zoom, "#f2b134");

    // 显示器有外壳厚度、支架与独立屏幕正面。
    isoBox(ctx, x + 0.28, y + 0.22, 0.81, 0.11, 0.11, 0.23, { top: "#6a5a4c", front: "#3a2a20", side: "#241a14", edge: INK });
    isoBox(ctx, x + 0.16, y + 0.13, 0.82, 0.34, 0.25, 0.05, { top: "#5a4636", front: "#3a2a20", side: "#241a14", edge: INK });
    isoBox(ctx, x + 0.02, y + 0.08, 1.0, 0.88, 0.12, 0.62, { top: "#5a4636", front: "#2a211b", side: "#1b1410", edge: INK });
    const screen = [project(x + 0.1, y + 0.205, 1.1), project(x + 0.8, y + 0.205, 1.1), project(x + 0.8, y + 0.205, 1.52), project(x + 0.1, y + 0.205, 1.52)];
    poly(screen, focus ? STATUS_FILL[st.status] : "#40505c", ctx, "#17110d");
    if (focus) {
      const scroll = reduceMotion.matches ? 0 : Math.floor(phase * 6) % 4;
      for (let i = 0; i < 4; i += 1) {
        const a = project(x + 0.18, y + 0.212, 1.18 + i * 0.075);
        const b = project(x + 0.3 + [0.24, 0.38, 0.18, 0.31][(i + scroll) % 4], y + 0.212, 1.18 + i * 0.075);
        poly([a, { x: b.x, y: a.y }, b, { x: a.x, y: b.y }], STATUS_COLOR[st.status]);
      }
    } else {
      const led = project(x + 0.76, y + 0.215, 1.07);
      px(led.x, led.y, 3 * camera.zoom, 3 * camera.zoom, "#6fbf73");
    }
    isoBox(ctx, x + 0.94, y + 0.48, 0.82, 0.58, 0.25, 0.04, { top: "#8a7666", front: "#5a4636", side: "#3a2a20", edge: INK });
    drawDeskItem(agent, x + 1.6, y + 0.25, 0.83);
  }

  function drawDeskItem(agent, x, y, z) {
    const colors = { coo: "#5a9fd4", creative: "#f08a5d", delivery: "#4fb3a9", engineer: "#f2b134", reviewer: "#6fbf73", marketer: "#b07fd6" };
    isoBox(ctx, x, y, z, 0.2, 0.28, 0.06, { top: "#fff8e6", front: "#d8cba9", side: "#b8a984", edge: INK });
    const p = project(x + 0.1, y + 0.29, z + 0.09);
    px(p.x - 3 * camera.zoom, p.y - 3 * camera.zoom, 6 * camera.zoom, 6 * camera.zoom, colors[agent.id]);
  }

  function drawChair(agent) {
    const p = positions.get(agent.id);
    const seated = p.y < agent.y;
    const x = agent.x + 0.63;
    const y = agent.y - 0.58;
    const color = { top: agent.color, front: agent.dark, side: agent.dark, edge: INK };
    isoBox(ctx, x, y, 0.32, 0.65, 0.58, 0.12, color);
    isoBox(ctx, x + 0.27, y + 0.25, 0.03, 0.1, 0.1, 0.31, { top: "#7d7d7d", front: "#4a4a4a", side: "#333", edge: INK });
    if (seated) isoBox(ctx, x, y - 0.08, 0.42, 0.65, 0.12, 0.65, color);
  }

  function drawHead(c, hx, hy, look, mood = {}) {
    look = look || LOOKS.coo;
    px(hx, hy + 2, 30, 28, INK, c);
    px(hx + 2, hy + 4, 26, 24, SKIN, c);
    px(hx + 2, hy + 24, 26, 4, SKIN_SHADE, c);
    px(hx, hy, 30, 10, INK, c);
    px(hx + 2, hy + 2, 26, 8, look.hair, c);
    px(hx + 2, hy + 10, 5, 8, look.hair, c);
    px(hx + 23, hy + 10, 5, 8, look.hair, c);
    px(hx + 12, hy + 10, 8, 3, look.hair, c);
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
    px(hx + 5, hy + 20, 4, 2, "#f29a8a", c);
    px(hx + 21, hy + 20, 4, 2, "#f29a8a", c);
    if (mood.sad) px(hx + 13, hy + 23, 4, 1, INK, c);
    else px(hx + 13, hy + 22, 4, 2, "#b4552e", c);
  }

  function drawShadow(x, y, width = 22) {
    const p = project(x, y, 0.015);
    const z = camera.zoom;
    poly([
      { x: p.x - width * z, y: p.y }, { x: p.x - width * 0.6 * z, y: p.y - 5 * z },
      { x: p.x + width * 0.6 * z, y: p.y - 5 * z }, { x: p.x + width * z, y: p.y },
      { x: p.x + width * 0.6 * z, y: p.y + 5 * z }, { x: p.x - width * 0.6 * z, y: p.y + 5 * z },
    ], "rgba(69,41,26,0.28)");
  }

  function drawCharacter(agent, phase) {
    const p = positions.get(agent.id);
    const st = state.get(agent.id);
    const focus = activeAgent === agent.id && ACTIVE.has(st.status);
    const seated = p.y < agent.y;
    const still = reduceMotion.matches;
    const bob = focus && !still ? Math.round(Math.sin(phase * 7)) : 0;
    const foot = project(p.x, p.y, 0);
    const z = camera.zoom;
    drawShadow(p.x, p.y, 17);
    ctx.save();
    ctx.translate(Math.round(foot.x), Math.round(foot.y + bob * z));
    ctx.scale(z, z);
    // 腿和鞋：站立与坐姿共用同一比例角色。
    if (seated) {
      px(-12, -13, 9, 11, agent.dark);
      px(3, -13, 9, 11, agent.dark);
      px(-14, -5, 12, 5, INK);
      px(2, -5, 12, 5, INK);
    } else {
      px(-10, -18, 8, 15, agent.dark);
      px(2, -18, 8, 15, agent.dark);
      px(-12, -5, 10, 5, INK);
      px(2, -5, 10, 5, INK);
    }
    const bodyY = seated ? -38 : -43;
    px(-15, bodyY, 30, 28, INK);
    px(-13, bodyY + 2, 26, 24, agent.color);
    px(-4, bodyY + 2, 8, 6, "#fff8e6");
    px(-13, bodyY + 20, 26, 4, agent.dark);
    const arm = focus && !still ? Math.round(Math.sin(phase * 14) * 2) : 0;
    if (st.status === "reviewing") {
      px(12, bodyY + 5, 8, 17, agent.color);
      px(12, bodyY + 1, 7, 7, SKIN);
      px(-20, bodyY + 8, 8, 17, agent.color);
    } else {
      px(-21, bodyY + 8 + arm, 8, 18, agent.color);
      px(13, bodyY + 8 - arm, 8, 18, agent.color);
      px(-20, bodyY + 22 + arm, 7, 6, SKIN);
      px(13, bodyY + 22 - arm, 7, 6, SKIN);
    }
    drawHead(ctx, -15, bodyY - 30, LOOKS[agent.talent], {
      blink: !still && (Math.floor(phase * 9 + agent.x * 4) % 41 === 0),
      sad: st.status === "error",
      happy: st.status === "completed",
    });
    ctx.restore();
  }

  function drawPlant(x, y) {
    drawShadow(x + 0.3, y + 0.3, 22);
    isoBox(ctx, x, y, 0, 0.62, 0.62, 0.55, { top: "#c98a50", front: "#a8693a", side: "#7a4a24", edge: INK });
    [[0.12, 0.18, 0.52, 0.28, 0.22, 0.65, "#4f9e57"], [0.34, 0.08, 0.55, 0.25, 0.25, 0.85, "#6fbf73"], [0.02, 0.35, 0.55, 0.24, 0.2, 0.48, "#2f7a3e"], [0.35, 0.36, 0.55, 0.22, 0.2, 0.55, "#4f9e57"]].forEach(([dx, dy, z, w, d, h, color]) => {
      isoBox(ctx, x + dx, y + dy, z, w, d, h, { top: color, front: color, side: "#2f7a3e", edge: "#2f6134" });
    });
  }

  function drawBookshelf() {
    isoBox(ctx, 0.28, 3.15, 0, 0.68, 1.55, 1.9, { top: "#c98a50", front: "#7a4a24", side: "#5a3720", edge: INK });
    const colors = ["#d2655a", "#f2b134", "#6fbf73", "#5a9fd4", "#b07fd6"];
    [0.25, 0.78, 1.31].forEach((z, row) => {
      isoBox(ctx, 0.25, 3.12, z, 0.75, 1.62, 0.08, { top: "#c98a50", front: "#a8693a", side: "#7a4a24", edge: INK });
      for (let i = 0; i < 5; i += 1) {
        isoBox(ctx, 0.92, 3.25 + i * 0.25, z + 0.08, 0.12, 0.17, 0.34 + (i % 2) * 0.08, { top: colors[(row + i) % 5], front: colors[(row + i) % 5], side: "#5a3720", edge: INK });
      }
    });
  }

  function drawCabinet() {
    isoBox(ctx, 9.05, 0.65, 0, 0.68, 1.25, 1.3, { top: "#dca464", front: "#a8693a", side: "#7a4a24", edge: INK });
    [0.38, 0.82].forEach((z) => {
      const p = project(9.38, 1.91, z);
      px(p.x - 4 * camera.zoom, p.y, 8 * camera.zoom, 2 * camera.zoom, "#f2b134");
    });
  }

  function drawMeeting() {
    const wood = { top: "#dca464", front: "#a8693a", side: "#7a4a24", edge: INK };
    isoBox(ctx, 4.1, 6.65, 0.58, 1.9, 0.95, 0.14, wood);
    isoBox(ctx, 4.28, 6.86, 0, 0.16, 0.16, 0.6, wood);
    isoBox(ctx, 5.65, 7.22, 0, 0.16, 0.16, 0.6, wood);
    isoBox(ctx, 4.45, 6.9, 0.74, 0.55, 0.36, 0.04, { top: "#fff8e6", front: "#d8cba9", side: "#b8a984", edge: INK });
    isoBox(ctx, 5.25, 6.98, 0.74, 0.24, 0.24, 0.25, { top: "#fff8e6", front: "#5a9fd4", side: "#2c6496", edge: INK });
    [[4.35, 6.05], [5.35, 6.05], [4.35, 7.62], [5.35, 7.62]].forEach(([x, y]) => {
      isoBox(ctx, x, y, 0.3, 0.52, 0.45, 0.12, { top: "#5a9fd4", front: "#2c6496", side: "#244f75", edge: INK });
      isoBox(ctx, x + 0.2, y + 0.18, 0, 0.1, 0.1, 0.32, { top: "#7d7d7d", front: "#4a4a4a", side: "#333", edge: INK });
    });
  }

  function drawSofa() {
    isoBox(ctx, 0.8, 6.75, 0.18, 1.65, 0.75, 0.38, { top: "#7fb6e0", front: "#4a86b8", side: "#2c6496", edge: INK });
    isoBox(ctx, 0.8, 6.67, 0.5, 1.65, 0.18, 0.65, { top: "#7fb6e0", front: "#5a9fd4", side: "#2c6496", edge: INK });
    isoBox(ctx, 0.72, 6.68, 0.25, 0.18, 0.82, 0.52, { top: "#7fb6e0", front: "#4a86b8", side: "#2c6496", edge: INK });
    isoBox(ctx, 2.35, 6.68, 0.25, 0.18, 0.82, 0.52, { top: "#7fb6e0", front: "#4a86b8", side: "#2c6496", edge: INK });
  }

  function drawSelection(agent) {
    if (selected !== agent.id && hovered !== agent.id) return;
    const x = agent.x - 0.18;
    const y = agent.y - 0.82;
    const color = selected === agent.id ? "#f2b134" : "#fff8e6";
    poly([project(x, y, 0.025), project(x + 2.35, y, 0.025), project(x + 2.35, y + 2.25, 0.025), project(x, y + 2.25, 0.025)], "rgba(242,177,52,0.08)", ctx, color);
  }

  function drawLabels(agent) {
    const st = state.get(agent.id);
    const p = positions.get(agent.id);
    const foot = project(p.x, p.y, 0);
    const z = camera.zoom;
    const label = `${agent.name} · ${STATUS_TEXT[st.status] || st.status}`;
    ctx.font = `bold ${Math.max(11, Math.round(14 * z))}px ${FONT}`;
    const width = Math.ceil(ctx.measureText(label).width) + 18 * z;
    const y = foot.y + 9 * z;
    box(foot.x - width / 2, y, width, 18 * z, STATUS_FILL[st.status], STATUS_COLOR[st.status]);
    px(foot.x - width / 2 + 5 * z, y + 6 * z, 5 * z, 5 * z, STATUS_COLOR[st.status]);
    ctx.textAlign = "left";
    ctx.fillStyle = INK;
    ctx.fillText(label, foot.x - width / 2 + 13 * z, y + 13 * z);
    if (st.tag) {
      ctx.font = `bold ${Math.max(10, Math.round(12 * z))}px ${FONT}`;
      const tw = ctx.measureText(st.tag).width + 14 * z;
      const desk = project(agent.x + 1.82, agent.y + 0.15, 1.05);
      box(desk.x - tw / 2, desk.y - 12 * z, tw, 17 * z, "#f2b134", INK);
      ctx.fillStyle = INK;
      ctx.textAlign = "center";
      ctx.fillText(st.tag, desk.x, desk.y);
    }
  }

  function wrap(text, max) {
    const lines = [];
    let line = "";
    for (const ch of String(text || "")) {
      line += ch;
      if ([...line].length >= max) {
        lines.push(line);
        line = "";
      }
    }
    if (line) lines.push(line);
    return lines.slice(0, 2);
  }

  function drawBubble(agent, now) {
    const st = state.get(agent.id);
    const p = positions.get(agent.id);
    const head = project(p.x, p.y, 2.35);
    const z = camera.zoom;
    const text = st.speech || (SPEAKING.has(st.status) ? st.message : "");
    if (text) {
      const lines = wrap(text, 12);
      const boxW = Math.max(...lines.map((l) => [...l].length)) * 11 * z + 18 * z;
      const boxH = lines.length * 15 * z + 12 * z;
      const bx = Math.min(Math.max(head.x - boxW / 2, 4), W - boxW - 4);
      const by = Math.max(4, head.y - boxH - 8 * z);
      px(bx + 3 * z, by + 3 * z, boxW, boxH, "rgba(69,41,26,0.35)");
      box(bx, by, boxW, boxH, "#fffdf5", INK);
      px(bx + 2 * z, by + 2 * z, 4 * z, boxH - 4 * z, STATUS_COLOR[st.status]);
      ctx.fillStyle = INK;
      ctx.font = `${Math.max(10, Math.round(12 * z))}px ${FONT}`;
      ctx.textAlign = "left";
      lines.forEach((line, i) => ctx.fillText(line, bx + 10 * z, by + 17 * z + i * 15 * z));
    }
    if (st.status === "working" && activeAgent === agent.id) {
      const n = reduceMotion.matches ? 3 : (Math.floor(now / 350) % 3) + 1;
      box(head.x + 18 * z, head.y - 4 * z, 28 * z, 16 * z, "#fff8e6", INK);
      for (let i = 0; i < n; i += 1) px(head.x + (24 + i * 7) * z, head.y + 3 * z, 3 * z, 3 * z, STATUS_COLOR.working);
    } else if (st.status === "completed") {
      ctx.fillStyle = STATUS_COLOR.completed;
      ctx.font = `bold ${Math.max(14, Math.round(20 * z))}px ${FONT}`;
      ctx.textAlign = "center";
      ctx.fillText("✓", head.x + 25 * z, head.y + 8 * z);
    } else if (st.status === "error") {
      box(head.x + 18 * z, head.y - 8 * z, 18 * z, 22 * z, "#d2655a", INK);
      px(head.x + 25 * z, head.y - 3 * z, 4 * z, 8 * z, "#fff8e6");
      px(head.x + 25 * z, head.y + 8 * z, 4 * z, 3 * z, "#fff8e6");
    }
    if (st.noticeUntil > now) {
      const rise = reduceMotion.matches ? 0 : Math.floor((st.noticeUntil - now) / 400) % 3;
      ctx.font = `bold ${Math.max(10, Math.round(12 * z))}px ${FONT}`;
      ctx.textAlign = "center";
      ctx.fillStyle = "#2f7a3e";
      ctx.fillText("+ TASK CLEAR", head.x, head.y - (24 + rise * 2) * z);
    }
  }

  function targetPosition(agent) {
    const st = state.get(agent.id);
    // 工作/修复在桌后；思考、完成、出错走到桌前。深度随真实世界坐标改变。
    const front = st.status === "reviewing" || st.status === "completed" || st.status === "error";
    return { x: agent.x + (front ? 0.65 : 0.2), y: agent.y + (front ? 1.12 : -0.58) };
  }

  function updatePositions() {
    let moving = false;
    AGENTS.forEach((agent) => {
      const current = positions.get(agent.id);
      const target = targetPosition(agent);
      const factor = reduceMotion.matches ? 1 : 0.22;
      current.x += (target.x - current.x) * factor;
      current.y += (target.y - current.y) * factor;
      if (Math.abs(target.x - current.x) + Math.abs(target.y - current.y) > 0.015) moving = true;
      else {
        current.x = target.x;
        current.y = target.y;
      }
    });
    return moving;
  }

  function agentBounds(agent) {
    const p = positions.get(agent.id);
    const points = [];
    [0, 1.8].forEach((z) => {
      points.push(project(p.x - 0.35, p.y, z), project(p.x + 0.35, p.y, z));
    });
    [[0, 0, 0], [1.95, 0, 0], [1.95, 1, 0], [0, 1, 0], [0, 0, 1.65], [1.95, 0, 1.65], [1.95, 1, 1.65], [0, 1, 1.65]].forEach(([x, y, z]) => points.push(project(agent.x + x, agent.y + y, z)));
    const xs = points.map((v) => v.x);
    const ys = points.map((v) => v.y);
    return { left: Math.min(...xs), top: Math.min(...ys), right: Math.max(...xs), bottom: Math.max(...ys) };
  }

  function syncHotspots() {
    AGENTS.forEach((agent) => {
      const button = hotspots.get(agent.id);
      if (!button) return;
      const b = agentBounds(agent);
      button.style.left = `${(b.left / W) * 100}%`;
      button.style.top = `${(b.top / H) * 100}%`;
      button.style.width = `${((b.right - b.left) / W) * 100}%`;
      button.style.height = `${((b.bottom - b.top) / H) * 100}%`;
      button.style.visibility = b.right < 0 || b.left > W || b.bottom < 0 || b.top > H ? "hidden" : "visible";
      button.classList.toggle("selected", selected === agent.id);
    });
  }

  function frame(now) {
    requestAnimationFrame(frame);
    if (document.hidden) return;
    const moving = updatePositions();
    const animated = activeAgent && ACTIVE.has(state.get(activeAgent).status);
    const notices = [...state.values()].some((s) => s.noticeUntil > now);
    if (!dirty && !moving && !animated && !notices) return;
    const interval = animated || moving ? 1000 / 15 : 80;
    if (now - lastFrame < interval) return;
    lastFrame = now;
    if (staticDirty) renderStatic();
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.imageSmoothingEnabled = false;
    ctx.clearRect(0, 0, W, H);
    ctx.drawImage(bg, 0, 0);

    const objects = [
      { depth: 4.1, draw: drawBookshelf },
      { depth: 10.4, draw: drawCabinet },
      { depth: 10.9, draw: drawMeeting },
      { depth: 8.3, draw: drawSofa },
      { depth: 8.2, draw: () => drawPlant(0.35, 7.15) },
      { depth: 16.8, draw: () => drawPlant(9.05, 7.0) },
      { depth: 12.1, draw: () => drawPlant(8.95, 3.0) },
    ];
    AGENTS.forEach((agent) => {
      objects.push({ depth: agent.x + agent.y + 0.48, draw: () => drawDesk(agent, now / 1000) });
      objects.push({ depth: agent.x + agent.y - 0.35, draw: () => drawChair(agent) });
      const p = positions.get(agent.id);
      objects.push({ depth: p.x + p.y, draw: () => drawCharacter(agent, now / 1000) });
    });
    // 所有可遮挡对象以世界 x+y 排序；不是固定 CSS z-index。
    objects.sort((a, b) => a.depth - b.depth).forEach((object) => object.draw());
    AGENTS.forEach(drawSelection);
    AGENTS.forEach((agent) => drawLabels(agent));
    AGENTS.forEach((agent) => drawBubble(agent, now));
    syncHotspots();
    dirty = false;
  }

  function buildHotspots() {
    const layer = document.getElementById("office-hotspots");
    if (!layer) return;
    layer.innerHTML = "";
    AGENTS.forEach((agent) => {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "hotspot";
      button.dataset.agent = agent.id;
      const label = agent.id === "engineer" ? `${agent.name} · ${agent.role}：查看档案并切换主力/备用工程师` : `${agent.name} · ${agent.role}：查看员工档案`;
      button.title = label;
      button.setAttribute("aria-label", label);
      button.addEventListener("click", () => {
        selected = agent.id;
        dirty = true;
        if (selectHandler) selectHandler(agent.id, agent.talent);
      });
      const enter = () => { hovered = agent.id; dirty = true; };
      const leave = () => { if (hovered === agent.id) hovered = null; dirty = true; };
      button.addEventListener("mouseenter", enter);
      button.addEventListener("focus", enter);
      button.addEventListener("mouseleave", leave);
      button.addEventListener("blur", leave);
      layer.appendChild(button);
      hotspots.set(agent.id, button);
    });
  }

  function clampCamera() {
    camera.zoom = Math.max(0.75, Math.min(1.75, camera.zoom));
    camera.panX = Math.max(-220, Math.min(220, camera.panX));
    camera.panY = Math.max(-150, Math.min(150, camera.panY));
  }

  function cameraChanged() {
    clampCamera();
    dirty = true;
    staticDirty = true;
    const readout = document.getElementById("office-zoom");
    if (readout) readout.textContent = `${Math.round(camera.zoom * 100)}%`;
  }

  function zoomBy(delta) {
    camera.zoom += delta;
    cameraChanged();
  }

  function bindCameraControls() {
    document.getElementById("office-zoom-in")?.addEventListener("click", () => zoomBy(0.25));
    document.getElementById("office-zoom-out")?.addEventListener("click", () => zoomBy(-0.25));
    document.getElementById("office-reset")?.addEventListener("click", () => {
      camera.zoom = 1.3;
      camera.panX = 0;
      camera.panY = 0;
      cameraChanged();
    });
    const viewport = document.querySelector(".office-viewport");
    viewport?.addEventListener("wheel", (event) => {
      event.preventDefault();
      zoomBy(event.deltaY < 0 ? 0.1 : -0.1);
    }, { passive: false });
    canvas.addEventListener("pointerdown", (event) => {
      dragging = { x: event.clientX, y: event.clientY, panX: camera.panX, panY: camera.panY };
      canvas.setPointerCapture(event.pointerId);
      canvas.classList.add("dragging");
    });
    canvas.addEventListener("pointermove", (event) => {
      if (!dragging) return;
      const rect = canvas.getBoundingClientRect();
      camera.panX = dragging.panX + ((event.clientX - dragging.x) / rect.width) * W;
      camera.panY = dragging.panY + ((event.clientY - dragging.y) / rect.height) * H;
      cameraChanged();
    });
    const stopDrag = () => { dragging = null; canvas.classList.remove("dragging"); };
    canvas.addEventListener("pointerup", stopDrag);
    canvas.addEventListener("pointercancel", stopDrag);
  }

  function resize() {
    dpr = Math.max(1, Math.min(3, window.devicePixelRatio || 1));
    canvas.width = Math.round(W * dpr);
    canvas.height = Math.round(H * dpr);
    ctx.imageSmoothingEnabled = false;
    dirty = true;
  }

  function setAgent(agentId, status, message) {
    const entry = state.get(agentId);
    if (!entry) return;
    if (status) {
      const previous = entry.status;
      entry.status = status;
      if (ACTIVE.has(status)) activeAgent = agentId;
      else if (activeAgent === agentId) activeAgent = null;
      if (status === "completed" && previous !== "completed") entry.noticeUntil = performance.now() + 2400;
    }
    if (message) entry.message = message;
    dirty = true;
  }

  function setRequirement(text) {
    requirement = (text || "").trim();
    dirty = true;
  }

  function setSpeech(agentId, text) {
    const entry = state.get(agentId);
    if (!entry) return;
    entry.speech = (text || "").trim();
    dirty = true;
  }

  function setTag(agentId, text) {
    const entry = state.get(agentId);
    if (entry) entry.tag = (text || "").trim();
    dirty = true;
  }

  function resetAgents() {
    state.forEach((entry) => {
      entry.status = "idle";
      entry.message = "";
      entry.speech = "";
      entry.noticeUntil = 0;
    });
    activeAgent = null;
    dirty = true;
  }

  function onSelect(handler) { selectHandler = handler; }

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
  bindCameraControls();
  resize();
  window.addEventListener("resize", resize, { passive: true });
  document.addEventListener("visibilitychange", () => { dirty = true; });
  requestAnimationFrame(frame);
  return { setAgent, setRequirement, setSpeech, setTag, resetAgents, onSelect, drawPortrait };
})();
