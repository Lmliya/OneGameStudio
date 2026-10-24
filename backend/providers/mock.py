"""Mock 模型供应商：不联网、不消耗 token、结果确定。

按 schema 名称返回结构合法的 JSON，让四个员工在没有 API Key 的情况下
也能被同一套 Vessel 独立执行与自动化测试。
Mock 不理解需求语义，只保证结构与流程正确。

审查策略：默认第一次审查不通过、第二次通过，用于演示一次完整的修复闭环。
"""

import json
import re

from backend.providers.base import BaseProvider, ProviderResponse

# 贪吃蛇：可被机械门禁用探针确定性驱动（方向 / 计分 / 重开）
SNAKE_HTML = """
<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Cyber Ocean Snake</title>
<style>
  * { box-sizing: border-box; user-select: none; -webkit-user-select: none; }
  body {
    margin: 0;
    min-height: 100vh;
    background: radial-gradient(circle at 50% 25%, #12355b 0%, #09192f 55%, #040b16 100%);
    color: #e2f1ff;
    font-family: 'Segoe UI', system-ui, -apple-system, sans-serif;
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    padding: 12px;
    overflow: hidden;
  }
  .game-shell {
    display: flex;
    flex-direction: column;
    align-items: center;
    background: rgba(11, 27, 50, 0.72);
    border: 1px solid rgba(56, 189, 248, 0.28);
    border-radius: 18px;
    padding: 14px 16px 16px;
    box-shadow: 0 20px 50px rgba(0, 0, 0, 0.65), 0 0 30px rgba(14, 165, 233, 0.16);
    backdrop-filter: blur(12px);
  }
  .top-bar {
    width: 400px;
    display: flex;
    align-items: center;
    justify-content: space-between;
    margin-bottom: 10px;
  }
  .brand {
    display: flex;
    align-items: center;
    gap: 8px;
    font-weight: 800;
    font-size: 15px;
    letter-spacing: 0.6px;
    color: #38bdf8;
    text-shadow: 0 0 12px rgba(56, 189, 248, 0.45);
  }
  .brand-dot {
    width: 9px;
    height: 9px;
    border-radius: 50%;
    background: #2dd4bf;
    box-shadow: 0 0 10px #2dd4bf;
  }
  .ctrl-group {
    display: flex;
    gap: 6px;
  }
  .icon-btn {
    background: rgba(15, 39, 68, 0.85);
    color: #93c5fd;
    border: 1px solid rgba(56, 189, 248, 0.3);
    border-radius: 6px;
    padding: 4px 9px;
    font-size: 12px;
    cursor: pointer;
    transition: all 0.15s ease;
  }
  .icon-btn:hover {
    background: rgba(56, 189, 248, 0.2);
    color: #fff;
    border-color: #38bdf8;
  }
  #hud {
    width: 400px;
    display: grid;
    grid-template-columns: repeat(3, 1fr);
    gap: 8px;
    margin-bottom: 10px;
  }
  .stat-card {
    background: rgba(7, 19, 36, 0.78);
    border: 1px solid rgba(56, 189, 248, 0.2);
    border-radius: 10px;
    padding: 6px 10px;
    display: flex;
    flex-direction: column;
    align-items: center;
  }
  .stat-label {
    font-size: 10px;
    text-transform: uppercase;
    letter-spacing: 1px;
    color: #7dd3fc;
    opacity: 0.8;
  }
  .stat-val {
    font-size: 18px;
    font-weight: 800;
    font-family: 'Consolas', 'SF Mono', monospace;
    color: #f0f9ff;
    margin-top: 1px;
  }
  #score { color: #2dd4bf; text-shadow: 0 0 10px rgba(45, 212, 191, 0.45); }
  #best { color: #38bdf8; }
  #speed { color: #facc15; }
  .stage-wrap {
    position: relative;
    width: 400px;
    height: 400px;
    border-radius: 12px;
    overflow: hidden;
    box-shadow: 0 0 25px rgba(56, 189, 248, 0.25), inset 0 0 18px rgba(0, 0, 0, 0.6);
    border: 2px solid #38bdf8;
  }
  canvas {
    display: block;
    background: #0b1d33;
  }
  #restart {
    margin-top: 12px;
    padding: 9px 24px;
    background: linear-gradient(135deg, #0ea5e9 0%, #2dd4bf 100%);
    color: #041322;
    border: 0;
    border-radius: 999px;
    font-size: 14px;
    font-weight: 800;
    letter-spacing: 0.5px;
    cursor: pointer;
    box-shadow: 0 6px 20px rgba(45, 212, 191, 0.4);
    transition: transform 0.15s ease, box-shadow 0.15s ease;
  }
  #restart:hover {
    transform: translateY(-1px) scale(1.03);
    box-shadow: 0 8px 25px rgba(56, 189, 248, 0.65);
  }
  #restart:active { transform: translateY(1px); }
  .footer-bar {
    width: 400px;
    display: flex;
    align-items: center;
    justify-content: space-between;
    margin-top: 10px;
    font-size: 11px;
    color: #93c5fd;
    opacity: 0.85;
  }
  .dpad {
    display: flex;
    gap: 5px;
  }
  .dpad-btn {
    width: 28px;
    height: 26px;
    border-radius: 6px;
    border: 1px solid rgba(56, 189, 248, 0.3);
    background: rgba(15, 39, 68, 0.75);
    color: #e0f2fe;
    font-size: 12px;
    cursor: pointer;
    display: flex;
    align-items: center;
    justify-content: center;
  }
  .dpad-btn:hover { background: rgba(56, 189, 248, 0.28); }
</style>
</head>
<body>
  <div class="game-shell">
    <div class="top-bar">
      <div class="brand"><span class="brand-dot"></span>CYBER OCEAN SNAKE</div>
      <div class="ctrl-group">
        <button type="button" class="icon-btn" id="pauseBtn" title="空格键暂停/继续">暂停</button>
        <button type="button" class="icon-btn" id="soundBtn" title="切换音效">音效: 开</button>
      </div>
    </div>

    <div id="hud">
      <div class="stat-card">
        <span class="stat-label">SCORE</span>
        <span class="stat-val" id="score">0</span>
      </div>
      <div class="stat-card">
        <span class="stat-label">BEST</span>
        <span class="stat-val" id="best">0</span>
      </div>
      <div class="stat-card">
        <span class="stat-label">SPEED</span>
        <span class="stat-val" id="speed">1.0x</span>
      </div>
    </div>

    <div class="stage-wrap">
      <canvas id="game" width="400" height="400"></canvas>
    </div>

    <button id="restart" hidden>重新开始</button>

    <div class="footer-bar">
      <span>方向键 / WASD 移动 · 空格暂停</span>
      <div class="dpad">
        <button type="button" class="dpad-btn" data-dir="left" aria-label="左">◀</button>
        <button type="button" class="dpad-btn" data-dir="up" aria-label="上">▲</button>
        <button type="button" class="dpad-btn" data-dir="down" aria-label="下">▼</button>
        <button type="button" class="dpad-btn" data-dir="right" aria-label="右">▶</button>
      </div>
    </div>
  </div>

<script>
(function () {
  var CELL = 20, COLS = 20, BASE_TICK = 120;
  var STORAGE_KEY = 'ogs_cyber_blue_snake_best_v1';
  var canvas = document.getElementById('game');
  var ctx = canvas.getContext('2d');
  var scoreEl = document.getElementById('score');
  var bestEl = document.getElementById('best');
  var speedEl = document.getElementById('speed');
  var restartBtn = document.getElementById('restart');
  var pauseBtn = document.getElementById('pauseBtn');
  var soundBtn = document.getElementById('soundBtn');

  var snake = [];
  var dir = { x: 1, y: 0 };
  var lastMovedDir = { x: 1, y: 0 };
  var dirQueue = [];
  var food = { x: 5, y: 5 };
  var bonusFood = null;
  var foodsEaten = 0;
  var score = 0;
  var bestScore = 0;
  var tickMs = BASE_TICK;
  var over = false;
  var paused = false;
  var newRecord = false;
  var timer = null;
  var rafId = null;
  var soundEnabled = true;
  var audioCtx = null;
  var particles = [];
  var popups = [];
  var shakeFrames = 0;

  try {
    bestScore = parseInt(localStorage.getItem(STORAGE_KEY) || '0', 10) || 0;
  } catch (e) { bestScore = 0; }
  bestEl.textContent = String(bestScore);

  function playTone(freq, type, duration, vol, slideTo) {
    if (!soundEnabled) return;
    try {
      var AC = window.AudioContext || window.webkitAudioContext;
      if (!AC) return;
      if (!audioCtx) audioCtx = new AC();
      if (audioCtx.state === 'suspended') audioCtx.resume();
      var osc = audioCtx.createOscillator();
      var gain = audioCtx.createGain();
      osc.type = type || 'sine';
      osc.frequency.setValueAtTime(freq, audioCtx.currentTime);
      if (slideTo) {
        osc.frequency.exponentialRampToValueAtTime(slideTo, audioCtx.currentTime + duration);
      }
      gain.gain.setValueAtTime(vol || 0.08, audioCtx.currentTime);
      gain.gain.exponentialRampToValueAtTime(0.001, audioCtx.currentTime + duration);
      osc.connect(gain);
      gain.connect(audioCtx.destination);
      osc.start();
      osc.stop(audioCtx.currentTime + duration);
    } catch (e) {}
  }

  function sfxEat() {
    playTone(520, 'triangle', 0.09, 0.09, 780);
    setTimeout(function () { playTone(780, 'sine', 0.11, 0.07, 1040); }, 45);
  }
  function sfxBonus() {
    playTone(587, 'triangle', 0.08, 0.1, 880);
    setTimeout(function () { playTone(880, 'triangle', 0.09, 0.1, 1174); }, 55);
    setTimeout(function () { playTone(1174, 'sine', 0.16, 0.1, 1568); }, 110);
  }
  function sfxOver() {
    playTone(240, 'sawtooth', 0.28, 0.09, 75);
  }

  function randCell() { return Math.floor(Math.random() * COLS); }

  function isOccupied(x, y) {
    for (var i = 0; i < snake.length; i++) {
      if (snake[i].x === x && snake[i].y === y) return true;
    }
    return false;
  }

  function placeFood() {
    var p, guard = 0;
    do {
      p = { x: randCell(), y: randCell() };
      guard++;
    } while (isOccupied(p.x, p.y) && guard < 500);
    food = p;
  }

  function maybeSpawnBonus() {
    if (bonusFood) return;
    var p, guard = 0;
    do {
      p = { x: randCell(), y: randCell(), ttl: 45, maxTtl: 45 };
      guard++;
    } while ((isOccupied(p.x, p.y) || (p.x === food.x && p.y === food.y)) && guard < 500);
    bonusFood = p;
  }

  function spawnBurst(gx, gy, color, count) {
    var cx = gx * CELL + CELL / 2;
    var cy = gy * CELL + CELL / 2;
    for (var i = 0; i < (count || 14); i++) {
      var ang = (Math.PI * 2 * i) / (count || 14) + (Math.random() - 0.5) * 0.4;
      var spd = 1.2 + Math.random() * 2.6;
      particles.push({
        x: cx,
        y: cy,
        vx: Math.cos(ang) * spd,
        vy: Math.sin(ang) * spd,
        r: 2 + Math.random() * 2.5,
        alpha: 1,
        color: color
      });
    }
  }

  function spawnPopup(gx, gy, text, color) {
    popups.push({
      x: gx * CELL + CELL / 2,
      y: gy * CELL + 6,
      text: text,
      color: color || '#2dd4bf',
      alpha: 1,
      vy: -0.9
    });
  }

  function updateSpeed() {
    var target = Math.max(68, BASE_TICK - Math.floor(score / 30) * 6);
    if (target !== tickMs) {
      tickMs = target;
      if (timer && !over && !paused) {
        clearInterval(timer);
        timer = setInterval(tick, tickMs);
      }
    }
    var mult = (BASE_TICK / tickMs).toFixed(1) + 'x';
    speedEl.textContent = mult;
  }

  function addScore(pts, gx, gy, isBonus) {
    score += pts;
    scoreEl.textContent = String(score);
    if (score > bestScore) {
      bestScore = score;
      newRecord = true;
      bestEl.textContent = String(bestScore);
      try { localStorage.setItem(STORAGE_KEY, String(bestScore)); } catch (e) {}
    }
    updateSpeed();
    spawnPopup(gx, gy, '+' + pts + (isBonus ? ' BONUS!' : ''), isBonus ? '#facc15' : '#2dd4bf');
  }

  function roundRectPath(x, y, w, h, r) {
    var rr = Math.min(r, w / 2, h / 2);
    ctx.beginPath();
    ctx.moveTo(x + rr, y);
    ctx.arcTo(x + w, y, x + w, y + h, rr);
    ctx.arcTo(x + w, y + h, x, y + h, rr);
    ctx.arcTo(x, y + h, x, y, rr);
    ctx.arcTo(x, y, x + w, y, rr);
    ctx.closePath();
  }

  function reset() {
    snake = [{ x: 10, y: 10 }, { x: 9, y: 10 }, { x: 8, y: 10 }];
    dir = { x: 1, y: 0 };
    lastMovedDir = { x: 1, y: 0 };
    dirQueue = [];
    score = 0;
    foodsEaten = 0;
    tickMs = BASE_TICK;
    over = false;
    paused = false;
    newRecord = false;
    bonusFood = null;
    particles = [];
    popups = [];
    shakeFrames = 0;
    scoreEl.textContent = '0';
    speedEl.textContent = '1.0x';
    pauseBtn.textContent = '暂停';
    restartBtn.hidden = true;
    placeFood();
    if (timer) clearInterval(timer);
    timer = setInterval(tick, tickMs);
    draw();
  }

  function gameOver() {
    over = true;
    shakeFrames = 10;
    if (timer) clearInterval(timer);
    restartBtn.hidden = false;
    sfxOver();
    draw();
  }

  function tick() {
    if (over || paused) return;

    if (dirQueue.length > 0) {
      dir = dirQueue.shift();
    }
    lastMovedDir = { x: dir.x, y: dir.y };

    var head = { x: snake[0].x + dir.x, y: snake[0].y + dir.y };
    if (head.x < 0 || head.x >= COLS || head.y < 0 || head.y >= COLS) {
      return gameOver();
    }
    for (var i = 0; i < snake.length; i++) {
      if (snake[i].x === head.x && snake[i].y === head.y) {
        return gameOver();
      }
    }

    snake.unshift(head);

    if (head.x === food.x && head.y === food.y) {
      foodsEaten++;
      addScore(10, head.x, head.y, false);
      spawnBurst(head.x, head.y, '#fb7185', 15);
      sfxEat();
      placeFood();
      if (foodsEaten % 5 === 0) maybeSpawnBonus();
    } else if (bonusFood && head.x === bonusFood.x && head.y === bonusFood.y) {
      addScore(30, head.x, head.y, true);
      spawnBurst(head.x, head.y, '#facc15', 22);
      sfxBonus();
      bonusFood = null;
    } else {
      var tail = snake.pop();
      if (Math.random() < 0.35) {
        particles.push({
          x: tail.x * CELL + CELL / 2,
          y: tail.y * CELL + CELL / 2,
          vx: (Math.random() - 0.5) * 0.5,
          vy: (Math.random() - 0.5) * 0.5,
          r: 1.8,
          alpha: 0.55,
          color: '#38bdf8'
        });
      }
    }

    if (bonusFood) {
      bonusFood.ttl--;
      if (bonusFood.ttl <= 0) bonusFood = null;
    }

    if (dirQueue.length > 0) {
      dir = { x: dirQueue[0].x, y: dirQueue[0].y };
    }

    draw();
  }

  function updateEffects() {
    for (var i = particles.length - 1; i >= 0; i--) {
      var p = particles[i];
      p.x += p.vx;
      p.y += p.vy;
      p.vx *= 0.94;
      p.vy *= 0.94;
      p.alpha -= 0.032;
      if (p.alpha <= 0) particles.splice(i, 1);
    }
    for (var j = popups.length - 1; j >= 0; j--) {
      var pop = popups[j];
      pop.y += pop.vy;
      pop.alpha -= 0.028;
      if (pop.alpha <= 0) popups.splice(j, 1);
    }
    if (shakeFrames > 0) shakeFrames--;
  }

  function draw() {
    var now = Date.now();
    ctx.save();
    if (shakeFrames > 0) {
      var dx = (Math.random() - 0.5) * 5;
      var dy = (Math.random() - 0.5) * 5;
      ctx.translate(dx, dy);
    }

    // 1. 深海蓝棋盘格背景
    for (var r = 0; r < COLS; r++) {
      for (var c = 0; c < COLS; c++) {
        ctx.fillStyle = (r + c) % 2 === 0 ? '#0b1d33' : '#0e243e';
        ctx.fillRect(c * CELL, r * CELL, CELL, CELL);
      }
    }

    // 2. 普通能量水晶食物（带呼吸发光）
    var pulse = 1 + Math.sin(now * 0.008) * 0.12;
    var fx = food.x * CELL + CELL / 2;
    var fy = food.y * CELL + CELL / 2;
    ctx.save();
    ctx.shadowColor = '#fb7185';
    ctx.shadowBlur = 14;
    ctx.fillStyle = '#fb7185';
    ctx.beginPath();
    ctx.arc(fx, fy, (CELL * 0.38) * pulse, 0, Math.PI * 2);
    ctx.fill();
    ctx.fillStyle = '#ffe4e6';
    ctx.beginPath();
    ctx.arc(fx - 2.2, fy - 2.2, 2.2, 0, Math.PI * 2);
    ctx.fill();
    ctx.restore();

    // 3. 限时电光金奖励果
    if (bonusFood) {
      var bx = bonusFood.x * CELL + CELL / 2;
      var by = bonusFood.y * CELL + CELL / 2;
      var bp = 1 + Math.sin(now * 0.015) * 0.16;
      ctx.save();
      ctx.shadowColor = '#facc15';
      ctx.shadowBlur = 16;
      ctx.fillStyle = '#facc15';
      ctx.beginPath();
      ctx.arc(bx, by, (CELL * 0.42) * bp, 0, Math.PI * 2);
      ctx.fill();
      ctx.strokeStyle = 'rgba(250, 204, 21, 0.75)';
      ctx.lineWidth = 2;
      ctx.beginPath();
      ctx.arc(bx, by, CELL * 0.48, -Math.PI / 2, -Math.PI / 2 + (Math.PI * 2 * bonusFood.ttl) / bonusFood.maxTtl);
      ctx.stroke();
      ctx.restore();
    }

    // 4. 绘制渐变流线型蛇身与灵动蛇头
    for (var i = snake.length - 1; i >= 0; i--) {
      var seg = snake[i];
      var isHead = i === 0;
      var ratio = i / Math.max(1, snake.length - 1);
      var pad = isHead ? 1 : 1.5 + ratio * 2.2;
      var sx = seg.x * CELL + pad;
      var sy = seg.y * CELL + pad;
      var sw = CELL - pad * 2;
      var sh = CELL - pad * 2;

      ctx.save();
      if (isHead) {
        ctx.shadowColor = '#2dd4bf';
        ctx.shadowBlur = 12;
        ctx.fillStyle = '#2dd4bf';
      } else {
        var g = Math.round(212 - ratio * 65);
        var b = Math.round(191 + ratio * 55);
        ctx.fillStyle = 'rgb(45,' + g + ',' + b + ')';
      }
      roundRectPath(sx, sy, sw, sh, isHead ? 6 : 5);
      ctx.fill();

      // 蛇头眼睛与高光
      if (isHead) {
        var cx = seg.x * CELL + CELL / 2;
        var cy = seg.y * CELL + CELL / 2;
        var ex1 = cx + dir.x * 3 - dir.y * 4;
        var ey1 = cy + dir.y * 3 + dir.x * 4;
        var ex2 = cx + dir.x * 3 + dir.y * 4;
        var ey2 = cy + dir.y * 3 - dir.x * 4;
        ctx.shadowBlur = 0;
        ctx.fillStyle = '#041322';
        ctx.beginPath();
        ctx.arc(ex1, ey1, 2.3, 0, Math.PI * 2);
        ctx.arc(ex2, ey2, 2.3, 0, Math.PI * 2);
        ctx.fill();
        ctx.fillStyle = '#ffffff';
        ctx.beginPath();
        ctx.arc(ex1 + dir.x * 0.6, ey1 + dir.y * 0.6, 0.9, 0, Math.PI * 2);
        ctx.arc(ex2 + dir.x * 0.6, ey2 + dir.y * 0.6, 0.9, 0, Math.PI * 2);
        ctx.fill();
      }
      ctx.restore();
    }

    // 5. 粒子特效
    for (var k = 0; k < particles.length; k++) {
      var pt = particles[k];
      ctx.save();
      ctx.globalAlpha = Math.max(0, pt.alpha);
      ctx.fillStyle = pt.color;
      ctx.beginPath();
      ctx.arc(pt.x, pt.y, pt.r, 0, Math.PI * 2);
      ctx.fill();
      ctx.restore();
    }

    // 6. 浮动加分飘字
    for (var m = 0; m < popups.length; m++) {
      var pop = popups[m];
      ctx.save();
      ctx.globalAlpha = Math.max(0, pop.alpha);
      ctx.font = 'bold 12px monospace';
      ctx.textAlign = 'center';
      ctx.fillStyle = pop.color;
      ctx.fillText(pop.text, pop.x, pop.y);
      ctx.restore();
    }

    // 7. 暂停遮罩
    if (paused && !over) {
      ctx.fillStyle = 'rgba(4, 15, 30, 0.68)';
      ctx.fillRect(0, 0, canvas.width, canvas.height);
      ctx.fillStyle = '#38bdf8';
      ctx.font = 'bold 22px sans-serif';
      ctx.textAlign = 'center';
      ctx.fillText('已暂停 (PAUSED)', canvas.width / 2, canvas.height / 2 - 6);
      ctx.fillStyle = '#bae6fd';
      ctx.font = '13px sans-serif';
      ctx.fillText('按空格键或点击顶部按钮继续', canvas.width / 2, canvas.height / 2 + 20);
    }

    // 8. 游戏结束结算层
    if (over) {
      ctx.fillStyle = 'rgba(4, 12, 24, 0.78)';
      ctx.fillRect(0, 0, canvas.width, canvas.height);

      ctx.fillStyle = 'rgba(12, 34, 62, 0.92)';
      ctx.strokeStyle = 'rgba(56, 189, 248, 0.5)';
      ctx.lineWidth = 1.5;
      roundRectPath(70, 115, 260, 170, 14);
      ctx.fill();
      ctx.stroke();

      ctx.fillStyle = '#f87171';
      ctx.font = 'bold 26px monospace';
      ctx.textAlign = 'center';
      ctx.fillText('Game Over', canvas.width / 2, 158);

      ctx.fillStyle = '#e0f2fe';
      ctx.font = '15px sans-serif';
      ctx.fillText('本局得分: ' + score + '   最高纪录: ' + bestScore, canvas.width / 2, 196);

      if (newRecord && score > 0) {
        ctx.fillStyle = '#facc15';
        ctx.font = 'bold 13px sans-serif';
        ctx.fillText('★ 新纪录达成 NEW RECORD! ★', canvas.width / 2, 226);
      } else {
        ctx.fillStyle = '#7dd3fc';
        ctx.font = '12px sans-serif';
        ctx.fillText('点击下方「重新开始」或按 Enter 再战一局', canvas.width / 2, 228);
      }
    }

    ctx.restore();
  }

  function renderLoop() {
    updateEffects();
    if (!over) draw();
    else if (shakeFrames > 0 || particles.length > 0) draw();
    rafId = requestAnimationFrame(renderLoop);
  }

  function queueDirection(nx, ny) {
    if (over || paused) return;
    var ref = dirQueue.length > 0 ? dirQueue[dirQueue.length - 1] : lastMovedDir;
    if (nx === -ref.x && ny === -ref.y) return;
    if (nx === ref.x && ny === ref.y) return;
    if (dirQueue.length < 2) {
      dirQueue.push({ x: nx, y: ny });
      dir = { x: dirQueue[0].x, y: dirQueue[0].y };
    }
  }

  function togglePause() {
    if (over) return;
    paused = !paused;
    pauseBtn.textContent = paused ? '继续' : '暂停';
    draw();
  }

  function handleKey(e) {
    var k = e.key;
    if (k === 'ArrowUp' || k === 'w' || k === 'W') {
      e.preventDefault();
      queueDirection(0, -1);
    } else if (k === 'ArrowDown' || k === 's' || k === 'S') {
      e.preventDefault();
      queueDirection(0, 1);
    } else if (k === 'ArrowLeft' || k === 'a' || k === 'A') {
      e.preventDefault();
      queueDirection(-1, 0);
    } else if (k === 'ArrowRight' || k === 'd' || k === 'D') {
      e.preventDefault();
      queueDirection(1, 0);
    } else if (k === ' ' || k === 'p' || k === 'P') {
      e.preventDefault();
      togglePause();
    } else if (k === 'Enter' && over) {
      e.preventDefault();
      reset();
    }
  }

  window.addEventListener('keydown', handleKey);

  restartBtn.addEventListener('click', reset);
  pauseBtn.addEventListener('click', togglePause);
  soundBtn.addEventListener('click', function () {
    soundEnabled = !soundEnabled;
    soundBtn.textContent = soundEnabled ? '音效: 开' : '音效: 关';
  });

  var dpadBtns = document.querySelectorAll('.dpad-btn');
  for (var i = 0; i < dpadBtns.length; i++) {
    dpadBtns[i].addEventListener('click', function () {
      var d = this.getAttribute('data-dir');
      if (d === 'up') queueDirection(0, -1);
      else if (d === 'down') queueDirection(0, 1);
      else if (d === 'left') queueDirection(-1, 0);
      else if (d === 'right') queueDirection(1, 0);
    });
  }

  // 门禁测试探针：只读状态 + 摆放食物，100% 兼容 backend/gate/mechanical.py
  window.__ogsProbe = {
    version: 1,
    state: function () {
      return {
        dir: { x: dir.x, y: dir.y },
        score: score,
        over: over,
        head: { x: snake[0].x, y: snake[0].y },
        length: snake.length,
        tickMs: tickMs
      };
    },
    placeFood: function (x, y) {
      food = { x: x, y: y };
    }
  };

  reset();
  rafId = requestAnimationFrame(renderLoop);
})();
</script>
</body>
</html>
"""

