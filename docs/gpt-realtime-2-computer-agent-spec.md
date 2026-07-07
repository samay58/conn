# Conn: a push-to-talk voice command surface for the Mac

Spec for the GPT-Realtime-2 computer agent. Written 2026-07-02 after a live
docs research pass, an architecture pressure test, and the v0 build. The
runnable code in this folder is the reference implementation of everything
below.

## Product thesis

Hold a key, say a command, release. Conn understands the target, takes the
smallest safe action through a local tool harness, and gives immediate
feedback. Low-risk actions execute at once. Risky actions show a crisp
approval chip stating exactly what will happen. Every session leaves a trace
and a cost receipt. No always-on mic, no ambient screen watching, no chatbot.

The name: "you have the conn" is the naval handoff of steering authority. The
officer with the conn commands by voice; the helm executes precisely;
authority is explicit, bounded, and revocable. Push-to-talk is taking the
conn. The stop button is "belay that."

Voice is worth using only where it beats the keyboard. v0 bets on three
spots: app switching while your hands are mid-task, vault search without
breaking focus, and read-back of current context. It deliberately excludes UI puppeteering
(clicks, typing) until per-app profiles can make that safe and reliable. The
Premiere-style demos are an inspiration benchmark, not scope.

## Naming decision

Twenty candidates were generated and judged; finalists were verified against
the live namespace by web search. The voice-Mac-tool space is heavily mined,
which killed several better-sounding options.

| Name | Feel | Why it fits | Downside | Folder/CLI |
|---|---|---|---|---|
| Conn (chosen) | "You have the conn" | Spoken command handoff; bounded, revocable authority | Reads as "con" until the story lands; CONN fMRI toolbox exists in neuroscience | `conn` |
| Cue | Theater cue | PTT is literally giving a cue | cuelang owns the `cue` CLI | `cue` |
| Relay | Signal handoff | Operational, user's own shortlist | GraphQL Relay, Relay FM, relay.app; generic | `relay` |
| Lever | Mechanical advantage | Small input, big output; user's shortlist | Lever ATS, a common hiring-tool name; generic | `lever` |
| Baton | Conductor, relay handoff | Small gesture, orchestrated action | getbaton.dev is an AI coding-agent orchestrator; ConductorOne `baton` CLI | `baton` |
| Sotto | Sotto voce | Speak quietly, computer acts | Multiple Mac dictation apps named exactly Sotto | `sotto` |
| Envoy | Delegate acting for you | Exact delegation semantics | Envoy proxy | `envoy` |
| Helm | Command seat | Steering authority | Kubernetes Helm | `helm` |
| Dispatch | Command routing | Operational verb | Long; generic | `dispatch` |
| Switchboard | Operator era | Command routing, retro charm | Too long for a menu bar | `switchboard` |
| Tiller | Boat steering | Quiet small corrections | Tiller Money | `tiller` |
| Yoke | Aircraft control | Direct manual command | Burden sense; homophone | `yoke` |
| Valet | Quiet service | Small tasks done for you | Servile; parking apps | `valet` |
| Beck | Beck and call | Short, command-native | Obscure; the musician | `beck` |
| Hark | Listening | Voice-native | One-way; npm `hark` speech lib | `hark` |
| Fiat | "Let it be done" | A spoken decree that executes | The car; currency discourse | `fiat` |
| Spoke | Past tense of speak; wheel spoke | "I spoke, it happened" | Reads odd as a product name | `spoke` |
| Jig | Workshop fixture | The harness constrains the tool so the cut is safe | Covers safety, not voice | `jig` |
| Puck | Sprite doing the bidding | Mischief-free execution | puck.news; the hockey object | `puck` |
| Bosun | Whistle-piped commands | Short signal, precise crew action | Obscure; Stack Exchange Bosun | `bosun` |

Conn wins on story fit (the metaphor teaches the safety model), length, and a
clean namespace. Relay and Lever, the early bias, lose on collisions: Relay is
crowded three ways and Lever already reads as the common ATS product name.

Prior art: Pat Simmons's demo setup is public at `per-simmons/voice-os`
("gpt-realtime-2 + agent-desktop"). Useful to skim for tool-schema ideas; the
architecture here differs deliberately (local harness owns permissions, PTT
only, no broad accessibility control in v0).

## What the research pass confirmed and corrected

Primary sources: the gpt-realtime-2 model page, the Realtime guides
(conversations, WebSocket, WebRTC, VAD, function calling, MCP, server
controls), the prompting guide, and the Realtime API blog notes, all fetched
2026-07-01.

Confirmed as assumed: model capabilities and modalities (text, audio, image
in; text, audio out; no video), 128k context, 32k max output, reasoning
tokens with `minimal` through `xhigh` effort and `low` recommended for
production voice agents, pricing (text $4 in / $24 out, audio $32 in / $64
out, image $5 in, cached input $0.40, per 1M tokens), transport guidance
(WebRTC for browser-owned audio, WebSocket when a backend owns raw audio, SIP
for telephony), ephemeral client secrets for browser clients, function tools
for local logic versus remote MCP tools, and sideband server control.

