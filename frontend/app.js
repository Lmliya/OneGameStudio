// 驾驶舱主控：提交需求、WebSocket 事件、标签页渲染与隔离预览。
// 所有界面状态都来自后端事件或任务快照，前端不伪造任何进度。

const el = (id) => document.getElementById(id);
const statusEl = el("task-status");
const taskIdEl = el("task-id");
const connEl = el("conn");
const officeTaskEl = el("office-task");
const frameEl = el("game-frame");
const previewEmpty = el("preview-empty");
const previewError = el("preview-error");
const previewErrorDetail = el("preview-error-detail");
const gameVersionEl = el("game-version");
const logStrip = el("log-strip");
const logList = el("log-list");

const state = {
  taskId: null,
  task: null,
  artifacts: {},
  history: [],
  logs: [],
  ws: null,
  retry: 0,
  currentVersion: "index.html",
  reconnectTimer: null,
};

const STATUS_CLASS = {
  pending: "badge-wait",
  planning: "badge-work",
  coding: "badge-work",
  reviewing: "badge-work",
  fixing: "badge-warn",
  marketing: "badge-work",
  completed: "badge-ok",
  failed: "badge-danger",
  needs_attention: "badge-warn",
  cancelled: "badge-warn",
};

const STATUS_LABEL = {
  pending: "等待中",
  planning: "COO 规划中",
  coding: "Engineer 编码中",
  reviewing: "Reviewer 审查中",
  fixing: "Engineer 修复中",
  marketing: "Marketer 生成中",
  completed: "已完成",
  failed: "失败",
  needs_attention: "待人工处理",
  cancelled: "已取消",
};

