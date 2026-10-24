// Employee 面板：按岗位展示角色，详情只保留基础信息与已完成任务。
// 所有数据都来自后端，前端不做推断或伪造进度。

(() => {
  const listEl = document.getElementById("talent-list");
  const detailEl = document.getElementById("talent-detail");
  if (!listEl || !detailEl) return;

  let selected = null;
  let rolesByTalent = new Map();

  const escapeHtml = (value) =>
    String(value ?? "").replace(
      /[&<>"']/g,
      (ch) =>
        ({
          "&": "&amp;",
          "<": "&lt;",
          ">": "&gt;",
          '"': "&quot;",
          "'": "&#39;",
        })[ch],
    );

  async function request(path, options) {
    const response = await fetch(path, options);
    if (!response.ok) {
      let detail = `${response.status} ${response.statusText}`;
      try {
        const payload = await response.json();
        if (payload && payload.detail) detail = payload.detail;
      } catch (error) {
        // 保持默认错误文案
      }
      throw new Error(detail);
    }
    return response.json();
  }

  const post = (path, body) => {
    const headers = { "Content-Type": "application/json" };
    const tokenInput = document.getElementById("access-token");
    const token = tokenInput ? tokenInput.value.trim() : "";
    if (token) headers["X-OGS-Token"] = token;
    return request(path, {
      method: "POST",
      headers,
      body: JSON.stringify(body || {}),
    });
  };

  function renderRole(positionId, item) {
    const count = Number(item.completed_count) || 0;
    const tasks = item.completed_tasks || [];
    const taskNames = tasks.map((task) => task.name).join(" · ");
    const active = item.is_active_for_position === true;
    const badge = `<span class="p-badge ${active ? "on" : "off"}">${
      active ? "启用中" : "备用"
    }</span>`;
    const switchBtn = active
      ? ""
      : `<button type="button" class="mini-btn switch" data-position="${escapeHtml(
          positionId,
        )}" data-switch="${escapeHtml(item.talent_name)}">设为启用</button>`;
    return `
      <div class="talent-item ${
        item.talent_name === selected ? "active" : ""
      }" data-talent="${escapeHtml(item.talent_name)}">
        <span class="t-name">${escapeHtml(item.name)} ${badge}</span>
        <span class="t-ver">${escapeHtml(item.role)} · ${escapeHtml(
          item.active_label,
        )}</span>
        <span class="t-stats">已完成 ${count} 个任务</span>
        <span class="t-tasks" title="${escapeHtml(taskNames)}">${
          taskNames ? `任务：${escapeHtml(taskNames)}` : "任务：暂无完成任务"
        }</span>
        ${switchBtn}
      </div>`;
  }

  function renderPositions(positions) {
    listEl.innerHTML = positions
      .map((position) => {
        const roles = position.roles || [];
        return `
        <div class="position-card">
          <div class="p-head">
            <span class="p-title">${escapeHtml(position.title)}</span>
            <span class="p-count">${roles.length} 个角色</span>
          </div>
          ${roles.map((role) => renderRole(position.position, role)).join("")}
        </div>`;
      })
      .join("");
  }

  function renderDetail(talent) {
    const entry = rolesByTalent.get(talent);
    if (!entry) {
      detailEl.innerHTML = '<p class="muted">没有找到该员工。</p>';
      return;
    }
    const { role, position } = entry;
    const tasks = role.completed_tasks || [];
    const active = role.is_active_for_position === true;
    const rows = tasks.length
      ? tasks
          .map(
            (task) => `
        <div class="task-row">
          <code class="task-id">${escapeHtml(task.task_id)}</code>
          <span class="task-name">${escapeHtml(task.name)}</span>
        </div>`,
          )
          .join("")
      : '<p class="muted">暂无已完成任务。</p>';

    detailEl.innerHTML = `
      <div class="talent-head">
        <div>
          <b>${escapeHtml(role.name)}</b>
          <span class="muted">${escapeHtml(role.role)}</span>
        </div>
        <span class="p-badge ${active ? "on" : "off"}">${
          active ? "启用中" : "备用"
        }</span>
      </div>

      <dl class="talent-kv">
        <dt>职位</dt><dd>${escapeHtml(position.title)}</dd>
        <dt>版本</dt><dd>${escapeHtml(role.active_label)}</dd>
        <dt>完成任务</dt><dd>${Number(role.completed_count) || 0} 个</dd>
      </dl>

      <div class="block">
        <h3>完成过的任务</h3>
        <div class="block-body">${rows}</div>
      </div>`;
  }

  function loadDetail(talent) {
    selected = talent;
    listEl.querySelectorAll(".talent-item").forEach((item) => {
      item.classList.toggle("active", item.dataset.talent === talent);
    });
    renderDetail(talent);
  }

  async function switchTalent(position, talent) {
    try {
      await post(`/api/positions/${encodeURIComponent(position)}/switch`, {
        talent_name: talent,
      });
      await loadEmployees();
    } catch (error) {
      detailEl.innerHTML = `<p class="muted">切换失败：${escapeHtml(
        error.message,
      )}</p>`;
    }
  }

  async function loadEmployees() {
    try {
      const positions = await request("/api/employees");
      rolesByTalent = new Map();
      positions.forEach((position) => {
        (position.roles || []).forEach((role) => {
          rolesByTalent.set(role.talent_name, { role, position });
        });
      });
      renderPositions(positions);
      if (selected && rolesByTalent.has(selected)) {
        renderDetail(selected);
      } else {
        const first = positions.flatMap((item) => item.roles || [])[0];
        if (first) loadDetail(first.talent_name);
      }
    } catch (error) {
      listEl.innerHTML = `<p class="muted">加载失败：${escapeHtml(error.message)}</p>`;
    }
  }

  listEl.addEventListener("click", (event) => {
    const switchBtn = event.target.closest("[data-switch]");
    if (switchBtn) {
      switchTalent(switchBtn.dataset.position, switchBtn.dataset.switch);
      return;
    }
    const item = event.target.closest("[data-talent]");
    if (item) loadDetail(item.dataset.talent);
  });

  const employeeTab =
    document.querySelector('[data-tab="employee"]') ||
    document.querySelector('[data-tab="talent"]');
  if (employeeTab) employeeTab.addEventListener("click", loadEmployees);

  // 页面加载时先拉一次，避免用户点开 Employee 时面板还是空的
  loadEmployees();
})();