Drift and gaps that changed the design:

- Push-to-talk is `turn_detection: null` plus manual `input_audio_buffer`
  commits. With VAD off there is no server-side idle timeout machinery, so
  the daemon owns idle timeout.
- The session duration ceiling for gpt-realtime-2 is not documented.
  Reconnect-with-fresh-session is built in and surfaced honestly in the UI
  (context loss is announced, never hidden).
- Async function calling exists but is thinly documented for this generation.
  Hallucinated completion is a named failure mode in the prompting guide with
  a named mitigation. Conn enforces it structurally (below), not just in the
  prompt.
- Realtime prompt caching mechanics are underdocumented; the cost meter
  reads actual cached-token counts from usage rather than predicting them.
- The launch announcement pages describe the previous generation
  (`gpt-realtime`, 32k context); their numbers must not be reused.
- Learned from the first live smoke test, not the docs: tool names must match
  `^[a-zA-Z0-9_-]+$`. Dotted names got the whole session.update rejected,
  which silently took the instructions down with it and left a vanilla
  assistant. The registry now uses underscore names and a regression test
  encodes the wire pattern.

## Architecture

One Python daemon owns everything; a thin localhost web console renders it.

- The daemon (Phoenix `.venv`, single asyncio loop) holds the WebSocket to
  OpenAI, the API key, mic capture gated by PTT, audio playback, the tool
  harness, approvals, traces, and the cost meter. A native process that owns
  raw audio is the documented WebSocket case, so there is no ephemeral-token
  dance and no client that could leak the key. Sideband by construction.
- The console (vanilla HTML/CSS/JS served at 127.0.0.1:8787) is a pure view
  and approval surface. It renders PTT state, transcript, chips, a
  collapsible trace, and a live cost line. It never talks to OpenAI.
- Push-to-talk is dual: hold Space in the console (zero TCC grants, always
  works) or hold Right Option globally via pynput (Input Monitoring grant,
  verified by `conn doctor`, degrades gracefully).
- Typed input is a peer of voice, not demo scaffolding: the same
  conversation item path drives live sessions, which gives a free degraded
  mode when audio breaks.
- Demo mode swaps one adapter: a scripted fake plays scenario files through
  the identical machine, harness, trace, and cost paths, with zero
  credentials and (with `--simulate-tools`) zero side effects.
- The native shell (shipped same day, `macos/`): a SwiftUI menu-bar app that
  speaks the daemon's WebSocket protocol. Floating voice panel with a
  level-driven waveform (the daemon streams mic and playback rms), state
  label, transcript line, approval chips, and a live cost line. The app
  autolaunches the daemon when none is running, owns the Right Option
  hold-to-talk through its own Accessibility grant (so the daemon runs
  `--no-hotkey` and the terminal needs no TCC at all), and installs to
  /Applications via `make-app.sh install`. `Conn --preview` renders the
  panel's key states deterministically for design iteration.

Rejected alternatives: browser WebRTC plus a companion daemon splits the
session across two runtimes and buys echo cancellation and VAD that PTT does
not need; SwiftUI-first misses a one-session craft bar; extending the legacy
eval lab never demos the product.

### The state machine and the anti-hallucination invariant

States: idle, listening, thinking, acting, awaiting_approval, speaking, done,
failed, budget_hold. The machine is pure (no I/O) and exhaustively tested,
including barge-in, sub-300ms tap abort (zero spend), denial and timeout
paths, budget hold, and reconnect.

The invariant that makes tool use honest: the model cannot speak about a tool
outcome until the daemon sends the function result and issues the next
`response.create`. While any call is pending or awaiting approval, the daemon
withholds that continuation, so the model is structurally paused; there is no
window where it can claim completion. A pending-call ledger (proposed,
running, completed, failed, denied, timeout, blocked) enforces
all-calls-resolved-before-continuation for multi-call responses and renders
verbatim in the console.

Barge-in in v0 is cancel-and-flush (response.cancel plus local buffer flush),
logged as such. Millisecond-accurate `conversation.item.truncate` is deferred
to v0.5.

## Tool contract

Each tool declares a description, JSON schema, risk level, a preview renderer
for chips, good and rejected call examples, a timeout, and its trace payload.
The registry exports the schemas into the session config; the harness owns
every gate decision. The model proposes; the harness disposes.

Risk levels map to gates: read and act_low run immediately; act_confirm shows
a chip and waits (30 seconds, then denied); blocked returns a structured
refusal with the specific reason so the model learns the boundary. Config can
escalate any tool to confirm or block it outright; config can never unblock a
v0-disabled tool.

Executable in v0:

