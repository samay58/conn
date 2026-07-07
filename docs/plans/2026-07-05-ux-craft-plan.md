# Conn UX Craft Implementation Plan

> **For agentic workers:** This plan executes under `~/.claude/FABLE-ORCHESTRATION.md`. Each packet is dispatched to the model tier named in its header; packet builders MUST use superpowers:test-driven-development and see only their own packet plus Global Constraints and their Interfaces block. The orchestrator (Fable) reads diffs, reports, and screenshots only. Steps use checkbox syntax for tracking.

**Goal:** Take Conn from shipped-and-safe to the notch-island surface specified in [../2026-07-05-ux-craft-spec.md](../2026-07-05-ux-craft-spec.md): measured-fast, reliable under transport death, and award-grade in motion, type, and sound.

**Architecture:** Instrumentation and reliability land first in the Python daemon (measure before craft, honesty before beauty). The island then rises in Swift as new focused files beside the frozen fallback panel, all animation values in one tokens file, tuned live through a playground rather than rebuilt. Sound and the AX-via-app migration run as parallel lanes at the end.

**Tech Stack:** Python 3.14 daemon (Phoenix `.venv`, asyncio, pytest), SwiftPM app (SwiftUI + AppKit NSPanel, new XCTest target), zsh build script.

## Global Constraints

- Working dir: `/Users/samaydhawan/conn`. Python: `PYTHONPATH=src /Users/samaydhawan/conn/.venv/bin/python`. Never create a second venv.
- Baseline `python -m pytest tests -q` was 82 passed at Phase 0 start (the original 81 undercounted; 162 after Phase 1); every packet leaves the full suite green. Swift: `./make-app.sh` builds bare via the R4 toolchain probe, and raw `swift build`/`swift test` still need `DEVELOPER_DIR=/Applications/Xcode-beta.app/Contents/Developer` on this machine.
- Safety invariants are untouchable: harness gates every tool call, continuations withheld until results are real, budget hard stop, approvals pointer-only, island/panel window always `styleMask [.borderless, .nonactivatingPanel]` and never key.
- Every animation duration, spring, and palette value in Swift lives in `DesignTokens.swift` only (enforced by test I1-T1). Spec tables in `docs/2026-07-05-ux-craft-spec.md` are the source of truth; tuned values get written back there in the same commit that changes the tokens.
- No monospace font names and no `design: .monospaced` anywhere in island Swift sources; no `.tracking(` and no `.uppercased()` on state labels.
- Tool names must match `^[a-zA-Z0-9_-]+$` (wire regression, tests/test_registry pattern already encodes it).
- Commits: lowercase `conn:` prefix, imperative, one packet per commit unless a packet says otherwise. No em-dashes in any commit, comment, or doc line; run `python3 ~/.claude/scripts/slopcheck.py` on any doc a packet touches.
- Packet builders return a structured report (files touched, tests added, commands run with results, open questions). A packet you cannot complete comes back as a question, not a guess.

## Review gates, applied at the end of every phase

1. **Mechanical:** every done-definition command in the phase, rerun together, green.
2. **Adversarial:** packets marked [ADV] get an Opus reviewer prompted to refute ("find where this violates the spec, the safety invariants, or breaks an edge; your job is to kill it, not bless it"). Findings verified against source before any rework is ordered.
3. **Taste:** Fable reviews diffs and preview screenshots only. Deletions get extra scrutiny.

Manual stop points are named STOP: Samay's hands on the real app; screenshots do not substitute.

Ledger discipline: append output-token split and gate results to `docs/orchestration-ledger.md` at every phase boundary.

---

## Phase 0: Measure and stop lying (daemon)

Order: P0-A, P0-B, P0-C parallel; P0-D after P0-B and P0-C; P0-E after P0-D; R4 parallel with everything.

### Packet P0-A: Trace schema v2 [sonnet, effort default]

**Files:**
- Modify: `src/conn/events.py`, `src/conn/trace.py`
- Test: `tests/test_trace_v2.py` (new)

