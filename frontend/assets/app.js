const state = {
  tasks: [],
  selectedTaskId: null,
  selectedRecord: null,
  artifacts: null,
  trace: [],
};

const $ = (selector) => document.querySelector(selector);
const $$ = (selector) => [...document.querySelectorAll(selector)];

function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>"']/g, (char) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#039;",
  }[char]));
}

function showToast(message) {
  const toast = $("#toast");
  toast.textContent = message;
  toast.classList.add("visible");
  clearTimeout(showToast.timer);
  showToast.timer = setTimeout(() => toast.classList.remove("visible"), 2800);
}

async function api(path, options = {}) {
  const response = await fetch(path, {
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
    ...options,
  });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    const error = payload.error || {};
    throw new Error(error.message || `Request failed: ${response.status}`);
  }
  return payload;
}

function statusBadge(status) {
  return `<span class="status-badge status-${escapeHtml(status)}">${escapeHtml(status)}</span>`;
}

function formatTime(value) {
  if (!value) return "--";
  return new Intl.DateTimeFormat(undefined, { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" }).format(new Date(value));
}

function renderMetrics() {
  const open = state.tasks.filter((task) => ["queued", "running"].includes(task.status)).length;
  const succeeded = state.tasks.filter((task) => task.status === "succeeded").length;
  const failed = state.tasks.filter((task) => task.status === "failed").length;
  $("#openCount").textContent = open;
  $("#successCount").textContent = succeeded;
  $("#failedCount").textContent = failed;
  $("#taskCountLabel").textContent = `${state.tasks.length} task${state.tasks.length === 1 ? "" : "s"}`;
  $("#lastUpdate").textContent = state.tasks[0] ? formatTime(state.tasks[0].updated_at) : "--";
}

function renderTasks() {
  renderMetrics();
  const rows = $("#taskRows");
  const empty = $("#taskEmpty");
  rows.innerHTML = state.tasks.map((task) => `
    <tr data-task-id="${escapeHtml(task.task_id)}">
      <td><strong>${escapeHtml(task.task_id)}</strong><div class="approval">${escapeHtml(task.error_message || "Repair request")}</div></td>
      <td>${statusBadge(task.status)}</td>
      <td><span class="approval ${escapeHtml(task.approval_status)}">${escapeHtml(task.approval_status)}</span></td>
      <td>${escapeHtml(formatTime(task.updated_at))}</td>
      <td><button class="icon-button row-open" data-task-id="${escapeHtml(task.task_id)}" type="button" aria-label="Open task"><i data-lucide="arrow-up-right"></i></button></td>
    </tr>
  `).join("");
  empty.style.display = state.tasks.length ? "none" : "flex";
  $$(".row-open").forEach((button) => button.addEventListener("click", (event) => {
    event.stopPropagation();
    selectTask(button.dataset.taskId);
  }));
  $$("#taskRows tr").forEach((row) => row.addEventListener("click", () => selectTask(row.dataset.taskId)));
  if (window.lucide) window.lucide.createIcons();
}

function renderDetail() {
  const record = state.selectedRecord;
  const artifacts = state.artifacts || {};
  const report = artifacts.report || {};
  if (!record) {
    $("#detailSummary").textContent = "Choose a task from the queue to inspect its report.";
    ["overviewContent", "traceContent", "diffContent", "testsContent"].forEach((id) => { $(`#${id}`).innerHTML = ""; });
    return;
  }
  $("#detailTitle").textContent = record.task_id;
  $("#detailSummary").innerHTML = `
    <strong>${escapeHtml(record.status)}</strong> · ${escapeHtml(report.summary || record.error_message || "No report yet")}
    <div class="detail-kpis">
      <div class="detail-kpi"><span>Approval</span><strong>${escapeHtml(record.approval_status)}</strong></div>
      <div class="detail-kpi"><span>Execution</span><strong>${escapeHtml(report.execution_mode || "pending")}</strong></div>
      <div class="detail-kpi"><span>Updated</span><strong>${escapeHtml(formatTime(record.updated_at))}</strong></div>
    </div>
  `;
  const evidence = (report.evidence || []).map((item) => `
    <div class="detail-kpi"><span>${escapeHtml(item.source_type || "evidence")}</span><strong>${escapeHtml(item.file_path || item.evidence_id)}</strong></div>
  `).join("");
  $("#overviewContent").innerHTML = `
    <div class="detail-kpis">
      <div class="detail-kpi"><span>Root cause</span><strong>${escapeHtml(report.root_cause || "not available")}</strong></div>
      <div class="detail-kpi"><span>Modified files</span><strong>${escapeHtml((report.modified_files || []).join(", ") || "none")}</strong></div>
      <div class="detail-kpi"><span>Failure node</span><strong>${escapeHtml(report.failure_node || "none")}</strong></div>
    </div>
    ${evidence ? `<div class="detail-kpis">${evidence}</div>` : ""}
    <pre class="code-block">${escapeHtml(report.summary || "No report content.")}</pre>
  `;
  $("#traceContent").innerHTML = (state.trace || []).length ? `<div class="trace-list">${state.trace.map((event) => `
    <div class="trace-row"><span>${escapeHtml(event.timestamp ? formatTime(event.timestamp) : "--")}</span><span class="trace-status trace-${escapeHtml(event.status)}">${escapeHtml(event.status)}</span><span>${escapeHtml(event.action)}</span><span class="trace-message">${escapeHtml(event.message || "")}</span></div>
  `).join("")}</div>` : `<div class="empty-state" style="display:flex"><i data-lucide="route"></i><div>No trace yet</div></div>`;
  $("#diffContent").innerHTML = `<pre class="code-block">${escapeHtml(artifacts.patch_diff || "No patch generated.")}</pre>`;
  const baseline = artifacts.baseline_test_report;
  const post = artifacts.post_patch_test_report;
  $("#testsContent").innerHTML = `
    <div class="test-grid">
      <div class="test-card"><h3>Baseline test · ${escapeHtml(baseline?.status || "not run")}</h3><pre>${escapeHtml(JSON.stringify(baseline || {}, null, 2))}</pre></div>
      <div class="test-card"><h3>Post-patch test · ${escapeHtml(post?.status || "not run")}</h3><pre>${escapeHtml(JSON.stringify(post || {}, null, 2))}</pre></div>
    </div>
  `;
  if (window.lucide) window.lucide.createIcons();
}

async function loadTasks() {
  try {
    state.tasks = await api("/api/v1/tasks");
    $("#connectionState").innerHTML = `<span class="status-dot live"></span> API linked`;
    renderTasks();
    if (state.selectedTaskId) await selectTask(state.selectedTaskId, { quiet: true });
  } catch (error) {
    $("#connectionState").innerHTML = `<span class="status-dot"></span> API unavailable`;
    showToast(error.message);
  }
}

async function selectTask(taskId, { quiet = false } = {}) {
  state.selectedTaskId = taskId;
  try {
    const [record, trace, artifacts] = await Promise.all([
      api(`/api/v1/tasks/${encodeURIComponent(taskId)}`),
      api(`/api/v1/tasks/${encodeURIComponent(taskId)}/trace`),
      api(`/api/v1/tasks/${encodeURIComponent(taskId)}/artifacts`),
    ]);
    state.selectedRecord = record;
    state.trace = trace.trace || [];
    state.artifacts = artifacts;
    renderDetail();
  } catch (error) {
    if (!quiet) showToast(error.message);
  }
}

async function submitTask(event) {
  event.preventDefault();
  let testCommand;
  try {
    testCommand = JSON.parse($("#testCommand").value.trim());
    if (!Array.isArray(testCommand) || !testCommand.length || !testCommand.every((item) => typeof item === "string" && item.trim())) throw new Error();
  } catch {
    showToast("Test command must be a non-empty JSON array of strings.");
    return;
  }
  const task = {
    task_id: $("#taskId").value.trim(),
    repo_path: $("#repoPath").value.trim(),
    issue: $("#issue").value.trim(),
    stack_trace: $("#stackTrace").value.trim() || null,
    test_command: testCommand,
  };
  try {
    const result = await api("/api/v1/tasks", { method: "POST", body: JSON.stringify(task) });
    showToast(`Submitted ${result.task_id}`);
    $("#submitPanel").hidden = true;
    await loadTasks();
    await selectTask(result.task_id);
  } catch (error) {
    showToast(error.message);
  }
}

async function approveSelected() {
  if (!state.selectedTaskId) return showToast("Select a task first.");
  try {
    await api(`/api/v1/tasks/${encodeURIComponent(state.selectedTaskId)}/approve`, {
      method: "POST",
      body: JSON.stringify({ approved: true, actor: "operator", reason: "reviewed in control room" }),
    });
    showToast("Approval recorded.");
    await loadTasks();
    await selectTask(state.selectedTaskId);
  } catch (error) {
    showToast(error.message);
  }
}

async function cancelSelected() {
  if (!state.selectedTaskId) return showToast("Select a task first.");
  try {
    await api(`/api/v1/tasks/${encodeURIComponent(state.selectedTaskId)}/cancel`, {
      method: "POST",
      body: JSON.stringify({ reason: "cancelled from control room" }),
    });
    showToast("Cancellation recorded.");
    await loadTasks();
    await selectTask(state.selectedTaskId);
  } catch (error) {
    showToast(error.message);
  }
}

function showPage(page) {
  $$(".page").forEach((element) => element.classList.toggle("active", element.id === `${page}Page`));
  $$(".nav-item").forEach((element) => element.classList.toggle("active", element.dataset.page === page));
}

function bindEvents() {
  $$(".nav-item").forEach((button) => button.addEventListener("click", () => showPage(button.dataset.page)));
  $("#refreshButton").addEventListener("click", loadTasks);
  $("#newTaskButton").addEventListener("click", () => { $("#submitPanel").hidden = false; $("#taskId").focus(); });
  $("#openFormButton").addEventListener("click", () => { $("#submitPanel").hidden = false; $("#taskId").focus(); });
  $("#closeFormButton").addEventListener("click", () => { $("#submitPanel").hidden = true; });
  $("#taskForm").addEventListener("submit", submitTask);
  $("#approveButton").addEventListener("click", approveSelected);
  $("#cancelButton").addEventListener("click", cancelSelected);
  $$(".tab").forEach((button) => button.addEventListener("click", () => {
    $$(".tab").forEach((tab) => tab.classList.toggle("active", tab === button));
    $$(".tab-content").forEach((content) => content.classList.toggle("active", content.dataset.tabContent === button.dataset.tab));
  }));
  setInterval(loadTasks, 5000);
}

async function boot() {
  bindEvents();
  if (window.lucide) window.lucide.createIcons();
  await loadTasks();
}

boot();
