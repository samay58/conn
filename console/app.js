/* Conn console: a dumb renderer over the daemon's WebSocket. It holds no
   secrets and makes no decisions; it displays state and forwards intents. */

const $ = (id) => document.getElementById(id);
const pill = $("ptt"), pillState = $("ptt-state"), pillSub = $("ptt-sub");
const transcript = $("transcript"), chipsEl = $("chips");
const traceList = $("trace-list"), traceCount = $("trace-count");
const costLine = $("cost-line"), receiptEl = $("receipt");

const PHASE_LABEL = {
  idle: ["Idle", "hold to talk"],
  listening: ["Listening", "release to send"],
  thinking: ["Thinking", "model is working"],
  acting: ["Acting", "running a tool"],
  awaiting_approval: ["Approve?", "action needs your ok"],
  speaking: ["Speaking", "tap space to interrupt"],
  done: ["Done", "hold to talk"],
  failed: ["Reconnecting", "connection dropped"],
  budget_hold: ["Budget hold", "cap reached"],
};

let ws = null;
let traceEvents = 0;
let modelLine = null;
let holding = false;
let receiptSeen = false;

function connect() {
  ws = new WebSocket(`ws://${location.host}/ws`);
  ws.onmessage = (e) => handle(JSON.parse(e.data));
  ws.onclose = () => {
    $("conn-dot").className = "dot failed";
    setTimeout(connect, 800);
  };
}

function send(msg) {
  if (ws && ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify(msg));
}

function sendTimed(msg) {
  send({ ...msg, client_ts_ms: Math.round(performance.now()) });
}

function sendUiAck(moment) {
  requestAnimationFrame(() => {
    send({ type: "ui_ack", moment, client_ts_ms: Math.round(performance.now()) });
  });
}

function handle(msg) {
  switch (msg.type) {
    case "hello":
      $("mode-label").textContent = msg.live ? "live" : "demo";
      break;
    case "state":
      renderState(msg);
      break;
    case "user_transcript":
      addUserLine(msg.text);
      break;
    case "transcript_delta":
      streamModel(msg.text);
      break;
    case "cost":
      renderCost(msg.receipt);
      break;
    case "receipt":
      renderCost(msg.receipt);
      addTrace({ kind: "session_end", ts: Date.now() / 1000 });
      break;
    case "trace":
      addTrace(msg.event);
      break;
    case "toast":
      toast(msg.text, msg.level);
      break;
  }
}

/* ---------- state + chips ---------- */

let lastAckedPhase = null;
let chipAcked = false;
function renderState(s) {
  const [label, sub] = PHASE_LABEL[s.phase] || [s.phase, ""];
  pill.dataset.phase = s.phase;
  pillState.textContent = label;
  pillSub.textContent = sub;
  $("conn-dot").className = "dot" + (s.connected ? " connected" : "");

  chipsEl.replaceChildren();
  let hasProposedChip = false;
  for (const entry of s.ledger || []) {
    chipsEl.appendChild(entry.status === "proposed" ? liveChip(entry) : ranChip(entry));
    if (entry.status === "proposed") hasProposedChip = true;
  }

  if (s.phase === "budget_hold") offerOverride();
  if (s.phase === "done" || s.phase === "idle") finishModelLine();
  if (typeof s.spent_usd === "number" && !receiptSeen) {
    costLine.textContent = `$${s.spent_usd.toFixed(4)}`;
  }

  if ((s.phase === "listening" || s.phase === "thinking") && s.phase !== lastAckedPhase) {
    lastAckedPhase = s.phase;
    sendUiAck(s.phase);
  }
  if (hasProposedChip && !chipAcked) {
    chipAcked = true;
    sendUiAck("chip");
  } else if (!hasProposedChip) {
    chipAcked = false;
  }
}

function liveChip(entry) {
  const chip = el("div", "chip");
  const preview = el("span", "preview");
  preview.innerHTML = `<b>${escapeHtml(entry.preview)}</b>`;
  const actions = el("div", "chip-actions");
  const approve = el("button", "approve", "Approve");
  const deny = el("button", "", "Deny");
  // Approvals are pointer-only on every surface: no tab focus, and
  // keyboard-synthesized clicks (event.detail === 0) are ignored, so Return
  // or Space can never approve an action.
  approve.tabIndex = -1;
  deny.tabIndex = -1;
  approve.onclick = (e) => {
    if (e.detail === 0) return;
    sendTimed({ type: "approval", call_id: entry.call_id, approved: true });
  };
  deny.onclick = (e) => {
    if (e.detail === 0) return;
    sendTimed({ type: "approval", call_id: entry.call_id, approved: false });
  };
  actions.append(approve, deny);
  chip.append(preview, actions);
  return chip;
}

