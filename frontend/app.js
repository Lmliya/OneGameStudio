// 前端最小交互：启动时检查后端状态，提交需求时创建一个任务。
// 阶段 4 后会改为展示四个员工的工作流进度。

const statusEl = document.getElementById("status");
const inputEl = document.getElementById("requirement");
const submitEl = document.getElementById("submit");
const resultEl = document.getElementById("result");

function setStatus(text, cls) {
  statusEl.textContent = text;
  statusEl.className = `badge ${cls}`;
}

async function checkHealth() {
  try {
    const response = await fetch("/api/health");
    const data = await response.json();
    if (data.status === "ok") {
      setStatus(data.mock_mode ? "Mock 模式" : "真实模式", "badge-ok");
    } else {
      setStatus("服务异常", "badge-warn");
    }
  } catch (error) {
    setStatus("后端未连接", "badge-warn");
  }
}

async function submitRequirement() {
  const requirement = inputEl.value.trim();
  if (!requirement) {
    resultEl.textContent = "请先填写需求。";
    return;
  }

  submitEl.disabled = true;
  resultEl.textContent = "提交中…";
  try {
    const response = await fetch("/api/tasks", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ requirement }),
    });
    if (!response.ok) {
      throw new Error(`HTTP ${response.status}`);
    }
    const data = await response.json();
    resultEl.textContent =
      `任务已创建\n` +
      `task_id : ${data.task_id}\n` +
      `状态    : ${data.status}\n` +
      `阶段    : ${data.stage}\n\n` +
      `（阶段 0 仅创建任务目录，尚未启动 AI 员工）`;
  } catch (error) {
    resultEl.textContent = `提交失败：${error.message}`;
  } finally {
    submitEl.disabled = false;
  }
}

submitEl.addEventListener("click", submitRequirement);
checkHealth();
