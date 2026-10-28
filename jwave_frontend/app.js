const stepNames = { analyze: "需求分析", retrieve: "知识检索", template: "模板转换", extract: "参数提取", param_check: "参数预检", generate: "代码生成", static_check: "静态检查", run_code: "执行仿真", semantic_gate: "语义校验", completion_review: "需求完成度评审", fix_code: "代码纠错", finalize: "输出" };
const stepOrder = ["analyze", "retrieve", "template", "extract", "param_check", "generate", "static_check", "run_code", "semantic_gate", "completion_review", "fix_code", "finalize"];
const $ = id => document.getElementById(id);
let latest = {};
let sessionId = localStorage.getItem("jwave.sessionId") || "";
let turnCount = 0;

async function ensureSession() {
  if (sessionId) {
    const response = await fetch(`/api/sessions/${encodeURIComponent(sessionId)}`);
    if (response.ok) {
      const data = await response.json();
      turnCount = (data.session?.turns || []).length;
      renderSession(data.session);
      return;
    }
  }
  const response = await fetch("/api/sessions", {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify({collect_memory: false})});
  const data = await response.json();
  sessionId = data.session.id; turnCount = 0;
  localStorage.setItem("jwave.sessionId", sessionId);
  renderSession(data.session);
}
function renderSession(session) {
  if (!session) return;
  $("sessionTitle").textContent = session.title || "当前仿真会话";
  $("turnHint").textContent = `${(session.turns || []).length} 轮 · 可继续修改`;
}