_PRIMARY_OUTPUTS: dict[str, dict] = {
    "prd": {
        "title": "贪吃蛇",
        "genre": "arcade",
        "core_loop": ["移动", "吃食物", "变长", "避免撞墙或撞到自己"],
        "features": ["计分", "随机食物", "游戏结束判定", "结束后可重新开始"],
        "controls": ["方向键移动"],
        "win_condition": "尽可能获得更高分数",
        "lose_condition": "撞墙或撞到自身",
    },
    "game": {
        "title": "贪吃蛇",
        "filename": "snake.html",
        "html": SNAKE_HTML,
        "notes": "单文件 Canvas 2D 实现，无外部依赖",
    },
}

_CREATIVE_PROPOSAL = {
    "innovation": "让背景色随得分阶段变化，强化成长反馈",
    "player_value": "玩家能直观看到自己变强，愿意再开一局",
    "complexity": "low",
    "priority": "high",
    "rationale": "只改 Canvas 绘制颜色，不新增玩法系统，风险可控",
}

_CREATIVE_REVISION = {
    "innovation": "保留换色，但限制为三档颜色，避免干扰食物辨识",
    "player_value": "保留成长反馈，同时不牺牲可读性",
    "complexity": "low",
    "priority": "medium",
    "rationale": "接受交付总监关于对比度的挑战，用更小的改动达成同样目标",
}

