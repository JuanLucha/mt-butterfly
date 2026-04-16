// ── Tasks page ───────────────────────────────────────────────────────────────
// Requires api.js to be loaded first (provides TOKEN, apiFetch, escHtml, renderMarkdown).
document.getElementById("nav-tasks").classList.add("active");

const DAYS = ["mon","tue","wed","thu","fri","sat","sun"];
let tasksCache = [];

async function loadTasks() {
  let res, tasks;
  try {
    res = await apiFetch("/api/tasks");
    tasks = await res.json();
  } catch (e) {
    document.getElementById("tasks-body").innerHTML =
      `<tr><td colspan="6" style="color:var(--danger);text-align:center;padding:2rem">Failed to load tasks: ${e.message}</td></tr>`;
    return;
  }
  tasksCache = tasks;
  const tbody = document.getElementById("tasks-body");
  if (!tasks.length) {
    tbody.innerHTML = '<tr><td colspan="6" style="color:var(--text-muted);text-align:center;padding:2rem">No tasks yet</td></tr>';
    return;
  }
  tbody.innerHTML = tasks.map(t => {
    const days = t.days_of_week || "mon-fri";
    const schedule = `${String(t.hour).padStart(2,"0")}:${String(t.minute).padStart(2,"0")} · ${days}`;
    const lastRun  = t.last_run ? new Date(t.last_run.started_at).toLocaleString() : "—";
    const status   = t.last_run ? badgeHtml(t.last_run.status) : '<span class="badge badge-none">—</span>';
    const enabled  = t.enabled ? '' : ' <span style="color:var(--text-muted);font-size:.75rem">(disabled)</span>';
    return `<tr>
      <td style="cursor:pointer;color:var(--primary)" onclick="viewTaskRuns('${t.id}', '${escHtml(t.name)}')">${escHtml(t.name)}${enabled}</td>
      <td style="font-family:monospace;font-size:.8rem">${escHtml(schedule)}</td>
      <td style="font-size:.8rem;color:var(--text-muted)">${escHtml(t.email_to || "—")}</td>
      <td style="font-size:.8rem;color:var(--text-muted)">${lastRun}</td>
      <td>${status}</td>
      <td>
        <div class="task-actions">
          <button class="btn-sm btn-sm-primary" onclick="runTask('${t.id}')">▶ Run</button>
          <button class="btn-sm btn-sm-ghost" onclick="editTask('${t.id}')">Edit</button>
          <button class="btn-sm btn-sm-danger"  onclick="deleteTask('${t.id}')">Delete</button>
        </div>
      </td>
    </tr>`;
  }).join("");
}

function badgeHtml(status) {
  const map = { success: "badge-success", error: "badge-error", running: "badge-running" };
  return `<span class="badge ${map[status] || 'badge-none'}">${status}</span>`;
}

window.openTaskModal = () => {
  document.getElementById("task-id").value = "";
  document.getElementById("task-modal-title").textContent = "New task";
  document.getElementById("task-name").value = "";
  document.getElementById("task-prompt").value = "";
  document.getElementById("task-hour").value = 9;
  document.getElementById("task-minute").value = 0;
  document.getElementById("task-email").value = "";
  document.getElementById("task-enabled").checked = true;
  updateWorkingDirDisplay("");
  document.querySelectorAll(".day-cb").forEach(cb => {
    cb.checked = ["mon","tue","wed","thu","fri"].includes(cb.value);
  });
  document.getElementById("task-modal").classList.add("open");
};

function updateWorkingDirDisplay(name) {
  const display = document.getElementById("task-working-dir-display");
  if (!name) {
    display.textContent = "Will be: WORKSPACES_DIR/task-name";
    return;
  }
  const slug = name.toLowerCase().replace(/[^\w-]+/g, "-").replace(/^-+|-+$/g, "") || "task";
  display.textContent = `Will be: WORKSPACES_DIR/${slug}`;
}

document.getElementById("task-name").addEventListener("input", (e) => {
  if (document.getElementById("task-id").value) return;
  updateWorkingDirDisplay(e.target.value);
});

window.closeTaskModal = () => document.getElementById("task-modal").classList.remove("open");

window.editTask = (taskId) => {
  const t = tasksCache.find(x => x.id === taskId);
  if (!t) return;
  document.getElementById("task-id").value = t.id;
  document.getElementById("task-modal-title").textContent = "Edit task";
  document.getElementById("task-name").value = t.name;
  document.getElementById("task-prompt").value = t.prompt;
  document.getElementById("task-hour").value = t.hour;
  document.getElementById("task-minute").value = t.minute;
  document.getElementById("task-email").value = t.email_to || "";
  document.getElementById("task-enabled").checked = t.enabled;
  document.getElementById("task-working-dir").value = t.working_dir || "";
  const activeDays = (t.days_of_week || "").split(",");
  document.querySelectorAll(".day-cb").forEach(cb => cb.checked = activeDays.includes(cb.value));
  document.getElementById("task-modal").classList.add("open");
};