const ESC = {
  "&": "&amp;",
  "<": "&lt;",
  ">": "&gt;",
  '"': "&quot;",
  "'": "&#39;",
};
const esc = (value) => String(value ?? "").replace(/[&<>"']/g, (c) => ESC[c]);

const AGENT_NAME = {
  coo: "COO",
  engineer: "ENGINEER",
  reviewer: "REVIEWER",
  marketer: "MARKETER",
};

// ---------- 通用状态 ----------

function setConn(text, cls) {
  connEl.textContent = text;
  connEl.className = `badge ${cls}`;
}

function setTaskStatus(status) {
  statusEl.textContent = STATUS_LABEL[status] || status;
  statusEl.className = `badge ${STATUS_CLASS[status] || "badge-wait"}`;
}

function showPreviewError(message) {
  previewEmpty.classList.add("hidden");
  previewError.classList.remove("hidden");
  previewErrorDetail.textContent = message;
}

function showPreviewFrame() {
  previewError.classList.add("hidden");
  previewEmpty.classList.add("hidden");
}

// ---------- 日志 ----------

function pushLog(event) {
  state.logs.push(event);
  if (state.logs.length > 300) state.logs = state.logs.slice(-300);
  renderLogs();
}

function logLine(event) {
  const time = (event.ts || "").slice(11, 19) || "--:--:--";
  const agent = AGENT_NAME[event.agent] || event.agent || "-";
  let cls = "log-line";
  if (event.type === "task.failed" || event.status === "error")
    cls += " is-error";
  if (event.type === "review.completed") cls += " is-review";
  return (
    `<div class="${cls}">` +
    `<span class="log-time">${esc(time)}</span>` +
    `<span class="log-agent">${esc(agent)}</span>` +
    `<span class="log-type">${esc(event.type)}</span>` +
    `<span class="log-msg">${esc(event.message)}</span>` +
    `</div>`
  );
}

function renderLogs() {
  const recent = state.logs.slice(-4);
  logStrip.innerHTML = recent.map(logLine).join("");
  logList.innerHTML = state.logs.map(logLine).join("");
  logList.scrollTop = logList.scrollHeight;
}

// ---------- 事件处理 ----------

function applyEvent(event) {
  switch (event.type) {
    case "agent.status_changed":
      if (event.agent && event.status) {
        Office.setAgent(event.agent, event.status, event.message);
      }
      break;
    case "task.status_changed":
      if (event.data && event.data.to) setTaskStatus(event.data.to);
      break;
    case "artifact.created":
      refreshArtifacts();
      break;
    case "task.completed":
      setTaskStatus("completed");
      refreshArtifacts();
      break;
    case "task.failed":
      setTaskStatus("failed");
      break;
    case "task.cancelled":
      setTaskStatus("cancelled");
      break;
    default:
      break;
  }
  pushLog(event);
  if (event.type === "review.completed") renderReview();
}

function handleMessage(payload) {
  if (!payload || payload.type === "ping") return;
  if (payload.type === "task.snapshot") {
    hydrate(payload.task);
    return;
  }
  applyEvent(payload);
}

// 断线重连后由快照重建界面，避免漏事件导致状态错乱
function hydrate(task) {
  if (!task) return;
  state.task = task;
  setTaskStatus(task.status);
  Office.setRequirement(task.requirement);
  Office.resetAgents();
  officeTaskEl.textContent = task.requirement;

  state.logs = [];
  (task.events || []).forEach((event) => {
    if (event.agent && event.status) {
      Office.setAgent(event.agent, event.status, event.message);
    }
    state.logs.push({
      type: event.type,
      message: event.message,
      agent: event.agent,
      status: event.status,
      ts: event.created_at,
    });
  });
  renderLogs();
  refreshArtifacts();
}

// ---------- WebSocket ----------

function scheduleReconnect() {
  if (!state.taskId) return;
  clearTimeout(state.reconnectTimer);
  const delay = Math.min(1000 * 2 ** state.retry, 8000);
  state.retry += 1;
  state.reconnectTimer = setTimeout(() => connect(state.taskId), delay);
}

function connect(taskId) {
  if (state.ws) {
    state.ws.onclose = null;
    state.ws.close();
  }
  const protocol = location.protocol === "https:" ? "wss" : "ws";
  const ws = new WebSocket(`${protocol}://${location.host}/ws/tasks/${taskId}`);
  state.ws = ws;

  ws.onopen = () => {
    state.retry = 0;
    setConn("事件已连接", "badge-ok");
  };
  ws.onmessage = (event) => {
    try {
      handleMessage(JSON.parse(event.data));
    } catch (error) {
      console.warn("事件解析失败", error);
    }
  };
  ws.onerror = () => setConn("连接异常", "badge-warn");
  ws.onclose = () => {
    setConn("重连中…", "badge-warn");
    scheduleReconnect();
  };
}

// ---------- 产物 ----------

async function refreshArtifacts() {
  if (!state.taskId) return;
  try {
    const [artifacts, history] = await Promise.all([
      fetch(`/api/tasks/${state.taskId}/artifacts`).then((r) =>
        r.ok ? r.json() : {},
      ),
      fetch(`/api/tasks/${state.taskId}/history`).then((r) =>
        r.ok ? r.json() : [],
      ),
    ]);
    state.artifacts = artifacts || {};
    state.history = history || [];
    renderReview();
    renderMarketing();
    updatePreviewAvailability();
  } catch (error) {
    console.warn("产物读取失败", error);
  }
}

function parsed(name) {
  const text = state.artifacts[name];
  if (!text) return null;
  try {
    return JSON.parse(text);
  } catch (error) {
    return null;
  }
}

function updatePreviewAvailability() {
  if (!state.artifacts["index.html"]) {
    previewError.classList.add("hidden");
    previewEmpty.classList.remove("hidden");
    gameVersionEl.textContent = "尚无产物";
    return;
  }
  const versions = state.history.filter((name) => name.endsWith(".html"));
  gameVersionEl.textContent = `当前版本 · 历史 ${versions.length} 个`;
  if (frameEl.dataset.task !== `${state.taskId}/${state.currentVersion}`) {
    loadPreview(state.currentVersion);
  }
}

// 预览安全检查：先确认文件存在且非空，再把沙箱 iframe 指向隔离预览源
async function loadPreview(version) {
  if (!state.taskId) return;
  state.currentVersion = version;
  const url = `/preview/${state.taskId}/${version}?t=${Date.now()}`;
  try {
    const response = await fetch(url, { cache: "no-store" });
    if (!response.ok) {
      showPreviewError(`预览源返回 ${response.status}`);
      return;
    }
    const html = await response.text();
    if (!html.trim()) {
      showPreviewError("游戏文件为空");
      return;
    }
    frameEl.dataset.task = `${state.taskId}/${version}`;
    frameEl.src = url;
    gameVersionEl.textContent = version.includes("history")
      ? `历史版本 ${version.replace("history/index.", "").replace(".html", "").toUpperCase()}`
      : "当前版本";
    showPreviewFrame();
  } catch (error) {
    showPreviewError(error.message || "预览加载失败");
  }
}

// ---------- Review 标签页 ----------

function renderReview() {
  const gate = parsed("gate.json");
  const review = parsed("review.json");
  const versions = state.history.filter((name) => name.endsWith(".html"));
  const body = el("review-body");

  if (!gate && !review) {
    body.innerHTML = '<p class="muted">审查结果尚未生成。</p>';
    return;
  }

  let html = "";

  if (review) {
    const pass = review.verdict === "PASS";
    html += `
      <div class="block">
        <h3>审查结论</h3>
        <div class="block-body">
          <span class="verdict ${pass ? "verdict-pass" : "verdict-iterate"}">${esc(
            review.verdict,
          )}</span>
          ${review.forced_by_gate ? '<span class="muted"> · 机械门禁强制改判</span>' : ""}
          <div style="margin-top:8px">${esc(review.summary)}</div>
        </div>
      </div>`;
    if ((review.issues || []).length) {
      html += `
        <div class="block">
          <h3>发现的问题（${review.issues.length}）</h3>
          <div class="block-body">
            <ul class="plain">${review.issues
              .map(
                (issue) =>
                  `<li><strong>${esc(issue.severity)}</strong> · ${esc(
                    issue.description,
                  )}<br/><span class="muted">建议：${esc(issue.suggestion)}</span></li>`,
              )
              .join("")}</ul>
          </div>
        </div>`;
    }
    if ((review.suggestions || []).length) {
      html += `
        <div class="block">
          <h3>修复建议</h3>
          <div class="block-body"><ul class="plain">${review.suggestions
            .map((item) => `<li>${esc(item)}</li>`)
            .join("")}</ul></div>
        </div>`;
    }
  }

  if (gate) {
    html += `
      <div class="block">
        <h3>机械门禁 · ${gate.passed ? "通过" : "未通过"}</h3>
        <div class="block-body">
          <table class="checks">
            <thead><tr><th>检查项</th><th>状态</th><th>说明</th></tr></thead>
            <tbody>${(gate.checks || [])
              .map(
                (check) =>
                  `<tr><td>${esc(check.title)}</td><td class="status-${esc(
                    check.status,
                  )}">${esc(check.status)}</td><td>${esc(check.detail)}</td></tr>`,
              )
              .join("")}</tbody>
          </table>
        </div>
      </div>`;
  }

  html += `
    <div class="block">
      <h3>版本记录</h3>
      <div class="block-body">
        <div class="version-list" id="version-list">
          <button type="button" data-version="index.html" class="${
            state.currentVersion === "index.html" ? "current" : ""
          }">当前</button>
          ${versions
            .map((name) => {
              const label = name
                .replace("history/index.", "")
                .replace(".html", "");
              return `<button type="button" data-version="${esc(name)}" class="${
                state.currentVersion === name ? "current" : ""
              }">${esc(label.toUpperCase())}</button>`;
            })
            .join("")}
        </div>
        <p class="muted" style="margin-top:8px">历史版本只读，用于对比修复前后差异。</p>
      </div>
    </div>`;

  body.innerHTML = html;
  body.querySelectorAll("[data-version]").forEach((button) => {
    button.addEventListener("click", () => {
      document.querySelector('[data-tab="game"]').click();
      loadPreview(button.dataset.version);
      renderReview();
    });
  });
}

// ---------- Marketing 标签页 ----------

function renderMarketing() {
  const kit = parsed("marketing_kit.json");
  const body = el("marketing-body");
  if (!kit) {
    body.innerHTML = '<p class="muted">营销素材会在审查通过后生成。</p>';
    return;
  }

  const pos = kit.positioning || {};
  const posts = (kit.posts || [])
    .map(
      (post) => `
      <div class="post-card">
        <div class="post-title">${esc(post.title)}</div>
        <div>${esc(post.body).replace(/\n/g, "<br/>")}</div>
        <div style="margin-top:6px">${esc((post.emojis || []).join(" "))}</div>
        <div class="hashtags">${esc((post.hashtags || []).join(" "))}</div>
        <div class="muted" style="margin-top:4px">${
          post.kind === "fun" ? "趣味体验向" : "挑战互动向"
        }</div>
      </div>`,
    )
    .join("");

  const plan = (kit.plan || [])
    .map(
      (day) =>
        `<tr><td>D${esc(day.day)}</td><td>${esc(day.goal)}</td><td>${esc(
          day.action,
        )}</td><td>${esc((day.assets || []).join("、"))}</td><td>${esc(
          (day.metrics || []).join("、"),
        )}</td></tr>`,
    )
    .join("");

  body.innerHTML = `
    <div class="block">
      <h3>游戏定位</h3>
      <div class="block-body">
        <div><strong>${esc(pos.game_name)}</strong></div>
        <div class="muted">${esc(pos.core_gameplay)}</div>
        <div style="margin-top:6px">一句话卖点：${esc(pos.one_liner)}</div>
        <div class="muted">目标玩家：${esc(pos.target_players)}</div>
      </div>
    </div>
    <div class="block">
      <h3>Slogan</h3>
      <div class="block-body"><span style="color:#7ee787">${esc(kit.slogan)}</span></div>
    </div>
    <div class="block">
      <h3>宣发文案</h3>
      <div class="block-body">${posts}</div>
    </div>
    <div class="block">
      <h3>首周推广计划</h3>
      <div class="block-body" style="padding:0">
        <table class="plan-table">
          <thead><tr><th>Day</th><th>目标</th><th>动作</th><th>素材</th><th>指标</th></tr></thead>
          <tbody>${plan}</tbody>
        </table>
      </div>
    </div>`;
}

// ---------- 标签切换 ----------

document.querySelectorAll("#tabs button").forEach((button) => {
  button.addEventListener("click", () => {
    document
      .querySelectorAll("#tabs button")
      .forEach((b) => b.classList.remove("active"));
    button.classList.add("active");
    document
      .querySelectorAll(".tab-pane")
      .forEach((pane) => pane.classList.add("hidden"));
    el(`tab-${button.dataset.tab}`).classList.remove("hidden");
    if (button.dataset.tab === "game" && state.artifacts["index.html"]) {
      loadPreview(state.currentVersion);
    }
  });
});

// ---------- 提交任务 ----------

async function submitRequirement(requirement) {
  const submitBtn = el("submit");
  submitBtn.disabled = true;
  try {
    const response = await fetch("/api/tasks", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ requirement }),
    });
    const data = await response.json();
    if (response.status === 409 && data.detail && data.detail.task_id) {
      attachTask(data.detail.task_id);
      return;
    }
    if (!response.ok) {
      throw new Error(data.detail || `HTTP ${response.status}`);
    }
    attachTask(data.task_id);
  } catch (error) {
    pushLog({
      type: "task.failed",
      message: `提交失败：${error.message}`,
      ts: new Date().toISOString(),
    });
    setTaskStatus("failed");
  } finally {
    submitBtn.disabled = false;
  }
}

function attachTask(taskId) {
  state.taskId = taskId;
  state.task = null;
  state.artifacts = {};
  state.history = [];
  state.currentVersion = "index.html";
  state.logs = [];
  state.retry = 0;
  taskIdEl.textContent = taskId;
  localStorage.setItem("ogs_task", taskId);
  frameEl.dataset.task = "";
  frameEl.removeAttribute("src");
  previewEmpty.classList.remove("hidden");
  previewError.classList.add("hidden");
  renderLogs();
  connect(taskId);
}

el("ceo-form").addEventListener("submit", (event) => {
  event.preventDefault();
  const requirement = el("requirement").value.trim();
  if (!requirement) return;
  submitRequirement(requirement);
});

el("reload-preview").addEventListener("click", () =>
  loadPreview(state.currentVersion),
);

// ---------- 启动 ----------

async function boot() {
  try {
    const health = await fetch("/api/health").then((r) => r.json());
    setConn(health.mock_mode ? "Mock 模式" : "真实模式", "badge-ok");
  } catch (error) {
    setConn("后端未连接", "badge-danger");
    return;
  }

  const saved = localStorage.getItem("ogs_task");
  if (!saved) return;
  try {
    const task = await fetch(`/api/tasks/${saved}`).then((r) => r.json());
    if (task && task.task_id) {
      attachTask(task.task_id);
      hydrate(task);
      el("requirement").value = task.requirement;
    }
  } catch (error) {
    localStorage.removeItem("ogs_task");
  }
}

boot();