_DELIVERY_ASSESSMENT = {
    "risk": "背景与食物颜色过近会影响可读性",
    "feasibility": "feasible",
    "simplification": "只调整背景与网格颜色，不改玩法参数",
    "priority": "medium",
    "rationale": "改动局限在绘制层，机械门禁仍可验证核心玩法",
}

# CREATIVE 下交付总监收到明确“挑战”上下文时给出风险判断，触发创意的一轮修订
_DELIVERY_CHALLENGE = {
    "risk": "高对比度配色可能让食物与蛇身难以区分，影响可玩性",
    "feasibility": "risky",
    "simplification": "限制配色档位，并保留高对比度的食物颜色",
    "priority": "high",
    "rationale": "创意方向可行，但需要收敛颜色数量并优先保证可读性",
}

_CONFLICT_DECISION = {
    "decision": "simplify",
    "summary": "创意总监提出配色反馈，交付总监要求收敛颜色数量以控制风险",
    "rationale": "采纳简化后的方案：保留成长反馈，同时优先保证食物与蛇身的可辨识度",
    "adopted_from": "both",
}


_REVIEW_FAIL = {
    "verdict": "ITERATE",
    "issues": [
        {
            "severity": "high",
            "description": "缺少计分与游戏结束提示",
            "suggestion": "在画面上方显示分数，并在结束时显示可点击的重新开始按钮",
        }
    ],
    "suggestions": ["补充计分 UI 与结束后重开入口"],
    "summary": "核心玩法存在，但缺少反馈与恢复入口，暂不交付。",
}