**Interfaces (produces, exact):** new trace kinds written via the existing `trace.log(kind, **payload)`:
- `ptt_down` / `ptt_up`: payload `{client_ts_ms: int | None, source: str}` where source is `"hotkey" | "console" | "panel"`
- `phase_change`: `{from_phase: str, to_phase: str, turn: int}`
- `model_delta`: `{response_id: str, modality: str}` logged only for the first delta of each response (`"audio" | "text"`)
- `audio_silent`: `{after: str}` (`"flush" | "drain"`)
- `ui_ack`: `{moment: str, client_ts_ms: int}` (`"listening" | "thinking" | "chip"`)
- `PttDown`/`PttUp` dataclasses gain field `client_ts_ms: int | None = None`; `now_ms()` gains a monotonic sibling `mono_ms()` used for all span math.

- [x] Write failing tests: each kind serializes to one JSONL line with exactly the fields above; `PttDown(client_ts_ms=123)` round-trips.
- [x] Run `python -m pytest tests/test_trace_v2.py -q`, expect FAIL.
- [x] Implement; full suite green.
- [x] Commit `conn: trace schema v2 with client timestamps`.

**Done:** `python -m pytest tests -q` green with new tests listed.

### Packet P0-B: Upstream close honesty [sonnet, effort default] [ADV]

**Files:**
- Modify: `src/conn/realtime/openai_ws.py`
- Test: `tests/test_ws_close.py` (new)

**Interfaces (produces):** `events()` yields `RtClosed(reason="connection closed: clean")` when the socket iterator ends without exception and the adapter is not closing; `connected` is False after any exit from `events()`; `close()` sets an internal `_closing` flag the iterator checks.

- [x] Failing tests with a fake ws object: clean iterator end yields RtClosed; `connected` False after clean end, after exception end, and after `close()`; no RtClosed yielded when `close()` initiated the end.
- [x] Implement (null `_ws` on all exit paths; yield the synthetic RtClosed).
- [x] Full suite green; commit `conn: upstream clean close yields RtClosed and invalidates connected`.

**Done:** named tests pass; adversarial reviewer confirms the Jul 3 wedge sequence (error event, then clean server close) now lands in the disconnect path.

### Packet P0-C: State machine effects [sonnet, effort default] [ADV]

**Files:**
- Modify: `src/conn/state.py`
- Test: `tests/test_state_reliability.py` (new)

**Interfaces (produces):**
- New command dataclass `RejectInput(reason: str)`: `_ptt_down` returns `[RejectInput(reason=phase.value)]` instead of `[]` in non-accepting phases.
- `transition()` return gains nothing; instead machine exposes `last_transition: tuple[Phase, Phase] | None` for the app to trace.
- New event `WatchdogTick()`: in any phase except IDLE and AWAITING_APPROVAL, if no transition and no pending call for `watchdog_timeout_s`, machine returns the same command list as `WsFailed` (existing failure path).

- [x] Failing tests: PTT in THINKING yields RejectInput("thinking"); watchdog in stuck THINKING forces failed; watchdog in IDLE is a no-op; existing 81 tests untouched.
- [x] Implement; full suite green; commit `conn: reject-input effect and any-phase watchdog`.

**Done:** named tests pass; state machine remains pure (no I/O added).

### Packet P0-D: App wiring [sonnet, effort default] [ADV]

**Files:**
- Modify: `src/conn/app.py`, `src/conn/server/http.py`, `src/conn/cost.py`
- Test: `tests/test_app_reliability.py`, `tests/test_receipt_incremental.py` (new)

**Interfaces (consumes):** P0-A kinds, P0-B RtClosed semantics, P0-C RejectInput/WatchdogTick/last_transition.
**Interfaces (produces):**
- Every dispatch logs `phase_change` when `machine.last_transition` changed.
- WS inbound `{"type":"ptt_down","client_ts_ms":...}` (and ptt_up/approval/stop) thread client_ts into events; `hello` message gains `"server_ts_ms"`.
- Adapter send failures inside `_exec` for `CommitInput | CreateResponse | SendText | SendToolResult` dispatch the disconnect path instead of raising to the socket handler.
- `RejectInput` publishes `{"type": "reject_input", "reason": ...}` to clients.
- Watchdog timer fires `WatchdogTick` every 60s; `watchdog_timeout_s = 600` in config with default.
- `healthz` adds `"phase_age_s": float, "upstream_connected": bool`.
- `CostMeter.write_receipt_snapshot()` called at every `response_done`; receipt file exists from first turn, `"final": false` until session end flips it.
- `audio_silent` traced from the playback flush/drain callbacks; `model_delta` traced on first delta per response.