function ranChip(entry) {
  const chip = el("div", "chip ran");
  const label = el("span", "preview", entry.preview);
  const status = el("span", "status " +
    (entry.status === "completed" ? "ok" : entry.status === "running" ? "" : "err"),
    entry.status);
  chip.append(label, status);
  return chip;
}

/* ---------- transcript ---------- */

function addUserLine(text) {
  finishModelLine();
  $("hint")?.remove();
  transcript.appendChild(el("p", "line user", text));
  transcript.scrollTop = transcript.scrollHeight;
}

function streamModel(text) {
  if (!modelLine) {
    modelLine = el("p", "line model streaming");
    transcript.appendChild(modelLine);
  }
  modelLine.textContent += text;
  transcript.scrollTop = transcript.scrollHeight;
}

function finishModelLine() {
  if (modelLine) modelLine.classList.remove("streaming");
  if (modelLine && !modelLine.textContent.trim()) modelLine.remove();
  modelLine = null;
}

/* ---------- cost + trace ---------- */

function renderCost(r) {
  if (!r) return;
  receiptSeen = true;
  costLine.textContent = `$${(r.estimated_usd ?? 0).toFixed(4)} of $${(r.cap_usd ?? 0).toFixed(2)}`;
  receiptEl.textContent =
    `${r.duration_s}s · ${r.turns} turns · ${r.tool_calls} tool calls · ` +
    `audio in ${r.tokens.audio_in} out ${r.tokens.audio_out} · ` +
    `text in ${r.tokens.text_in} out ${r.tokens.text_out} · cached ${r.tokens.cached_in}`;
}

function addTrace(event) {
  if (event.kind === "response_done") finishModelLine();
  traceEvents += 1;
  traceCount.textContent = `${traceEvents} events`;
  const li = document.createElement("li");
  const t = new Date(event.ts * 1000).toLocaleTimeString();
  const detail = Object.entries(event)
    .filter(([k]) => !["ts", "kind"].includes(k))
    .map(([k, v]) => `${k}=${typeof v === "object" ? JSON.stringify(v) : v}`)
    .join(" ")
    .slice(0, 160);
  li.innerHTML = `${t} <span class="k">${escapeHtml(event.kind)}</span> ${escapeHtml(detail)}`;
  traceList.appendChild(li);
  traceList.scrollTop = traceList.scrollHeight;
}

/* ---------- toasts ---------- */

function toast(text, level = "info", action = null) {
  const t = el("div", `toast ${level}`, text);
  if (action) {
    const a = el("span", "toast-action", action.label);
    a.onclick = () => { action.fn(); t.remove(); };
    t.appendChild(a);
  }
  $("toasts").appendChild(t);
  setTimeout(() => t.remove(), 6000);
}

let overrideOffered = false;
function offerOverride() {
  if (overrideOffered) return;
  overrideOffered = true;
  toast("Session budget reached.", "warn",
    { label: "Override once", fn: () => { send({ type: "override_budget" }); overrideOffered = false; } });
  setTimeout(() => { overrideOffered = false; }, 8000);
}

/* ---------- input: hold-space PTT, pill hold, text ---------- */

function pttDown() {
  if (holding) return;
  holding = true;
  sendTimed({ type: "ptt_down" });
}
function pttUp() {
  if (!holding) return;
  holding = false;
  sendTimed({ type: "ptt_up" });
}

document.addEventListener("keydown", (e) => {
  if (e.code !== "Space" || e.repeat) return;
  if (document.activeElement === $("text-input")) return;
  e.preventDefault();
  pttDown();
});
document.addEventListener("keyup", (e) => {
  if (e.code !== "Space") return;
  if (document.activeElement === $("text-input") && !holding) return;
  e.preventDefault();
  pttUp();
});
window.addEventListener("blur", pttUp);

pill.addEventListener("pointerdown", (e) => { e.preventDefault(); pttDown(); });
pill.addEventListener("pointerup", pttUp);
pill.addEventListener("pointerleave", () => { if (holding) pttUp(); });

$("text-form").addEventListener("submit", (e) => {
  e.preventDefault();
  const input = $("text-input");
  const text = input.value.trim();
  if (!text) return;
  send({ type: "text", text });
  input.value = "";
});

$("stop").onclick = () => sendTimed({ type: "stop" });
$("new-session").onclick = () => {
  send({ type: "new_session" });
  transcript.replaceChildren();
  traceList.replaceChildren();
  traceEvents = 0;
  traceCount.textContent = "0 events";
  modelLine = null;
};

/* ---------- utils ---------- */

function el(tag, cls, text) {
  const node = document.createElement(tag);
  if (cls) node.className = cls;
  if (text !== undefined) node.textContent = text;
  return node;
}
function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  }[c]));
}

connect();
