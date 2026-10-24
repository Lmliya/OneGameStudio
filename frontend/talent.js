// Talent 自进化面板：查看版本 / 经验 / 提案 / 评估，并执行批准与回滚。
// 所有判定与状态都来自后端，前端不做任何本地推断或伪造进度。

(() => {
  const listEl = document.getElementById("talent-list");
  const detailEl = document.getElementById("talent-detail");
  if (!listEl || !detailEl) return;

  const STATUS_TEXT = {
    active: "启用中",
    candidate: "候选",
    inactive: "已停用",
    rejected: "已拒绝",
    verified: "已验证",
    pending: "待处理",
    passed: "已通过",
    failed: "未通过",
    approved: "已批准",
  };

  let selected = null;
  let busy = false;
  let lastDetail = null;

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

  const pct = (value) => `${Math.round((Number(value) || 0) * 100)}%`;
  const tag = (status) =>
    `<span class="tag ${escapeHtml(status)}">${escapeHtml(
      STATUS_TEXT[status] || status,
    )}</span>`;

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

  const post = (path, body) =>
    request(path, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body || {}),
    });

  function setMessage(text, isError = false) {
    const box = document.getElementById("talent-msg");
    if (!box) return;
    box.textContent = text || "";
    box.style.color = isError ? "var(--danger)" : "var(--warn)";
  }

  function taskId() {
    return localStorage.getItem("ogs_task") || "";
  }

  function renderList(items) {
    listEl.innerHTML = items
      .map(
        (item) => `
        <button type="button" class="talent-item ${
          item.talent_name === selected ? "active" : ""
        }" data-talent="${escapeHtml(item.talent_name)}">
          <span class="t-name">${escapeHtml(item.name)}</span>
          <span class="t-ver">${escapeHtml(item.role)} · ${escapeHtml(
            item.active_label,
          )}</span>
        </button>`,
      )
      .join("");
  }

  async function loadTalents() {
    try {
      const items = await request("/api/talents");
      renderList(items);
      if (!selected && items.length) {
        await loadDetail(items[0].talent_name);
      }
    } catch (error) {
      listEl.innerHTML = `<p class="muted">加载失败：${escapeHtml(error.message)}</p>`;
    }
  }

  async function loadDetail(talent) {
    selected = talent;
    listEl.querySelectorAll(".talent-item").forEach((button) => {
      button.classList.toggle("active", button.dataset.talent === talent);
    });
    detailEl.innerHTML = '<p class="muted">加载中…</p>';
    try {
      const data = await request(`/api/talents/${encodeURIComponent(talent)}`);
      renderDetail(data);
    } catch (error) {
      detailEl.innerHTML = `<p class="muted">加载失败：${escapeHtml(
        error.message,
      )}</p>`;
    }
  }

  function renderVersions(data) {
    return data.versions
      .map((version) => {
        const isActive = version.version === data.active_version.version;
        let action = "";
        if (!isActive && version.status !== "rejected") {
          action = `<button type="button" class="mini-btn" data-action="rollback" data-version="${version.version}">
            ${version.status === "inactive" ? "回滚启用" : "启用"}
          </button>`;
        }
        return `
        <div class="version-row">
          <span class="v-label">v${version.version}</span>
          ${tag(version.status)}
          <span class="muted">parent=${version.parent_version ?? "-"}</span>
          <span class="muted">${escapeHtml(version.change_reason || "")}</span>
          <span class="muted">${escapeHtml(version.evaluation_result || "未评估")}</span>
          ${action}
        </div>`;
      })
      .join("");
  }

  function renderLessons(data) {
    if (!data.lessons.length) {
      return '<p class="muted">还没有经验。点击「诊断当前版本」可从固定回归集生成已验证经验。</p>';
    }
    return data.lessons
      .map((lesson) => {
        const actions =
          lesson.status === "candidate"
            ? `<button type="button" class="mini-btn primary" data-action="verify" data-lesson="${escapeHtml(
                lesson.lesson_id,
              )}">验证</button>
               <button type="button" class="mini-btn danger" data-action="reject-lesson" data-lesson="${escapeHtml(
                 lesson.lesson_id,
               )}">拒绝</button>`
            : "";
        return `
        <div class="lesson-row">
          <div>
            <b class="status-${escapeHtml(lesson.status)}">${escapeHtml(
              STATUS_TEXT[lesson.status] || lesson.status,
            )}</b>
            · ${escapeHtml(lesson.related_talent)}
            · ${escapeHtml(lesson.problem)}
          </div>
          <div class="muted">改进：${escapeHtml(lesson.improvement)}</div>
          <div class="muted">证据：${escapeHtml(
            lesson.verification || "（无，模型推测不得当作已验证）",
          )}</div>
          <div class="muted">来源：${escapeHtml(
            lesson.source_project_id || "—",
          )} / ${escapeHtml(lesson.source_version_id || "—")}</div>
          ${actions}
        </div>`;
      })
      .join("");
  }

  function renderEvaluation(evaluation) {
    if (!evaluation) return "";
    const cases = evaluation.cases
      .map(
        (item) =>
          `<div class="muted">${escapeHtml(item.case_id)}：基线 ${
            item.base_detected ? "检出" : "漏检"
          } / 候选 ${item.candidate_detected ? "检出" : "漏检"}</div>`,
      )
      .join("");
    const acceptance = evaluation.acceptance
      .map(
        (item) =>
          `<span class="tag ${item.passed ? "approved" : "failed"}">${escapeHtml(
            item.name,
          )} ${item.passed ? "✓" : "✗"}</span>`,
      )
      .join(" ");
    return `
      <div class="metric-row">
        <span>引擎 <b>${escapeHtml(evaluation.engine)}</b></span>
        <span>检出率 <b>${pct(evaluation.base.detection_rate)} → ${pct(
          evaluation.candidate.detection_rate,
        )}</b></span>
        <span>误报率 <b>${pct(evaluation.base.false_positive_rate)} → ${pct(
          evaluation.candidate.false_positive_rate,
        )}</b></span>
        <span>Token <b>${evaluation.base.tokens} → ${
          evaluation.candidate.tokens
        }</b>（${escapeHtml(evaluation.base.token_source)}）</span>
        <span>结论 <b>${evaluation.passed ? "通过" : "未通过"}</b></span>
      </div>
      <div class="metric-row">${acceptance}</div>
      ${cases}
      <div class="muted">${evaluation.notes.map(escapeHtml).join("；")}</div>`;
  }

  function renderProposals(data) {
    if (!data.proposals.length) {
      return '<p class="muted">还没有提案。先在经验库确认 verified 经验，再生成提案。</p>';
    }
    const byId = new Map(
      data.evaluations.map((item) => [item.evaluation_id, item]),
    );
    return data.proposals
      .map((proposal) => {
        const evaluation = byId.get(proposal.evaluation_id);
        const actions = [];
        if (proposal.approval_status === "pending") {
          if (!proposal.evaluation_id) {
            actions.push(
              `<button type="button" class="mini-btn" data-action="evaluate" data-proposal="${escapeHtml(
                proposal.proposal_id,
              )}">运行回归评估</button>`,
            );
          }
          if (proposal.evaluation_status === "passed") {
            actions.push(
              `<button type="button" class="mini-btn primary" data-action="approve" data-proposal="${escapeHtml(
                proposal.proposal_id,
              )}">批准并启用</button>`,
            );
          }
          actions.push(
            `<button type="button" class="mini-btn danger" data-action="reject-proposal" data-proposal="${escapeHtml(
              proposal.proposal_id,
            )}">拒绝</button>`,
          );
        }
        return `
        <div class="proposal-card">
          <h4>${escapeHtml(proposal.proposal_id)}</h4>
          <div class="metric-row">
            <span>${escapeHtml(proposal.target_talent)} v${proposal.base_version} → v${
              proposal.candidate_version ?? "?"
            }</span>
            <span>证据 <b>${proposal.supporting_evidence.length}</b> 条</span>
            ${tag(proposal.evaluation_status)}
            ${tag(proposal.approval_status)}
          </div>
          <div class="muted">收益：${escapeHtml(proposal.expected_benefit)}</div>
          <div class="muted">风险：${escapeHtml(proposal.risks.join("；"))}</div>
          ${renderEvaluation(evaluation)}
          <div class="proposal-actions">${actions.join("")}</div>
        </div>`;
      })
      .join("");
  }

  function renderDetail(data) {
    lastDetail = data;
    const active = data.active_version;
    const hasTask = Boolean(taskId());
    detailEl.innerHTML = `
      <div class="talent-head">
        <div>
          <b>${escapeHtml(data.name)}</b>
          <span class="muted">${escapeHtml(data.role)}</span>
        </div>
        <div>${tag(active.status)} <span class="muted">${escapeHtml(
          active.label,
        )}</span></div>
      </div>
      <div class="talent-actions">
        <button type="button" class="mini-btn" data-action="refresh">刷新</button>
        <button type="button" class="mini-btn" data-action="diagnose">诊断当前版本</button>
        <button type="button" class="mini-btn primary" data-action="propose">用已验证经验生成提案</button>
        <button type="button" class="mini-btn" data-action="extract" ${
          hasTask ? "" : "disabled"
        }>从当前任务提取经验</button>
      </div>
      <div id="talent-msg" class="talent-msg"></div>

      <div class="block">
        <h3>当前启用版本</h3>
        <div class="block-body">
          <dl class="talent-kv">
            <dt>版本</dt><dd>${escapeHtml(active.label)}</dd>
            <dt>变更原因</dt><dd>${escapeHtml(active.change_reason || "—")}</dd>
            <dt>评估</dt><dd>${escapeHtml(active.evaluation_result || "未评估")}</dd>
          </dl>
          <details>
            <summary class="muted">查看提示词</summary>
            <div class="muted" style="white-space: pre-wrap; font-size: 11px">${escapeHtml(
              active.prompt,
            )}</div>
          </details>
          <div class="muted">检查清单</div>
          <ul class="check-list">
            ${active.checklist.map((item) => `<li>${escapeHtml(item)}</li>`).join("")}
          </ul>
        </div>
      </div>

      <div class="block">
        <h3>版本历史（不可变）</h3>
        <div class="block-body">${renderVersions(data)}</div>
      </div>

      <div class="block">
        <h3>经验库</h3>
        <div class="block-body">${renderLessons(data)}</div>
      </div>

      <div class="block">
        <h3>进化提案</h3>
        <div class="block-body">${renderProposals(data)}</div>
      </div>

      <div class="block">
        <h3>启用审计</h3>
        <div class="block-body">
          ${data.audit
            .slice()
            .reverse()
            .map(
              (entry) =>
                `<div class="lesson-row muted">${escapeHtml(entry.at)} · ${escapeHtml(
                  entry.action,
                )} · v${entry.from_version ?? "?"} → v${entry.to_version} · ${escapeHtml(
                  entry.reason,
                )}</div>`,
            )
            .join("")}
        </div>
      </div>
    `;
  }

  async function runAction(action, element) {
    if (busy) return;
    busy = true;
    element.disabled = true;
    let message = "";
    try {
      if (action === "refresh") {
        await loadDetail(selected);
        return;
      }
      if (action === "diagnose") {
        const result = await post(`/api/talents/${selected}/diagnose`);
        message = `诊断完成：基线检出率 ${pct(
          result.evaluation.base.detection_rate,
        )}，新增 ${result.created_lessons.length} 条已验证经验。`;
      } else if (action === "propose") {
        const used = new Set();
        (lastDetail.proposals || [])
          .filter((item) => item.approval_status !== "rejected")
          .forEach((item) =>
            item.supporting_evidence.forEach((id) => used.add(id)),
          );
        const lessonIds = (lastDetail.lessons || [])
          .filter(
            (item) => item.status === "verified" && !used.has(item.lesson_id),
          )
          .map((item) => item.lesson_id);
        if (!lessonIds.length) {
          throw new Error("没有可用的已验证经验，请先诊断当前版本或验证经验。");
        }
        const result = await post("/api/evolution/proposals", {
          target_talent: selected,
          lesson_ids: lessonIds,
        });
        message = `已生成提案，候选版本 v${result.candidate_version.version}，请先运行回归评估。`;
      } else if (action === "extract") {
        const id = taskId();
        if (!id) throw new Error("没有当前任务，请先提交一次需求。");
        const result = await post(`/api/tasks/${id}/lessons`);
        message = `从任务 ${id} 提取了 ${result.count} 条经验。`;
      } else if (action === "rollback") {
        const version = Number(element.dataset.version);
        const reason = window.prompt(`回滚到 v${version} 的原因：`, "用户回滚");
        if (reason === null) return;
        await post(`/api/talents/${selected}/rollback`, { version, reason });
        message = `已启用 v${version}。`;
      } else if (action === "verify") {
        const id = element.dataset.lesson;
        const verification = window.prompt(
          "请输入可追溯的验证证据（例如任务 ID + gate.json 检查项）：",
          "",
        );
        if (!verification) return;
        await post(`/api/lessons/${id}/verify`, { verification });
        message = "经验已验证。";
      } else if (action === "reject-lesson") {
        const id = element.dataset.lesson;
        if (!window.confirm("确认拒绝这条经验？")) return;
        await post(`/api/lessons/${id}/reject`);
        message = "经验已拒绝。";
      } else if (action === "evaluate") {
        const id = element.dataset.proposal;
        const result = await post(`/api/evolution/proposals/${id}/evaluate`);
        message = `评估完成：${result.evaluation.passed ? "通过" : "未通过"}，候选检出率 ${pct(
          result.evaluation.candidate.detection_rate,
        )}。`;
      } else if (action === "approve") {
        const id = element.dataset.proposal;
        if (!window.confirm("批准该提案并立即启用候选版本？")) return;
        const result = await post(`/api/evolution/proposals/${id}/approve`);
        message = `已启用 ${result.active_version.label}。`;
      } else if (action === "reject-proposal") {
        const id = element.dataset.proposal;
        if (!window.confirm("确认拒绝该提案？候选版本会一并标记为拒绝。"))
          return;
        await post(`/api/evolution/proposals/${id}/reject`);
        message = "提案已拒绝。";
      }
      await loadDetail(selected);
      await loadTalents();
      if (message) setMessage(message);
    } catch (error) {
      setMessage(error.message, true);
    } finally {
      busy = false;
    }
  }

  detailEl.addEventListener("click", (event) => {
    const button = event.target.closest("button[data-action]");
    if (!button) return;
    runAction(button.dataset.action, button);
  });

  document
    .querySelector('[data-tab="talent"]')
    .addEventListener("click", loadTalents);
})();
