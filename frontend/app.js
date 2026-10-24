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
  versions: [],
  logs: [],
  ws: null,
  retry: 0,
  currentVersion: "index.html",
  reconnectTimer: null,
  mock: false,
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

const SOP_LABEL = {
  fast: "FAST",
  balanced: "BALANCED",
  creative: "CREATIVE",
};

const SOP_CLASS = {
  fast: "badge-ok",
  balanced: "badge-work",
  creative: "badge-warn",
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
  creative: "CREATIVE",
  delivery: "DELIVERY",
  engineer: "ENGINEER",
  reviewer: "REVIEWER",
  marketer: "MARKETER",
};

// ---------- 通用状态 ----------

function setSop(mode) {
  const badge = el("sop-badge");
  if (!mode) {
    badge.textContent = "SOP --";
    badge.className = "badge badge-wait";
    return;
  }
  badge.textContent = `SOP ${SOP_LABEL[mode] || String(mode).toUpperCase()}`;
  badge.className = `badge ${SOP_CLASS[mode] || "badge-wait"}`;
}

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
    case "sop.selected":
      if (event.data && event.data.mode) {
        state.task = state.task || {};
        state.task.sop_mode = event.data.mode;
        state.task.sop_reason = event.data.reason;
        setSop(event.data.mode);
      }
      break;
    case "conflict.opinion":
      if (event.agent) Office.setSpeech(event.agent, event.message);
      renderStudio();
      break;
    case "conflict.resolved":
      if (event.data && event.data.decision) {
        const decision = event.data.decision;
        Office.setSpeech(
          "coo",
          `裁决 ${decision.decision}：${decision.rationale}`,
        );
      }
      renderStudio();
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
  setSop(task.sop_mode);
  Office.setRequirement(task.requirement);
  Office.resetAgents();
  officeTaskEl.textContent = task.requirement;

  state.logs = [];
  (task.events || []).forEach((event) => {
    if (event.agent && event.status) {
      Office.setAgent(event.agent, event.status, event.message);
    }
    // 冲突观点与 COO 裁决同样从真实事件恢复气泡，不伪造文本
    if (event.type === "conflict.opinion" && event.agent) {
      Office.setSpeech(event.agent, event.message);
    }
    if (
      event.type === "conflict.resolved" &&
      event.data &&
      event.data.decision
    ) {
      const decision = event.data.decision;
      Office.setSpeech(
        "coo",
        `裁决 ${decision.decision}：${decision.rationale}`,
      );
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
    const [artifacts, history, versions, task] = await Promise.all([
      fetch(`/api/tasks/${state.taskId}/artifacts`).then((r) =>
        r.ok ? r.json() : {},
      ),
      fetch(`/api/tasks/${state.taskId}/history`).then((r) =>
        r.ok ? r.json() : [],
      ),
      fetch(`/api/tasks/${state.taskId}/versions`).then((r) =>
        r.ok ? r.json() : [],
      ),
      fetch(`/api/tasks/${state.taskId}`).then((r) => (r.ok ? r.json() : null)),
    ]);
    state.artifacts = artifacts || {};
    state.history = history || [];
    state.versions = versions || [];
    if (task) {
      state.task = task;
      setSop(task.sop_mode);
    }
    renderReview();
    renderMarketing();
    renderStudio();
    renderVersionSelect();
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
  if (state.currentVersion === "index.html") {
    gameVersionEl.textContent = `当前版本 · 历史 ${versions.length} 个`;
  }
  if (frameEl.dataset.task !== `${state.taskId}/${state.currentVersion}`) {
    loadPreview(state.currentVersion);
  }
}

function renderVersionSelect() {
  const select = el("version-select");
  const button = el("rollback-version");
  if (!select || !button) return;
  const finalId = state.task ? state.task.final_version_id : null;
  const history = (state.history || [])
    .filter((name) => /^history\/index\.v\d+\.html$/.test(name))
    .map((name) => {
      const label = name.replace("history/index.", "").replace(".html", "");
      return `<option value="${esc(name)}">历史快照 ${esc(label.toUpperCase())}</option>`;
    });
  const versions = (state.versions || []).map((version) => {
    const finalMark = version.version_id === finalId ? " · 最终" : "";
    const label = `完成版本 V${version.version_number} · ${
      SOP_LABEL[version.sop_mode] || version.sop_mode
    }${finalMark}`;
    return `<option value="versions/${esc(version.version_id)}.html">${esc(
      label,
    )}</option>`;
  });
  select.innerHTML = ['<option value="index.html">当前版本</option>']
    .concat(history, versions)
    .join("");

  const selected = state.currentVersion || "index.html";
  select.value = selected;
  if (select.value !== selected) select.value = "index.html";
  button.disabled = select.value === "index.html";
}

async function rollbackVersion() {
  const select = el("version-select");
  const button = el("rollback-version");
  const filename = select ? select.value : "";
  if (!state.taskId || !filename || filename === "index.html") return;
  const label = select.options[select.selectedIndex].textContent;
  button.disabled = true;
  button.textContent = "回退中…";
  try {
    const response = await fetch(`/api/tasks/${state.taskId}/final-version`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ filename }),
    });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) {
      throw new Error(data.detail || `HTTP ${response.status}`);
    }
    state.currentVersion = "index.html";
    await refreshArtifacts();
    await loadPreview("index.html");
    gameVersionEl.textContent = `已回退到 ${label}`;
  } catch (error) {
    gameVersionEl.textContent = `回退失败：${error.message}`;
  } finally {
    button.textContent = "回退到此版本";
    renderVersionSelect();
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
    if (version.startsWith("history/")) {
      gameVersionEl.textContent = `历史版本 ${version
        .replace("history/index.", "")
        .replace(".html", "")
        .toUpperCase()}`;
    } else if (version.startsWith("versions/")) {
      const versionId = version
        .replace(/^versions\//, "")
        .replace(/\.html$/, "");
      const found = (state.versions || []).find(
        (item) => item.version_id === versionId,
      );
      gameVersionEl.textContent = found
        ? `完成版本 V${found.version_number}`
        : "历史完成版本";
    } else {
      gameVersionEl.textContent = "当前版本";
    }
    showPreviewFrame();
    renderVersionSelect();
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

// ---------- Studio 标签页：冲突协作与 SOP 全景 ----------

const DECISION_LABEL = {
  adopt: "采用",
  simplify: "简化",
  reject: "拒绝",
};
const ADOPTED_LABEL = {
  creative: "采纳创意总监",
  delivery: "采纳交付总监",
  both: "双方融合",
  neither: "双方均未采纳",
};
const FEASIBILITY_LABEL = {
  feasible: "可行",
  risky: "有风险",
  infeasible: "不可行",
};
const PRIORITY_LABEL = { high: "高", medium: "中", low: "低" };
const COMPLEXITY_LABEL = { low: "低", medium: "中", high: "高" };

function renderStudio() {
  const body = el("studio-body");
  if (!body) return;

  const task = state.task || {};
  const mode = task.sop_mode;
  const creative = parsed("creative_proposal.json");
  const delivery = parsed("delivery_assessment.json");
  const decision = parsed("conflict_decision.json") || task.conflict_decision;
  const metrics = task.metrics || {};

  let html = `
    <div class="block">
      <h3>SOP · 运行指标</h3>
      <div class="block-body">
        <div class="metric-row">
          <span>模式 <b>${esc(SOP_LABEL[mode] || mode || "待选择")}</b></span>
          <span>调用次数 <b>${esc(metrics.model_calls ?? "-")}</b></span>
          <span>实际耗时 <b>${esc(metrics.elapsed_ms ?? "-")} ms</b></span>
          <span>并行墙钟 <b>${esc(metrics.parallel_wall_ms ?? "-")} ms</b></span>
        </div>
        <div class="muted" style="margin-top:6px">选择原因：${esc(
          task.sop_reason || "尚未记录",
        )}</div>
        ${
          state.mock
            ? '<div class="studio-note">MOCK 模式：以下结构化观点由确定性 Mock 供应商生成，耗时与 token 仅为估算，不代表真实模型性能。</div>'
            : ""
        }
      </div>
    </div>`;

  if (mode === "fast") {
    html += `
      <div class="block">
        <h3>FAST 流程</h3>
        <div class="block-body muted">
          FAST 跳过创意总监、交付总监与营销阶段；机械门禁、AI 审查与修复循环仍完整执行。
        </div>
      </div>`;
  } else {
    html += `<div class="block">
      <h3>创意总监 · Creative Director</h3>
      <div class="block-body">${
        creative
          ? `<div><strong>${esc(creative.innovation)}</strong></div>
             <div style="margin-top:6px">玩家价值：${esc(creative.player_value)}</div>
             <div class="metric-row" style="margin-top:6px">
               <span>复杂度 <b>${esc(COMPLEXITY_LABEL[creative.complexity] || creative.complexity)}</b></span>
               <span>优先级 <b>${esc(PRIORITY_LABEL[creative.priority] || creative.priority)}</b></span>
             </div>
             <div class="muted" style="margin-top:6px">依据：${esc(creative.rationale)}</div>`
          : '<span class="muted">本次运行没有创意总监意见。</span>'
      }</div>
    </div>
    <div class="block">
      <h3>交付总监 · Delivery Director</h3>
      <div class="block-body">${
        delivery
          ? `<div><strong>${esc(delivery.risk)}</strong></div>
             <div style="margin-top:6px">可行性：${esc(
               FEASIBILITY_LABEL[delivery.feasibility] || delivery.feasibility,
             )}</div>
             <div>简化建议：${esc(delivery.simplification)}</div>
             <div class="metric-row" style="margin-top:6px">
               <span>优先级 <b>${esc(PRIORITY_LABEL[delivery.priority] || delivery.priority)}</b></span>
             </div>
             <div class="muted" style="margin-top:6px">依据：${esc(delivery.rationale)}</div>`
          : '<span class="muted">本次运行没有交付总监意见。</span>'
      }</div>
    </div>`;
  }

  if (decision) {
    html += `
      <div class="block">
        <h3>COO 最终决策</h3>
        <div class="block-body">
          <span class="verdict ${
            decision.decision === "reject" ? "verdict-iterate" : "verdict-pass"
          }">${esc(DECISION_LABEL[decision.decision] || decision.decision)}</span>
          <span class="muted"> · ${esc(
            ADOPTED_LABEL[decision.adopted_from] || decision.adopted_from || "",
          )}</span>
          <div style="margin-top:8px">${esc(decision.summary)}</div>
          <div class="muted" style="margin-top:6px">理由：${esc(
            decision.rationale,
          )}</div>
        </div>
      </div>`;
  }

  if ((state.versions || []).length) {
    html += `
      <div class="block">
        <h3>游戏版本记录</h3>
        <div class="block-body">${state.versions
          .map(
            (version) => `
          <div class="version-row">
            <span class="v-label">V${esc(version.version_number)}</span>
            <span class="tag">${esc(SOP_LABEL[version.sop_mode] || version.sop_mode)}</span>
            <span class="muted">来源 ${esc(
              version.source_version_id || "-",
            )}</span>
            <span class="muted">创意 Talent ${esc(
              version.creative_talent_version || "-",
            )}</span>
            <span class="muted">交付 Talent ${esc(
              version.delivery_talent_version || "-",
            )}</span>
          </div>`,
          )
          .join("")}
        </div>
      </div>`;
  }

  body.innerHTML = html;
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
    const payload = { requirement };
    const selected = el("sop-mode").value;
    if (selected !== "auto") payload.sop_mode = selected;
    const sourceVersion = el("source-version").value.trim();
    if (sourceVersion) payload.source_version_id = sourceVersion;

    const headers = { "Content-Type": "application/json" };

    const response = await fetch("/api/tasks", {
      method: "POST",
      headers,
      body: JSON.stringify(payload),
    });
    const data = await response.json();
    if (response.status === 409 && data.detail && data.detail.task_id) {
      attachTask(data.detail.task_id);
      return;
    }
    if (!response.ok) {
      throw new Error(
        typeof data.detail === "string"
          ? data.detail
          : data.detail?.message || `HTTP ${response.status}`,
      );
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
  state.versions = [];
  state.currentVersion = "index.html";
  state.logs = [];
  state.retry = 0;
  setSop(null);
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

el("version-select").addEventListener("change", () => {
  loadPreview(el("version-select").value);
});

el("rollback-version").addEventListener("click", rollbackVersion);

// ---------- 启动 ----------

function renderMode(health) {
  const mode = health.mode || (health.mock_mode ? "demo" : "live");
  const readOnly = mode === "demo" && Boolean(health.read_only);
  const badge = el("mode-badge");
  if (badge) {
    if (mode === "demo") {
      badge.textContent = readOnly ? "DEMO 只读" : "DEMO";
      badge.className = "badge badge-warn";
      badge.title = readOnly
        ? "Demo 模式：只读历史任务回放，不会调用真实模型，也不会产生费用"
        : "Demo 模式：历史任务回放；本地 Mock 运行不会调用真实模型";
    } else if (health.live_ready) {
      badge.textContent = "LIVE";
      badge.className = "badge badge-ok";
      badge.title = "Live 模式：调用真实模型；受访问令牌、并发、频率与预算限制";
    } else {
      badge.textContent = "LIVE 未配置";
      badge.className = "badge badge-danger";
      badge.title =
        "Live 模式未配置完成：需要服务端 LLM_API_KEY、LLM_MODEL 且 MOCK_MODE=false";
    }
  }

  el("requirement").disabled = readOnly;
  el("submit").disabled = readOnly;
  el("sop-mode").disabled = readOnly;
  el("source-version").disabled = readOnly;
}

async function loadDemoTask() {
  try {
    const demo = await fetch("/api/demo").then((r) => r.json());
    const tasks = Array.isArray(demo.tasks) ? demo.tasks : [];
    const task = tasks.find((item) => item.status === "completed") || tasks[0];
    if (!task) {
      el("office-task").textContent = "暂无演示任务";
      return;
    }
    attachTask(task.task_id);
    el("requirement").value = task.name;
  } catch (error) {
    pushLog({
      type: "task.failed",
      message: `演示数据加载失败：${error.message}`,
      ts: new Date().toISOString(),
    });
  }
}

async function boot() {
  let health;
  try {
    health = await fetch("/api/health").then((r) => r.json());
  } catch (error) {
    setConn("后端未连接", "badge-danger");
    return;
  }

  const mode = health.mode || (health.mock_mode ? "demo" : "live");
  state.mode = mode;
  state.mock = Boolean(health.mock_mode);
  renderMode(health);
  setConn(
    mode === "demo"
      ? "Demo 模式"
      : health.live_ready
        ? "Live 模式"
        : "Live 未配置",
    "badge-ok",
  );

  if (mode === "demo") {
    // Demo 始终加载随仓库提交的历史任务，忽略本地残留的任务 ID
    await loadDemoTask();
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