- [x] Failing tests: send-raise lands in failed not thinking; ptt in thinking publishes reject_input; healthz fields present and phase_age_s grows under a frozen clock; receipt file exists after first response_done with final false; kill mid-session leaves a valid receipt.
- [x] Implement; full suite green; `python -m conn --eval` still 6/6.
- [x] Commit `conn: reliability wiring, healthz staleness, incremental receipts`.

**Done:** named tests pass, `--eval` 6/6, live smoke: kill the wifi mid-turn and the console shows Reconnecting within 1s.

### Packet P0-E: Latency spans [sonnet, effort default]

**Files:**
- Create: `src/conn/latency.py`
- Modify: `src/conn/evals.py`, `src/conn/__main__.py`, `evals/tasks.json`
- Test: `tests/test_latency_report.py` (new)

**Interfaces (consumes):** P0-A trace kinds. **Produces:** `latency.spans(trace_path) -> dict` with keys `keydown_to_listening_ms, release_to_ack_ms, release_to_first_token_ms, release_to_first_tool_ms, proposal_to_chip_ms, stop_to_silence_ms` (None when the span's events are absent); `python -m conn --latency-report <trace.jsonl>` prints the six spans and budget pass/fail against the spec table; receipts gain a `latency` block per turn.

- [x] Failing tests against a fixture trace file containing all v2 kinds; spans compute to known values; missing kinds yield None not crashes.
- [x] Implement; add one eval case asserting v2 kinds appear in a demo run; commit `conn: latency spans and report`.

**Done:** `--latency-report` on a fixture prints six spans; `--eval` green (now 7 cases).

### Packet R4: Launcher log, zombie policy, toolchain probe [sonnet, effort low]

**Files:**
- Modify: `macos/Sources/Conn/DaemonLauncher.swift`, `macos/make-app.sh`

**Interfaces (consumes):** healthz `phase_age_s`/`upstream_connected` from P0-D (ships in parallel; adopt policy activates once fields exist, treats absence as healthy for back-compat).
**Produces:** daemon stdout/stderr piped to `data/logs/daemon-YYYY-MM-DD.log` (7-day retention, pruned at launch); adopt policy: adopt when `phase == "idle" && upstream_connected` or `phase_age_s < 120`, otherwise terminate the PID owning the port and spawn fresh; `make-app.sh` probes `swift build --version`, falls back to `DEVELOPER_DIR=/Applications/Xcode-beta.app/Contents/Developer`, exits 1 with the fix line if neither works.

- [x] Implement; verify: `./make-app.sh` succeeds bare; launch app, `ls data/logs/` shows today's file; wedge drill below.
- [x] Commit `conn: daemon log file, zombie adoption policy, toolchain probe`.

**Done:** build green bare; log file exists; manual: wedge a daemon (kill -STOP), relaunch app, fresh session id in healthz.

### STOP 1 (end of Phase 0): reliability drill, Samay driving

Fresh build, live session, five real commands. Then: toggle wifi off mid-turn (Reconnecting visible within 1s), press PTT during thinking (reject pulse event visible in console trace), read `--latency-report` on the session trace (four daemon-side spans real; ui_ack spans arrive Phase 1). Phase gate runs after this drill.

Execution record 2026-07-05: all six packets committed (bd646917a, 48eff5526, fda444718, d9a6dc8a9, 5d1746aa7, 3eceae4aa) plus remediation P0-F for adversarial findings (a96a24d73 watchdog seq re-arm and single fire, 7576968fa generator-abandonment socket null, 1867dbc0e atomic receipt writes). Suite 150 passed. Mechanical and adversarial gates green; STOP 1 is the open item.

---

## Phase 1: Island structure (Swift)

Order: I1 and I2 parallel; I3 after I2; I4 parallel with I3; I5 after I3. Adds an XCTest target: `Package.swift` gains `.testTarget(name: "ConnTests", dependencies: ["Conn"], path: "Tests/ConnTests")`; that Package.swift change belongs to I2 (first Swift test packet).

### Packet I1: Design tokens + no-magic-numbers test [haiku, effort low]

**Files:**
- Create: `macos/Sources/Conn/DesignTokens.swift`
- Test: `tests/test_design_tokens.py` (new, python grep test)

**Interfaces (produces, exact names consumed by every island packet):**
```swift
enum DesignTokens {
    // motion
    static let summonSpring = Spring(response: 0.28, dampingFraction: 0.80)
    static let collapseSpring = Spring(response: 0.22, dampingFraction: 0.90)
    static let chipOpenDuration = 0.16, chipButtonsFadeDelay = 0.06
    static let stateWordCrossfade = 0.12, doneSettleDuration = 0.32
    static let doneCollapseDelay = 0.90, refusalPulseDuration = 0.25
    static let belaySnapDuration = 0.12, contentStaggerDelay = 0.08
    // personality
    static let aliveness = 1.0
    static let breathAmplitude = 0.015, breathPeriod = 3.2
    static let squashHeightOvershoot = 0.04, squashWidthOvershoot = 0.02
    static let squashWidthLeadMs = 40.0, exhaleContraction = 0.02, exhaleDuration = 0.22
    // palette (island, on black)
    static let islandBg = Color.black
    static let islandText = Color.white.opacity(0.92)
    static let islandTextSecondary = Color.white.opacity(0.58)
    static let islandAccent = Color(red: 0.48, green: 0.65, blue: 0.88)
    static let islandAmber = Color(red: 0.91, green: 0.63, blue: 0.24)
    static let islandGreen = Color(red: 0.30, green: 0.76, blue: 0.54)
    static let islandRed = Color(red: 0.88, green: 0.32, blue: 0.32)
    // geometry
    static let islandGrowWidth: CGFloat = 64, islandGrowHeight: CGFloat = 26
    static let islandCornerRadius: CGFloat = 14, chipRowHeight: CGFloat = 44
}
```
- [x] Write `tests/test_design_tokens.py`: greps `macos/Sources/Conn/*.swift` excluding DesignTokens.swift for numeric literals inside `.animation(`, `withAnimation(`, `Spring(`, and for `design: .monospaced`, mono font names, `.tracking(`, `.uppercased()`; passes only when none found. Run: passes trivially now, guards every later packet.
- [x] Create the tokens file; build green; commit `conn: design tokens and magic-number guard`.

**Done:** `python -m pytest tests/test_design_tokens.py -q` green; swift build green.

### Packet I2: IslandGeometry [sonnet, effort default]

**Files:**
- Create: `macos/Sources/Conn/IslandGeometry.swift`, `macos/Tests/ConnTests/IslandGeometryTests.swift`
- Modify: `macos/Package.swift` (add test target)

**Interfaces (produces):**
```swift
struct IslandGeometry {
    init?(screenFrame: CGRect, safeTopInset: CGFloat, auxTopLeft: CGRect?, auxTopRight: CGRect?) // nil when no notch
    var notchRect: CGRect                       // screen coords, the hardware rect
    func expandedFrame(chipOpen: Bool) -> CGRect // notch grown by DesignTokens.islandGrow*, plus chipRowHeight when chipOpen
    static func forScreen(_ screen: NSScreen) -> IslandGeometry? // reads the real values
}
```
- [x] Failing XCTests: known M4 Air numbers produce a centered notchRect; no-notch screen returns nil; expandedFrame math exact against tokens.
- [x] Implement; `DEVELOPER_DIR=... swift test` green; commit `conn: island geometry from notch metrics`.

**Done:** `swift test --filter IslandGeometryTests` green.

### Packet I3: Island shell [sonnet, effort default] [ADV]

**Files:**
- Create: `macos/Sources/Conn/IslandController.swift`

**Interfaces (consumes):** IslandGeometry, DesignTokens. **Produces:**
```swift
final class IslandController {
    init(state: AppState, client: DaemonClient, geometry: IslandGeometry)
    func summon()    // creates/orders front the nonactivating panel at expandedFrame
    func collapse()  // returns to nothing; panel ordered out after animation
    func apply(phase: String) // maps the nine phases to summon/collapse/hold per spec state table timing
}
```
Panel config mirrors PanelController exactly: `[.borderless, .nonactivatingPanel]`, `.statusBar` level, `.canJoinAllSpaces, .fullScreenAuxiliary`, `orderFrontRegardless()`, appearance NOT forced to aqua (island is black by design). Content view arrives in Phase 2; shell renders a black rounded placeholder.

- [x] Implement with placeholder content; hand check: island appears over the notch on key-down path via a temporary debug hook, typing in another app loses zero keystrokes while it shows.
- [x] Commit `conn: island shell, nonactivating, notch-anchored`.

**Done:** build green; adversarial review confirms focus rules and level; manual typing-continuity check recorded in the report.

### Packet I4: Client timing acks [sonnet, effort low]

**Files:**
- Modify: `macos/Sources/Conn/DaemonClient.swift`, `macos/Sources/Conn/AppState.swift`, `macos/Sources/Conn/HotkeyMonitor.swift`, `console/app.js`

**Interfaces (consumes):** P0-D message contract. **Produces:** both clients stamp `client_ts_ms` (monotonic) on ptt_down/ptt_up/approval/stop; both send `{"type":"ui_ack","moment":...,"client_ts_ms":...}` after first render of listening, thinking, and chip (Swift: `CATransaction.setCompletionBlock` on the state apply; console: `requestAnimationFrame` callback); AppState gains `@Published var rejectPulse: Int` incremented on `reject_input` messages.

- [x] Implement; verify with a live session: `--latency-report` now fills all six spans.
- [x] Commit `conn: client timestamps and ui acks`.

**Done:** report shows keydown_to_listening_ms and proposal_to_chip_ms real numbers on a fresh trace.

### Packet I5: Surface routing [sonnet, effort low]

**Files:**
- Modify: `macos/Sources/Conn/AppDelegate.swift`, `macos/Sources/Conn/PanelController.swift`

**Interfaces:** `IslandGeometry.forScreen(.main)` non-nil routes phase changes to IslandController; nil keeps PanelController exactly as today. PanelController gains only a toast line (AppState.toast rendered as text, closing the panel half of the toast gap) and no other change.

- [x] Implement; commit `conn: route island on notch displays, panel elsewhere`.

**Done:** build green; on this Mac the island path is active; setting a debug env `CONN_FORCE_PANEL=1` shows the old panel unchanged.

Execution record 2026-07-05: five packets committed (43007bfcd I1, a2cc95af9 I2, a0abdd46e I3, b5fcc736d I4, 8ae07383f I5) via workflow wf_35e7042c, all TDD, zero blocked. Orchestrator on Opus (Fable budget exhausted; strategy unchanged, see the ledger freeze note). I3 adversarial review returned one MAJOR (Color.cgColor Optional could render an invisible island) remediated inline at 5cc45b63c, and one MINOR (done/failed self-dismiss) tracked to I6. Suite 162 passed; `swift test` geometry 4 passed; `./make-app.sh` builds bare. Deviations logged in the ledger: I1 haiku to sonnet-low, sequential dispatch not parallel waves, guard scoped to island sources (PanelView and WaveformView exempt, WaveformView rejoins at I7). Phase 1 mechanical, adversarial, and taste gates green. Phase 1 closes at this gate; the first island hands-on is STOP 2 at the end of Phase 2.

Phase 1 gate, then proceed.

---

## Phase 2: State vocabulary and typography (design cores)

Order: I6 then I7 then I8 (shared visual language settles in sequence); I9 parallel after I6.

### Packet I6: IslandView, all nine states [opus, effort high] [ADV]

**Files:**
- Create: `macos/Sources/Conn/IslandView.swift`
- Modify: `macos/Sources/Conn/IslandController.swift` (hosting only: swap placeholder for IslandView)

**Interfaces (consumes):** AppState published fields (phase, userLine, modelLine, spentUSD, toast, rejectPulse, level), DesignTokens, spec state table. **Produces:** `IslandView(state:client:)` rendering every row of the spec's state table except the chip row (I8): waveform slot, sentence-case state word 11pt, transcript line 13pt, cost figure with `.monospacedDigit()`, tool name during acting, toast line replacing state word for 3s, budget-hold override click target sending `{"type": "override_budget"}`, reconnect and done treatments, refusal pulse shake keyed off rejectPulse (2px, 3 cycles, tokens duration).

- [x] Implement against the spec state and typography tables exactly; every literal from tokens.
- [x] Verify: `python -m pytest tests/test_design_tokens.py -q` green (the guard is the mechanical check), build green.
- [x] Commit `conn: island state vocabulary and typography`.

**Done:** token guard green; preview screenshots (I9) show nine distinct states; adversarial reviewer checks each state against the spec table row by row.

Execution record 2026-07-06: two commits (33b9510f1 IslandView + host, 01b8dbaa9 adversarial remediation). Token guard 12/12, `swift build` green, full python suite 166 passed (excluding a foreign untracked `test_ax_snapshot.py` from a parallel AX-feature track). Independent Opus adversarial review returned one CONFIRMED low finding (budget_hold rendered the generic stateLabel instead of the spec's "$ cap reached"), remediated inline; it independently cleared the keyboard-focus attack on the new override Button (canBecomeKey=false blocks any Return path). Scope notes: I6 also added three motion tokens to DesignTokens (refusalShakeMagnitude/Cycles, toastDuration) since the guard forbids raw motion numbers, and the interactive Deny/Approve chip is deliberately left to I8 (I6 renders a non-interactive approval preview). Key finding for I9: the C2 cleanup left a full private island rendering inside PreviewWindow.swift (IslandPreviewSurface); I9 must retarget the preview at the canonical IslandView to kill the fork.

### Packet I7: Island waveform [opus, effort high]

**Files:**
- Modify: `macos/Sources/Conn/WaveformView.swift`

**Interfaces (consumes/produces):** keeps signature `WaveformView(level: Double, phase: String)`; palette moves to island tokens; the TimelineView runs only in listening/thinking/acting/speaking (in all other phases the view renders a static flat bar set and starts no timer); listening drives from mic level in islandAccent, speaking from playback level in islandText, per the spec table.

- [ ] Implement; add debug counter hook `WaveformView.tickCount` asserted static in a small XCTest with phase "awaiting_approval".
- [ ] Commit `conn: waveform state-gated and re-palleted for island`.

**Done:** `swift test --filter WaveformTests` green; token guard green.

### Packet I8: Chip row and approve beat [opus, effort high] [ADV]

**Files:**
- Create: `macos/Sources/Conn/IslandChipView.swift`
- Modify: `macos/Sources/Conn/IslandView.swift` (mount point only)

**Interfaces (consumes):** AppState.pendingChip (`Chip` with id/preview), DaemonClient.send. **Produces:** chip row inside the island silhouette (island grows by chipRowHeight, no separate card): amber dot, preview 12.5pt, Deny quiet and Approve prominent buttons on the black palette, open/close on chipOpenDuration with buttons faded in at chipButtonsFadeDelay; approve click gives a 120ms confirm settle before the row closes; waveform flattens while a chip is open (consumes I7's phase gating).

- [ ] Implement; commit `conn: chip row inside the island`.

**Done:** build + token guard green; preview chip state screenshot; adversarial reviewer attacks the approve beat for focus-stealing, mis-click geometry (buttons at least 24pt tall targets), and any path where Return could reach the panel.

### Packet I9: Preview states + screenshot rig [sonnet, effort low]

**Files:**
- Modify: `macos/Sources/Conn/PreviewWindow.swift`, `macos/Sources/Conn/main.swift`

**Interfaces (produces):** `Conn --preview` cycles all nine phases plus toast and chip via on-screen buttons; `Conn --preview --shoot <dir>` renders each state and writes `<dir>/<phase>.png` headlessly, plus a `center-crosshair` overlay toggle for the optical-alignment check.

- [ ] Implement; run `--shoot /tmp/conn-states`, verify 11 PNGs.
- [ ] Commit `conn: preview state cycler and screenshot rig`.

**Done:** 11 PNGs exist and are reviewed at the phase gate.

### STOP 2 (end of Phase 2): Samay reviews the screenshot set and drives the preview cycler. Typography and state vocabulary must feel calm and non-AI before motion work begins.

---

## Phase 3: The morph, personality, playground (signature)

Order: I10 then I11 (same files); I12 parallel with I11 once I10 lands.

### Packet I10: Summon and collapse morph [opus, effort high] [ADV]

**Files:**
- Modify: `macos/Sources/Conn/IslandController.swift`, `macos/Sources/Conn/IslandView.swift`

**Interfaces (consumes):** tokens summonSpring/collapseSpring/contentStaggerDelay/squash*. **Produces:** key-down: island grows out of the notchRect with summonSpring, width leading height by squashWidthLeadMs, overshoot per tokens, content opacity trailing by contentStaggerDelay; collapse mirrors with collapseSpring, content fades first; belay path uses belaySnapDuration for content clear then collapses. The shape morphs from the exact notch rect so the birth reads as the hardware breathing out.

- [ ] Implement; verify by preview replay and live key-down; token guard green.
- [ ] Commit `conn: summon and collapse morph`.

**Done:** guard green; adversarial reviewer scores the morph against the 12-principles skill (squash/stretch, anticipation, follow-through) and the spec's overshoot tokens; Fable taste pass on a screen recording.

Execution record 2026-07-07: the morph substance shipped across two Samay-directed solo rounds rather than a dispatched packet, ahead of I7-I9: `conn: refine notch island` (shape grows from the notch rect with content stagger) and 7361b6c `conn: island personality motion` (width leads height by squashWidthLeadMs, per-axis springs with damping derived from the overshoot tokens, mirrored staggered collapse, panel order-out waits for the trailing spring). Every dismissal path was verified to retract through the morph via frame-level recording analysis. The adversarial 12-principles score and the Fable taste pass on a recording did not run; both fold into STOP 3.

### Packet I11: Personality behaviors [opus, effort high]

**Files:**
- Modify: `macos/Sources/Conn/IslandView.swift`, `macos/Sources/Conn/WaveformView.swift`

**Interfaces (consumes):** tokens aliveness/breath*/exhale*. **Produces:** breath (island height ±breathAmplitude, eased sine, breathPeriod) only while listening; exhale contraction before the done settle; all three behaviors scale with `aliveness` and vanish at 0.

- [ ] Implement; XCTest: aliveness 0 renders identical frames across a simulated 5s (no animation values change).
- [ ] Commit `conn: breath and exhale personality`.

**Done:** test green; STOP 3 judges the feel.

Execution record 2026-07-07 (commit 7361b6c, same round as I10's second half): breath while listening via a TimelineView paused in every other phase, exhale on done entry, all three behaviors scaled by aliveness. Deviations from the packet: the planned identical-frames XCTest became IslandMotionTests (the overshoot-to-damping inversion pinned at aliveness 1 and 0) plus live frame-level recording verification of the 3.2s breath period; WaveformView was left untouched (it remains I7's file, and the interim island waveform already gates its timeline by phase). The spec's whimsy ceiling was renegotiated for summon and retract in the same commit per Samay's directive. STOP 3 judges the feel.

### Packet I12: Tuning playground [sonnet, effort default]

**Files:**
- Create: `macos/Sources/Conn/InspectorView.swift`
- Modify: `macos/Sources/Conn/PreviewWindow.swift`, `macos/Sources/Conn/DesignTokens.swift`

**Interfaces (produces):** DesignTokens becomes a mutable runtime store behind the same static names (`DesignTokens.current` instance, statics forward to it) so the inspector can write live values; inspector lists every motion, personality, and palette token as slider/color-well beside the preview; Replay button re-runs summon+collapse; Write Back button writes a regenerated `DesignTokens.swift` literal block to disk and prints the spec-table diff to stdout for manual paste-back.

- [ ] Implement; verify: move summonSpring response slider, replay reflects it without rebuild; Write Back produces a compilable file matching controls.
- [ ] Commit `conn: tuning playground with write-back`.

**Done:** the write-back file diff round-trips; token guard still green after a write-back.

### STOP 3 (end of Phase 3): tuning sessions. Samay drives the playground and the live hotkey until summon, breath, exhale, chip, and belay feel right. Tuned values written back to DesignTokens.swift AND the spec tables in one commit. The phase does not close until Samay says the morph is award-grade, and the ≤3% overshoot line in the spec is updated if taste moved it.

---

## Phase 4: Senses and context (parallel lanes)

### Packet S1: Sound candidates [sonnet, effort default]

**Files:**
- Create: `scripts/make_sounds.py`, `macos/Sources/Conn/SoundPlayer.swift`, `sounds/` (candidate output, gitignored except chosen set)
- Modify: `macos/Sources/Conn/AppDelegate.swift` (wire cues), `config.toml` (`[sound] enabled = true`), `src/conn/config.py`

**Interfaces (produces):** four cue names `engage, commit, approve, belay` played by the Swift app (never the daemon) on the matching state transitions; `sound.enabled=false` silences all; `scripts/make_sounds.py` synthesizes three candidate families x four cues as .caf (DSP: filtered noise bursts, wooden-tap impulse convolution, soft-attack envelopes per the spec character bar: warm, organic, ≤ -20dBFS peak, lengths per spec table).

- [ ] Implement generator and player; verify lengths and peaks programmatically (`scripts/make_sounds.py --verify` asserts duration and peak per cue).
- [ ] Commit `conn: sound player and three candidate families`.

**Done:** verify pass; STOP 4: audition with Samay, one family chosen or all rejected with notes; chosen set committed, losers deleted, idea-ledger updated if rejected outright.

### Packet S2: AX via app [sonnet, effort default] [ADV]

**Files:**
- Create: `macos/Sources/Conn/ContextReader.swift`
- Modify: `macos/Sources/Conn/DaemonClient.swift`, `src/conn/app.py`, `src/conn/tools/mac.py`, `src/conn/server/http.py`
- Test: `tests/test_context_via_app.py` (new)

**Interfaces (produces):** daemon-to-client WS request `{"type":"context_request","id":...}`; client replies `{"type":"context_response","id":...,"app":...,"bundle_id":...,"window_title":...,"selected_text":...,"accessibility":"granted"}` read via AX from the Swift process (which holds the grant); `get_context` executor awaits the app response with a 1.5s timeout, falls back to the current python path when no app client is connected; python AX code and its grant requirement retired from the primary path.

- [ ] Failing tests with a fake client: tool result carries the app-provided selection; timeout falls back cleanly.
- [ ] Implement both sides; commit `conn: context reads through the app grant`.

**Done:** tests green; manual: with zero grants on the python binary, "copy this selection" round-trips real selected text (closes the live-eval task 4 gap).

### Packet S3: Frontmost filtering [haiku, effort low]

**Files:**
- Modify: `src/conn/tools/mac.py`, `macos/Sources/Conn/ContextReader.swift`
- Test: `tests/test_frontmost_filter.py` (new)

**Interfaces:** both context paths resolve the frontmost app among `.regular` activation-policy apps only (the Kaku miss); python fallback filters `NSWorkspace.runningApplications` accordingly.

- [ ] Failing test with mocked app list (agent app frontmost, regular app behind it → regular app returned); implement; commit `conn: frontmost resolves regular apps only`.

**Done:** test green.

---

## Phase 5: Proof

### Packet V1: Eval and checklist upgrades [sonnet, effort low]

**Files:**
- Modify: `docs/LIVE_EVAL_CHECKLIST.md`, `evals/tasks.json`, `src/conn/evals.py`

**Interfaces:** checklist gains per-task latency columns fed from the receipt latency block, plus three reliability drills (wifi-kill mid-turn, PTT-in-thinking pulse, zombie-adopt relaunch); eval suite asserts reject_input and phase_change kinds in demo runs.

- [ ] Implement; commit `conn: checklist v2 with latency columns and reliability drills`.

**Done:** `--eval` green; checklist file updated and slopchecked.

### STOP 5: full live-eval run, Samay driving, all nine tasks plus the three drills, fresh session per block of three, receipts and latency report read together. Budgets breached here spawn optimization packets before the project closes.

### Packet V2: Ledger close-out [Fable]

Final ledger entry: output tokens by tier from the jq pass, gate results, counterfactual estimate, Fable share against the 20 percent bar, and Samay's verdict. The project is done when the checklist verdicts, the budgets, and the taste call all hold.

---

## Self-review notes

Spec coverage checked section by section: geometry (I2), palette (I1/I6), states (I6/I7/I8), personality (I11), motion policy and table (I10/I11 under the I1 guard), playground (I12), latency budgets and instrumentation (P0-A/D/E, I4), typography (I6 under the I1 guard), sound (S1), reliability defects 1 through 8 (P0-B: 1-2, P0-C: 6-7, P0-D: 3-4 daemon side, 8; R4: 4 client side, 5), AX migration (S2), frontmost filter (S3), build health (R4), console freeze (no packet, by design; panel toast line in I5), idea ledger (no packet; V2 confirms currency). Type names cross-checked: IslandGeometry API consistent between I2/I3, DesignTokens names consistent across I1/I6/I10/I11/I12, trace kinds consistent across P0-A/P0-D/P0-E/I4.