| Tool | Risk | Mechanism | Notes |
|---|---|---|---|
| computer_get_context | read | NSWorkspace frontmost app; window title and selected text via AX when Accessibility is granted | Degrades to app name only; never the cmd+C clipboard hack |
| computer_screenshot | read | `screencapture -x` to a session-scoped dir | Deleted at session end unless `screenshots.keep`; not sent to the model by default |
| app_open / app_switch | act_low | `open -a` | Allowlist enforced in the harness |
| browser_search | act_low | `open` on the configured search URL | Query is URL-encoded; default browser |
| phoenix_search | read | `qmd search` subprocess, parsed results | BM25; absolute binary path from config |
| phoenix_open_note | act_low | `obsidian://open` URL | Path must resolve inside the vault root |
| clipboard_set | act_low | `pbcopy` | Size-capped; escalatable to confirm in config |
| wait_for_user | read | No-op | The prompting guide's unclear-audio pattern |

Specced and blocked in v0, pending per-app profiles: computer_click,
computer_type_text, computer_hotkey, computer_ax_tree. Their schemas exist
and are exported so the refusal path teaches the model; their executors are
unreachable. The shell allowlist ships empty. Zero osascript anywhere means
zero Automation prompts.

## Safety model

The harness owns permissions; the model only proposes. Specifically:

- Push-to-talk only. The mic stream is open for latency reasons but frames
  are forwarded upstream only while the key is held.
- No persistent screen streaming; screenshots are single, on-demand, local,
  and deleted at session end by default.
- Destructive and outbound actions do not exist in the v0 toolset; the
  approval gate (act_confirm) is the mechanism they will arrive through.
- Approval timeouts deny. Denials and blocks flow back to the model as
  structured errors with reasons.
- Secrets stay in the daemon's environment; the console and the model never
  see them.
- Logs are local JSONL, gitignored.
- Kill switch: the Stop button cancels the response, flushes audio, clears
  input, and ends the upstream session. The budget hard stop is a second,
  independent brake.

TCC reality, as verified by `conn doctor` on this machine: Microphone
auto-prompts and is checked by actual RMS; Accessibility is optional (window
title and selection in get_context); Screen Recording is optional
(screenshot content); Input Monitoring is required only for the global
hotkey and is the flakiest grant on modern macOS, which is why console PTT
is the foundation and the hotkey is the upgrade.

## UX states and craft

One continuous light-mode card: header (identity, mode, new session, stop),
transcript (user bubbles right, streaming model lines left), chips (amber
awaiting approval with Approve/Deny, quiet post-hoc rows for executed calls
with status), the PTT pill plus a typed-command field, and a footer meter
(event count, running cost against cap) that expands into the full trace and
receipt.

The pill is the state surface: Idle, Listening (accent ring), Thinking,
Acting, Approve? (amber), Speaking, Done (green flash), Reconnecting,
Budget hold (red family). Motion is limited to state changes: a 140ms chip
rise, a caret blink while streaming. No glow, no dark glass, radii at 7 to
10px, system text face with a monospace reserved for trace and receipt lines.

The native panel adds one rule learned the hard way: it never takes keyboard
focus. The first build made the panel key when a chip appeared, and a Return
keystroke meant for another app silently approved a pending action. Approvals
are deliberate pointer clicks; the panel is a nonactivating layer that cannot
intercept typing.

## Cost model

`response.create` is the only spend trigger and the daemon owns every one,
including tool-result continuations, so the budget gate is one function in
one place. The meter ingests per-response usage (text, audio, cached splits),
prices from config, and keeps per-turn line items so the superlinear cost of
long sessions is visible instead of surprising. Defaults: reasoning effort
low, $1.00 hard cap per session, warning at $0.50, idle disconnect after five
minutes, short-replies prompt discipline. The receipt (duration, turns,
token classes, tool calls, screenshots, estimated dollars, per-turn dollars)
streams live and persists per session.

Cheap-enough-to-use-daily target: a five-command session should stay under
$0.25. The demo receipts price a realistic command turn at one to three
cents; the live smoke test validates the real number.

## Eval plan

Two layers, honestly separated:

- Harness evals (automated, demo mode): `python -m conn --eval` drives six
  cases through the real composition root and asserts tool sequence, gate
  decisions, approval counts, result honesty, and terminal phase, while
  measuring first-feedback and end-to-end latency and writing artifacts to
  `data/evals/`. These prove the loop, the gates, and the receipts; they do
  not prove model quality.
- Live evals (manual checklist, `docs/LIVE_EVAL_CHECKLIST.md`): the nine
  prompt tasks including disambiguation, refusal, and recovery, each with
  fields for latency, tool calls, clarifying questions, gate correctness,
  cost, and a faster-than-manual verdict.

Pass condition for the project: trace-backed evidence of where voice beats
the keyboard, not a demo that worked once.

## What is deliberately not built yet

Arbitrary UI control (needs per-app profiles with named, validated targets),
screenshot-to-model image input (plumbing exists; off until a task proves the
need), `conversation.item.truncate` barge-in precision, MCP adapters, a
Phoenix write lane (voice capture into the vault behind an approval chip),
and any shell command execution. Each gets built when traces show the need,
not before. Deployment to a second machine is documented in
`docs/DEPLOYMENT.md`.