window.saveTask = async () => {
  const id = document.getElementById("task-id").value;
  const days = [...document.querySelectorAll(".day-cb:checked")].map(cb => cb.value).join(",");
  const body = {
    name:         document.getElementById("task-name").value.trim(),
    prompt:       document.getElementById("task-prompt").value.trim(),
    hour:         parseInt(document.getElementById("task-hour").value),
    minute:       parseInt(document.getElementById("task-minute").value),
    days_of_week: days || "mon",
    email_to:     document.getElementById("task-email").value.trim() || null,
    enabled:      document.getElementById("task-enabled").checked,
    working_dir:  document.getElementById("task-working-dir").value.trim() || null,
  };
  if (!body.name || !body.prompt) { alert("Name and prompt are required."); return; }
  const method = id ? "PUT" : "POST";
  const path   = id ? `/api/tasks/${id}` : "/api/tasks";
  try {
    await apiFetch(path, { method, headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
    closeTaskModal();
    loadTasks();
  } catch (e) {
    alert("Error saving task: " + e.message);
  }
};

window.deleteTask = async (id) => {
  if (!confirm("Delete this task?")) return;
  try {
    await apiFetch(`/api/tasks/${id}`, { method: "DELETE" });
    loadTasks();
  } catch (e) {
    alert("Error deleting task: " + e.message);
  }
};

let _pollInterval = null;
let _activeRunId = null;

async function refreshActiveRun() {
  if (!_activeRunId) return;
  try {
    const res = await apiFetch(`/api/tasks/runs/${_activeRunId}`);
    const run = await res.json();
    const outputEl = document.getElementById("run-output");
    if (outputEl && document.getElementById("run-output-container").style.display !== "none") {
      const scrolledToBottom = outputEl.scrollHeight - outputEl.scrollTop <= outputEl.clientHeight + 40;
      outputEl.innerHTML = renderSession(run.output);
      if (scrolledToBottom) outputEl.scrollTop = outputEl.scrollHeight;
    }
  } catch {}
}

function startPolling() {
  if (_pollInterval) return;
  _pollInterval = setInterval(async () => {
    await loadTasks();
    await refreshActiveRun();
    const hasRunning = tasksCache.some(t => t.last_run?.status === "running");
    if (!hasRunning) {
      clearInterval(_pollInterval);
      _pollInterval = null;
    }
  }, 3000);
}

window.runTask = async (id) => {
  try {
    await apiFetch(`/api/tasks/${id}/run`, { method: "POST" });
    await loadTasks();
    startPolling();
  } catch (e) {
    alert("Error triggering task: " + e.message);
  }
};

window.viewTaskRuns = async (taskId, taskName) => {
  document.getElementById("runs-task-id").value = taskId;
  document.getElementById("runs-modal-title").textContent = `Runs — ${taskName}`;
  document.getElementById("run-output-container").style.display = "none";

  try {
    const res = await apiFetch(`/api/tasks/${taskId}/runs`);
    const runs = await res.json();

    const listEl = document.getElementById("runs-list");
    if (!runs.length) {
      listEl.innerHTML = '<div style="padding:1rem;color:var(--text-muted)">No runs yet</div>';
      return;
    }

    listEl.innerHTML = runs.map(r => {
      const started = r.started_at ? new Date(r.started_at).toLocaleString() : "—";
      const completed = r.completed_at ? new Date(r.completed_at).toLocaleString() : "—";
      const status = badgeHtml(r.status);
      return `<div class="run-item" style="display:flex;align-items:center;gap:1rem;padding:.5rem 1rem;border-bottom:1px solid var(--border);cursor:pointer" onclick="viewRunOutput('${r.id}')">
        <span style="flex:1;font-size:.85rem">${started}</span>
        <span style="flex:1;font-size:.85rem">${completed}</span>
        <span>${status}</span>
      </div>`;
    }).join("");
  } catch (e) {
    document.getElementById("runs-list").innerHTML = `<div style="padding:1rem;color:var(--danger)">Error: ${e.message}</div>`;
  }

  document.getElementById("runs-modal").classList.add("open");
};

function renderSession(jsonl) {
  if (!jsonl || !jsonl.trim()) return '<div style="color:var(--text-muted);font-style:italic">No output</div>';

  const lines = jsonl.trim().split("\n");
  const blocks = [];

  for (const line of lines) {
    let event;
    try { event = JSON.parse(line); } catch { continue; }

    const type = event.type;
    const part = event.part || {};

    if (type === "text") {
      const text = part.text || "";
      if (!text.trim()) continue;
      blocks.push(`<div style="background:var(--bg);border-radius:4px;padding:.5rem .75rem">${renderMarkdown(text)}</div>`);

    } else if (type === "message") {
      const role = part.role || "assistant";
      const content = part.content || "";
      const text = Array.isArray(content)
        ? content.filter(c => c.type === "text").map(c => c.text || "").join("")
        : content;
      if (!text.trim()) continue;
      const label = role === "user" ? "User" : "Assistant";
      const color = role === "user" ? "var(--primary)" : "var(--text-muted)";
      blocks.push(`<div style="border-left:3px solid ${color};padding:.4rem .75rem">
        <div style="font-size:.7rem;color:${color};margin-bottom:.2rem;font-weight:600">${label}</div>
        <div>${renderMarkdown(text)}</div>
      </div>`);

    } else if (type === "tool_use") {
      const toolName = part.tool || part.name || part.tool_name || "tool";
      const state = part.state || {};
      const input = state.input || part.input || {};
      const inputStr = typeof input === "string" ? input : JSON.stringify(input, null, 2);
      const out = state.output || "";
      const err = state.error || "";
      const hasResult = out || err;
      const resultStr = err
        ? `ERROR: ${typeof err === "string" ? err : JSON.stringify(err)}`
        : (typeof out === "string" ? out : JSON.stringify(out, null, 2));
      const borderColor = err ? "var(--danger)" : "var(--border)";
      blocks.push(`<details style="border:1px solid ${borderColor};border-radius:4px;padding:.3rem .6rem">
        <summary style="cursor:pointer;font-size:.75rem;color:var(--text-muted)">⚙ ${escHtml(toolName)}</summary>
        <pre style="margin:.4rem 0 0;font-size:.75rem;overflow-x:auto;color:var(--text-muted)">${escHtml(inputStr)}</pre>
        ${hasResult ? `<pre style="margin:.4rem 0 0;font-size:.75rem;overflow-x:auto;border-top:1px solid var(--border);padding-top:.4rem">${escHtml(resultStr)}</pre>` : ""}
      </details>`);

    } else if (type === "tool_result") {
      const state = part.state || {};
      const out = state.output || part.output || part.content || "";
      const err = state.error || part.error || "";
      const content = err ? `ERROR: ${err}` : (typeof out === "string" ? out : JSON.stringify(out, null, 2));
      if (!content.trim()) continue;
      const color = err ? "var(--danger)" : "var(--border)";
      blocks.push(`<details style="border:1px solid ${color};border-radius:4px;padding:.3rem .6rem">
        <summary style="cursor:pointer;font-size:.75rem;color:var(--text-muted)">↩ result</summary>
        <pre style="margin:.4rem 0 0;font-size:.75rem;overflow-x:auto">${escHtml(content)}</pre>
      </details>`);
    }
  }

  return blocks.length
    ? blocks.join("")
    : '<div style="color:var(--text-muted);font-style:italic">No displayable content</div>';
}

window.viewRunOutput = async (runId) => {
  try {
    const res = await apiFetch(`/api/tasks/runs/${runId}`);
    const run = await res.json();
    const outputEl = document.getElementById("run-output");
    outputEl.innerHTML = renderSession(run.output);
    document.getElementById("run-output-container").style.display = "block";
    outputEl.scrollTop = outputEl.scrollHeight;
    _activeRunId = run.status === "running" ? runId : null;
    if (_activeRunId) startPolling();
  } catch (e) {
    alert("Error loading output: " + e.message);
  }
};

window.closeRunsModal = () => {
  document.getElementById("runs-modal").classList.remove("open");
  _activeRunId = null;
};

document.getElementById("task-modal").addEventListener("click", e => {
  if (e.target === document.getElementById("task-modal")) closeTaskModal();
});
document.getElementById("runs-modal").addEventListener("click", e => {
  if (e.target === document.getElementById("runs-modal")) closeRunsModal();
});
document.addEventListener("keydown", e => { if (e.key === "Escape") { closeTaskModal(); closeRunsModal(); } });

window.exportTasks = async () => {
  try {
    const res = await apiFetch("/api/tasks/export");
    const blob = await res.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = "mt-butterfly-tasks.json";
    a.click();
    URL.revokeObjectURL(url);
  } catch (e) {
    alert("Export failed: " + e.message);
  }
};

window.importTasks = async (input) => {
  const file = input.files[0];
  if (!file) return;
  input.value = "";
  let parsed;
  try {
    parsed = JSON.parse(await file.text());
  } catch {
    alert("Invalid JSON file.");
    return;
  }
  const tasks = parsed.tasks || (Array.isArray(parsed) ? parsed : null);
  if (!tasks) { alert("No tasks found in file."); return; }
  if (!confirm(`Import ${tasks.length} task(s) and add them to existing tasks?`)) return;
  try {
    const res = await apiFetch("/api/tasks/import", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ tasks, replace: false }),
    });
    const result = await res.json();
    alert(`Imported ${result.imported} task(s).`);
    loadTasks();
  } catch (e) {
    alert("Import failed: " + e.message);
  }
};

loadTasks();
