/* Conn console: capability-authenticated, read-only diagnostics. */

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
let receiptSeen = false;
const capabilityKey = "conn.console.capability";
const consoleCapability = loadConsoleCapability();

function loadConsoleCapability() {
  const fragment = new URLSearchParams(location.hash.slice(1));
  const supplied = fragment.get("cap");
  if (supplied) {
    sessionStorage.setItem(capabilityKey, supplied);
    history.replaceState(null, "", `${location.pathname}${location.search}`);
    return supplied;
  }
  return sessionStorage.getItem(capabilityKey);
}

async function hmacProof(secret, purpose, challenge) {
  const encoder = new TextEncoder();
  const key = await crypto.subtle.importKey(
    "raw", encoder.encode(secret), { name: "HMAC", hash: "SHA-256" }, false, ["sign"]
  );
  const signature = await crypto.subtle.sign(
    "HMAC", key, encoder.encode(`${purpose}:${challenge}`)
  );
  return Array.from(new Uint8Array(signature))
    .map((byte) => byte.toString(16).padStart(2, "0"))
    .join("");
}

function connect() {
  if (!consoleCapability) {
    $("conn-dot").className = "dot failed";
    $("mode-label").textContent = "locked";
    toast("Read-only console requires an explicit debug capability.", "warn");
    return;
  }
  ws = new WebSocket(`ws://${location.host}/ws`);
  ws.onmessage = async (e) => {
    const message = JSON.parse(e.data);
    if (message.type === "auth_challenge") {
      const proof = await hmacProof(
        consoleCapability, "conn-console-websocket-v1", message.challenge
      );
      ws.send(JSON.stringify({ type: "client_hello", role: "console", proof }));
      return;
    }
    handle(message);
  };
  ws.onclose = () => {
    $("conn-dot").className = "dot failed";
    setTimeout(connect, 800);
  };
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
    case "ax_grants":
      renderGrants(msg);
      break;
    case "low_signal":
      toast("Barely heard you: speak up or check the input device.", "warn");
      break;
  }
}


function renderGrants(g) {
  const banner = $("grant-banner");
  const dark = [];
  if (g.app_ax === "not_granted") {
    dark.push("Conn.app lost its Accessibility grant: toggle Conn off and on in System Settings, Privacy and Security, Accessibility.");
  }
  if (g.python_ax === "not_granted") {
    dark.push(`Daemon lane has no Accessibility grant: add ${g.python_grant_target} in System Settings, Privacy and Security, Accessibility, then relaunch.`);
  }
  banner.hidden = dark.length === 0;
  banner.textContent = dark.join(" ");
}


function renderState(s) {
  let [label, sub] = PHASE_LABEL[s.phase] || [s.phase, ""];
  if (s.phase === "done" && s.last_action_outcome === "dispatch_only") {
    [label, sub] = ["Sent, not confirmed", "effect was not observable"];
  } else if (s.phase === "done" && s.last_action_outcome && s.last_action_outcome !== "verified") {
    [label, sub] = ["Did not run", "no confirmed effect"];
  }
  pill.dataset.phase = s.phase;
  pill.dataset.outcome = s.last_action_outcome || "";
  pillState.textContent = label;
  pillSub.textContent = sub;
  $("conn-dot").className = "dot" + (s.connected ? " connected" : "");

  chipsEl.replaceChildren();
  for (const entry of s.ledger || []) {
    chipsEl.appendChild(entry.status === "proposed" ? liveChip(entry) : ranChip(entry));
  }

  if (s.phase === "budget_hold") offerOverride();
  if (s.phase === "done" || s.phase === "idle") finishModelLine();
  if (typeof s.spent_usd === "number" && !receiptSeen) {
    costLine.textContent = `$${s.spent_usd.toFixed(4)}`;
  }

}

function liveChip(entry) {
  const chip = el("div", "chip");
  const preview = el("span", "preview");
  preview.innerHTML = `<b>${escapeHtml(entry.preview)}</b>`;
  const status = el("span", "status warn", "Approve in Conn");
  chip.append(preview, status);
  return chip;
}

function ranChip(entry) {
  const chip = el("div", "chip ran");
  const label = el("span", "preview", entry.preview);
  const status = el("span", "status " +
    (["completed", "verified"].includes(entry.status) ? "ok" :
      entry.status === "unverified" ? "warn" : entry.status === "running" ? "" : "err"),
    entry.status);
  chip.append(label, status);
  return chip;
}


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
  toast("Session budget reached. Use Conn.app to continue.", "warn");
  setTimeout(() => { overrideOffered = false; }, 8000);
}


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