function renderSteps(active) {
  $("steps").innerHTML = stepOrder.map(key => {
    const completed = latest.completed?.includes(key);
    const status = completed ? "done" : key === active ? "active" : "";
    return `<div class="step ${status}"><strong>${status === "done" ? "✓ " : status === "active" ? "● " : ""}${stepNames[key]}</strong><span>${status === "active" ? "智能体处理中…" : status === "done" ? "已完成" : "等待中"}</span></div>`;
  }).join("");
}
function addActivity(text) {
  const box = $("activity"); box.classList.remove("empty");
  const line = document.createElement("div"); line.textContent = `${new Date().toLocaleTimeString()}  ${text}`;
  box.appendChild(line); box.scrollTop = box.scrollHeight;
}
function renderGates(state) {
  const hasResult = ["param_check_ok", "static_issues", "semantic_verified", "verified", "requirement_completed"]
    .some(key => Object.prototype.hasOwnProperty.call(state, key));
  const gates = [
    ["参数物理预检", state.param_check_ok, state.param_issues?.length || 0],
    ["AST 静态检查", !state.static_issues?.length, state.static_issues?.length || 0],
    ["语义数值门", state.semantic_verified ?? state.verified, state.semantic_issues?.length || 0],
    ["需求完成度评审", state.requirement_completed, state.completion_feedback ? 1 : 0],
  ];
  $("gates").innerHTML = gates.map(([name, ok, count]) => {
    if (!hasResult) return `<div class="gate placeholder">${name}<b>等待任务</b></div>`;
    return `<div class="gate ${ok ? "pass" : "fail"}">${name}<b>${ok ? "通过 ✓" : `${count} 项问题`}</b></div>`;
  }).join("");
  const check = state.selfcheck || {};
  $("metrics").innerHTML = Object.keys(check).length ? Object.entries(check).map(([key, val]) => `<div class="metric"><small>${key}</small><b>${typeof val === "object" ? JSON.stringify(val) : val}</b></div>`).join("") : '<div class="empty">暂无自检数据。</div>';
}
function renderResult(state, showCode = false) {
  latest = {...latest, ...state};
  const ok = Boolean(state.verified);
  $("resultStatus").className = `status ${ok ? "pass" : "fail"}`;
  $("resultStatus").textContent = ok ? "验证通过 ✓" : "需要人工确认";
  renderGates(state);
  if (showCode && (state.text || state.code_final || state.code)) {
    $("code").textContent = state.text || state.code_final || state.code;
  }
  if (state.elapsed) $("elapsed").textContent = `${Number(state.elapsed).toFixed(1)}s`;
}
function saveCode() {
  const code = $("code").textContent;
  if (!code || code === "运行工作流后，生成的 jwave 代码会显示在这里。" || code === "工作流完成输出后，生成的 jwave 代码会显示在这里。" || code === "没有生成代码。") {
    addActivity("暂无可保存的生成代码");
    return;
  }
  let filename = $("filename").value.trim() || "jwave_simulation.py";
  filename = filename.replace(/[\\/:*?"<>|]/g, "_");
  if (!filename.toLowerCase().endsWith(".py")) filename += ".py";
  const blob = new Blob([code], {type: "text/x-python;charset=utf-8"});
  const link = document.createElement("a");
  link.href = URL.createObjectURL(blob);
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(link.href);
  addActivity(`已另存为 ${filename}`);
}
async function run() {
  const query = $("query").value.trim(); if (!query) { $("query").focus(); return; }
  $("runBtn").disabled = true; $("runBtn").querySelector("span").textContent = "运行中…";
  latest = {completed: []}; $("activity").innerHTML = ""; $("activity").classList.add("empty"); $("elapsed").textContent = "准备中…"; renderSteps();
  $("code").textContent = "工作流完成输出后，生成的 jwave 代码会显示在这里。";
  $("resultStatus").className = "status neutral"; $("resultStatus").textContent = "运行中";
  try {
    const response = await fetch(`/api/sessions/${encodeURIComponent(sessionId)}/run`, {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify({query, collect_memory: $("collectMemory").checked})});
    if (!response.ok || !response.body) throw new Error("无法连接到工作流服务");
    const reader = response.body.getReader(); const decoder = new TextDecoder(); let buffer = "";
    while (true) {
      const {value, done} = await reader.read(); if (done) break;
      buffer += decoder.decode(value, {stream: true});
      const lines = buffer.split("\n"); buffer = lines.pop();
      for (const line of lines) { if (!line.trim()) continue; handleEvent(JSON.parse(line)); }
    }
  } catch (error) { addActivity(`错误：${error.message}`); $("resultStatus").className = "status fail"; $("resultStatus").textContent = "运行失败"; }
  finally { $("runBtn").disabled = false; $("runBtn").querySelector("span").textContent = "运行工作流"; loadHistory(); }
}
function handleEvent(event) {
  if (event.type === "node") {
    const state = event.state || {}; latest = {...latest, ...state};
    if (!latest.completed) latest.completed = [];
    if (latest.activeNode && latest.activeNode !== event.node) {
      latest.completed = [...new Set([...latest.completed, latest.activeNode])];
    }
    latest.activeNode = event.node || "";
    renderSteps(event.node); (state.trace || []).slice(-1).forEach(addActivity);
    renderResult(latest, event.node === "finalize"); return;
  }
  if (event.type === "complete") {
    latest = {...latest, ...(event.state || {})};
    latest.activeNode = "";
    latest.completed = [...new Set([...latest.completed, "finalize"])];
    renderResult(latest, true); renderSteps(); addActivity("工作流完成"); return;
  }
  if (event.type === "session") {
    turnCount = (event.session?.turns || []).length;
    renderSession(event.session);
    return;
  }
  if (event.type === "memory") {
    addActivity("已生成脱敏项目经验卡片");
    latest.memory = event.memory;
    return;
  }
  if (event.type === "error") addActivity(`错误：${event.error}`);
}
async function loadHistory() {
  try {
    const data = await fetch("/api/history").then(r => r.json());
    $("history").innerHTML = (data.records || []).map((item, i) => `<div class="history-item" data-index="${i}"><strong>${item.verified && item.success ? "✓ " : "⚠ "}${item.title || item.query || "未命名任务"}</strong><small>${item.time || ""} · ${item.elapsed || 0}s · ${item.iterations || 0} 轮</small></div>`).join("") || '<div class="empty">还没有历史任务。</div>';
    $("history").querySelectorAll(".history-item").forEach(item => item.addEventListener("click", () => selectHistory(data.records[Number(item.dataset.index)])));
  } catch { $("history").innerHTML = '<div class="empty">历史记录暂不可用。</div>'; }
}
async function selectHistory(record) {
  renderResult(record, true);
  if (!record.session_id) {
    addActivity("该历史任务没有会话信息，只能查看结果；新任务可继续使用当前会话。");
    return;
  }
  try {
    const response = await fetch(`/api/sessions/${encodeURIComponent(record.session_id)}`);
    if (!response.ok) throw new Error("会话不存在");
    const data = await response.json();
    sessionId = data.session.id;
    turnCount = (data.session.turns || []).length;
    localStorage.setItem("jwave.sessionId", sessionId);
    renderSession(data.session);
    addActivity(`已载入会话，可继续追问（第 ${turnCount} 轮）`);
  } catch (error) {
    addActivity(`无法载入会话：${error.message}`);
  }
}
async function loadConfig() {
  try { const data = await fetch("/api/config").then(r => r.json()); const s = data.settings; $("runtimeBadge").textContent = s.api_key_configured ? `● ${s.executor_backend} · ${s.analyst_model}` : "● 待配置 API Key"; $("runtimeBadge").classList.add(s.api_key_configured ? "ok" : "error"); }
  catch { $("runtimeBadge").textContent = "● 服务不可用"; $("runtimeBadge").classList.add("error"); }
}
$("runBtn").addEventListener("click", run); $("refreshHistory").addEventListener("click", loadHistory);
$("newSession").addEventListener("click", async () => {
  const response = await fetch("/api/sessions", {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify({})});
  const data = await response.json();
  sessionId = data.session.id; turnCount = 0; localStorage.setItem("jwave.sessionId", sessionId);
  latest = {}; $("query").value = ""; $("code").textContent = "工作流完成输出后，生成的 jwave 代码会显示在这里。"; renderSession(data.session); addActivity("已新建会话");
});
$("copyCode").addEventListener("click", () => navigator.clipboard?.writeText($("code").textContent));
$("saveCode").addEventListener("click", saveCode);
document.querySelectorAll(".chip").forEach(button => button.addEventListener("click", () => { $("query").value = button.dataset.query; $("query").focus(); }));
loadConfig(); loadHistory(); renderGates({}); renderSteps(); ensureSession().catch(error => addActivity(`会话初始化失败：${error.message}`));