_REVIEW_PASS = {
    "verdict": "PASS",
    "issues": [],
    "suggestions": [],
    "summary": "玩法与 PRD 一致，机械门禁通过，可交付。",
}


MARKETING_PAYLOAD: dict = {
    "positioning": {
        "game_name": "贪吃蛇",
        "core_gameplay": "方向键控制蛇吃食物变长，撞墙或撞到自己即结束",
        "one_liner": "三分钟一局，看你能把这条蛇养多长",
        "target_players": "喜欢碎片化休闲游戏的玩家",
    },
    "slogan": "摸鱼三分钟，你能让这条蛇活多久？",
    "posts": [
        {
            "kind": "fun",
            "title": "上班摸鱼神器，这条蛇我玩到停不下来",
            "body": (
                "一条蛇，一块屏幕，一个下午。\n"
                "方向键控制，规则简单到不用看教程，"
                "吃一个苹果长一截，撞墙就重来。"
                "卡壳的时候来两把，脑子反而清醒了。"
            ),
            "emojis": ["🐍", "🍎", "🎮"],
            "hashtags": ["#贪吃蛇", "#摸鱼日常", "#休闲游戏"],
        },
        {
            "kind": "challenge",
            "title": "挑战：连续吃 10 个苹果不撞墙，你能做到吗",
            "body": (
                "规则就一条：别撞墙，也别咬到自己。\n"
                "越到后面越长，转弯的余地越小。"
                "玩完在评论区报一下你的最高分，看看谁更能憋。"
            ),
            "emojis": ["🔥", "🏆", "👀"],
            "hashtags": ["#游戏挑战", "#贪吃蛇", "#手速"],
        },
    ],
    "plan": [
        {
            "day": 1,
            "goal": "让身边人先玩上",
            "action": "把游戏链接发到同学群，收集最直接的操作反馈",
            "assets": ["游戏链接", "一句话卖点"],
            "metrics": ["试玩人数", "评论数"],
        },
        {
            "day": 2,
            "goal": "发布第一篇体验向笔记",
            "action": "发布摸鱼场景的小红书笔记",
            "assets": ["第一篇文案", "游戏截图"],
            "metrics": ["曝光量", "收藏数"],
        },
        {
            "day": 3,
            "goal": "收集真实玩家分数",
            "action": "在笔记评论区发起晒分",
            "assets": ["评论区引导话术"],
            "metrics": ["评论数", "互动率"],
        },
        {
            "day": 4,
            "goal": "发布第二篇挑战向笔记",
            "action": "发布挑战文案，引导用户晒最高分",
            "assets": ["第二篇文案", "挑战规则图"],
            "metrics": ["点击率", "点赞数"],
        },
        {
            "day": 5,
            "goal": "沉淀玩法说明",
            "action": "整理一份新手三句话攻略",
            "assets": ["攻略图文"],
            "metrics": ["收藏数"],
        },
        {
            "day": 6,
            "goal": "观察留存",
            "action": "对比两篇笔记带来的复访情况",
            "assets": ["数据记录表"],
            "metrics": ["二次访问率"],
        },
        {
            "day": 7,
            "goal": "复盘首周",
            "action": "汇总有效动作，确定下一周只保留表现最好的渠道",
            "assets": ["首周复盘文档"],
            "metrics": ["互动总量", "有效反馈条数"],
        },
    ],
}


def _review_attempt(user: str) -> int:
    match = re.search(r"审查轮次\s*:\s*(\d+)", user)
    return int(match.group(1)) if match else 1


class MockProvider(BaseProvider):
    default_model = "mock"

    def __init__(self, review_passes_from: int = 2) -> None:
        # 第 N 次及以后的审查返回 PASS；默认第 2 次通过
        self._review_passes_from = review_passes_from

    async def complete(
        self,
        system: str,
        user: str,
        *,
        model: str,
        schema: str | None = None,
        max_tokens: int | None = None,
    ) -> ProviderResponse:
        _ = max_tokens  # Mock 不限制输出长度
        payload = self._payload(user, schema)
        text = json.dumps(payload, ensure_ascii=False)
        return ProviderResponse(
            text=text,
            model=model or self.default_model,
            input_tokens=len(system + user) // 4,
            output_tokens=len(text) // 4,
            cost_usd=0.0,
            # Mock 的 token 是按字符数估算，不是真实用量
            usage_source="estimated",
        )

    def _payload(self, user: str, schema: str | None) -> dict:
        if schema == "review":
            attempt = _review_attempt(user)
            return (
                json.loads(json.dumps(_REVIEW_PASS))
                if attempt >= self._review_passes_from
                else json.loads(json.dumps(_REVIEW_FAIL))
            )
        if schema == "game":
            payload = dict(_PRIMARY_OUTPUTS["game"])
            if "审查意见" in user:
                payload["notes"] = "已按审查意见补充计分与结束提示"
            if "历史版本参考代码" in user:
                payload["notes"] = "在历史版本基础上做增量修改"
            return payload
        if schema == "marketing":
            return json.loads(json.dumps(MARKETING_PAYLOAD))
        if schema == "creative_proposal":
            source = (
                _CREATIVE_REVISION
                if "唯一一轮修订" in user
                else _CREATIVE_PROPOSAL
            )
            return json.loads(json.dumps(source))
        if schema == "delivery_assessment":
            source = (
                _DELIVERY_CHALLENGE
                if "交付总监挑战" in user
                else _DELIVERY_ASSESSMENT
            )
            return json.loads(json.dumps(source))

        payload = json.loads(
            json.dumps(_PRIMARY_OUTPUTS.get(schema or "prd", _PRIMARY_OUTPUTS["prd"]))
        )
        # COO 收到双方意见时必须给出可审计的裁决
        if "创意总监意见" in user and "交付总监意见" in user:
            payload["conflict_decision"] = json.loads(
                json.dumps(_CONFLICT_DECISION)
            )
        return payload
