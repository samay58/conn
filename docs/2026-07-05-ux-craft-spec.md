# Conn UX craft spec

Companion to [gpt-realtime-2-computer-agent-spec.md](gpt-realtime-2-computer-agent-spec.md), written 2026-07-05 after the Phase 1 teardown, a live test drive, and the scoping session. The shipped spec stands except where this document explicitly renegotiates it. Safety invariants are untouched: the model proposes and the harness disposes, continuations are withheld until tool results are real, the budget cap is a hard stop. This spec adds a third invariant and a craft layer with numbers.

Every line here is verifiable: a latency number a trace can compute, an enumerated state, a motion value in a tokens table, or a screenshot-checkable rule. Values marked "tuned" start at the stated number, get adjusted by hand against `Conn --preview` and the live app, and the final value is written back into this file. The table is the source of truth; code constants that drift from it are a defect.

## Decisions of record, 2026-07-05

- The notch island is Conn's primary surface on the built-in display. The floating panel survives only as the fallback for non-notch displays, visually frozen except for reliability fixes.
- The island is black in every state. This is a deliberate, scoped exception to the light-surfaces doctrine, approved by Samay 2026-07-05: the notch is black hardware and a biomimetic extension of it cannot be white. Console, preview chrome, and every other Conn surface stay light.
- Nothing is on screen at idle. Key-down summons the island out of the notch; collapse returns the screen to untouched. No ambient presence, no idle animation loop, no battery cost.
- Approvals remain pointer-only. The panel-never-takes-keyboard-focus rule (born from the stray-Return incident) was deliberately reconsidered and reaffirmed. Keyboard approval and voice approval were both rejected: keyboard reintroduces the incident class, voice puts speech recognition on the approval path.
- The web console is frozen as the engineer's debug surface. Its two load-bearing exclusives, budget override and toast display, migrate to the island. Typed input stays console-only this round.
- Speed is a core lane, not a guard rail. Samay's framing, 2026-07-05: developing a new interaction medium makes speed critical. Budgets below are product targets; instrumentation lands first, and any measured breach spawns an optimization packet.
- Signature moment: the summon morph. The listening state, the approve beat, and the belay stop are also fully invested; the morph is first among them.
- Personality is motion, not a mascot. The island is alive through physics (squash-and-stretch, breath, exhale) with no face in this round. The personality parameters form a skeleton a future character could mount without rework; "cute character" is logged in the idea ledger with that trigger.
- No monospace faces anywhere on the island. Numerals align through tabular figures in the text face, not through a coding mono. Calm and whimsical, zero AI-tool aesthetic in the notch.
- Sounds are custom and warm: ASMR-adjacent, organic textures, soft attacks. Stock or system sounds are disqualified.
- A tuning playground gets built so spec values are adjusted live against the real animation and written back, instead of rebuild-and-guess.
- North star, recorded for scope honesty: Conn is meant to become a general, flexible computer tool. This round builds the surface, the speed discipline, and the reliability spine that generality rides on; capability breadth itself stays out of this round.
- Rejected and deferred ideas are logged with revisit triggers in [idea-ledger.md](idea-ledger.md), never silently dropped.

## Renegotiations of the shipped spec

Three lines of the shipped spec are superseded:

1. "Motion is limited to state changes" becomes the motion policy below: continuous motion is allowed only inside the waveform and only while a session is in an active phase. The island's shape moves only on state change. At idle nothing exists, so the question dissolves.
2. "Radii at 7 to 10px" applied to the floating card. The island's geometry is its own system (below); the frozen fallback panel keeps its current 12px chrome rather than churning a demoted surface.
3. The 140ms chip rise was never implemented (shipped code runs 180ms). The motion table below sets the value and the preview verifies it.

## The island

### Geometry

Island geometry derives from the notch at runtime, never from hardcoded pixels. Source: `NSScreen.safeAreaInsets` and the auxiliary top areas give the notch rect (width between `auxiliaryTopLeftArea` and `auxiliaryTopRightArea`, height = top safe-area inset). Acceptance: a unit-testable `IslandGeometry` type computes collapsed and expanded frames from a mocked screen; on non-notch screens it returns nil and the fallback panel is used.

Built-in-display fallback (2026-07-06): some notched built-in displays report `safeAreaInsets.top = 0` with nil auxiliary areas, so AppKit yields no notch rect even though a physical notch exists. `IslandGeometry.syntheticBuiltIn` then synthesizes a centered notch rect (width 200pt, height = the measured menu-bar inset `screen.frame.maxY - screen.visibleFrame.maxY`, clamped to 24...40, fallback 32) for `localizedName` containing "built-in". This keeps the island on the primary surface rather than dropping to the center panel; true external non-notch displays still return nil.

States, one continuous shape throughout:

| State | Shape | Acceptance |
|---|---|---|
| Idle | Nothing. Zero windows on screen. | Screenshot of idle desktop shows no Conn window; `CGWindowListCopyWindowInfo` shows no Conn island window |
| Summoned (listening, thinking, acting, speaking) | Notch rect grown 58pt wider each side (`islandGrowWidth`) with a 60pt content lane below the notch (`islandContentHeight`). Top edge flush to the screen edge and top corners square so it continues the notch hardware; bottom corners continuous 13pt (`islandCornerRadius`). All readable content lives in the lane below the notch and never draws into the notch depth. | `Conn --preview` state renders; hand test against real notch; live screenshot shows no clip |
| Chip open (awaiting approval) | Summoned shape plus a chip row extending 40pt below (`chipRowHeight`), same silhouette, no separate card | Preview render; chip is inside the island outline, screenshot-checkable |
| Budget hold / failed | Summoned shape, no growth, red-family treatment (palette below) with the override affordance on budget hold | Preview render |

The island is an `NSPanel` with `styleMask [.borderless, .nonactivatingPanel]`, level above the menu bar, exactly like the shipped panel. Acceptance: a unit test asserts the style mask; the manual gate is typing in another app while the island is up and observing zero keystroke loss, including while a chip is showing.

### Palette on black

True black `#000000` background matching the notch glass. Content colors, starting values, tuned:

| Token | Value | Use |
|---|---|---|
| island.bg | #000000 | Every state |
| island.text | white 0.92 | Transcript, chip preview |
| island.textSecondary | white 0.58 | State word, cost line |
| island.accent | #7BA7E0 | Listening ring, waveform when listening |
| island.amber | #E8A13D | Approval dot, chip accent |
| island.green | #4CC38A | Done settle |
| island.red | #E05252 | Failed, budget hold |

The shipped light palette (`ink`, `accent #2E59A8`-family) is unchanged for the fallback panel and console. Contrast acceptance: every text token on island.bg passes 4.5:1 (the values above all clear it; re-verify after tuning).

### State vocabulary inside the island

All nine machine phases get a distinct, enumerated treatment. No two phases may render identically (the shipped panel's thinking/acting collision is a defect this fixes).

| Phase | Island treatment |
|---|---|
| idle | Nothing on screen |
| listening | Waveform live at mic level in island.accent; 1pt accent ring strokes the island perimeter |
| thinking | Waveform low-amplitude breath in textSecondary; no ring |
| acting | Thinking treatment plus the running tool's name in SF Pro Text 10.5pt medium (island.textSecondary) under the waveform |
| awaiting_approval | Chip row open: amber dot, action preview, Deny and Approve buttons; waveform paused flat |
| speaking | Waveform live at playback level in island.text; no ring |
| done | Waveform settles flat, green tick replaces state word, 320ms settle, collapse begins at +900ms |
| failed (reconnecting) | State word "Reconnecting" in island.red, waveform flat; auto-collapse at +2.5s |
| budget_hold | "$ cap reached" in island.red plus an "Override once" click target; stays until acted on |

Toasts from the daemon render as a single line replacing the state word for 3s (this closes the native toast gap). Acceptance: `Conn --preview` renders every row of this table; a screenshot set is captured per state and reviewed at the phase gate; the previewed states enumerate all nine phases plus toast.

### Personality

The island is a living thing rendered entirely through physics. Three behaviors, all parameterized in the tokens file and all tunable in the playground:

| Behavior | Starting values (tuned) | Character intent |
|---|---|---|
| Squash and stretch on summon | Width leads height by 40ms; height overshoots 4%, width 2% | The island has mass; it arrives, it does not fade in |
| Breath while listening | Height oscillates ±1.5%, period 3.2s, eased sine | Quiet pulsing: attentive, calm, alive |
| Exhale on done | One 220ms contraction of 2% before the green settle | Release of attention; the turn is over |

Rules: calm is the default register. On the summon and retract beats the whimsy ceiling is raised from subtle to delightful and alive (Samay's directive, 2026-07-07); every frequent in-session transition stays immediate and every other beat stays subtle. The island shape moves only on state change, breath, or exhale; nothing anthropomorphic in this round. The three behaviors share a single aliveness scalar in the tokens file (0 disables all three), which is the mount point for any future character. Acceptance: playground sliders drive all parameters live; aliveness 0 renders a fully static island; the hand gate is Samay holding the key and judging calm versus fidget.

## Motion

Motion policy: the island's shape and content move only on state change, breath, or exhale (the personality table above). The waveform animates continuously but only in listening, thinking, acting, and speaking, driven by the existing 60fps TimelineView; at every other phase no animation timer runs. Acceptance: instruments or a debug counter shows zero timeline ticks while a chip is open and after collapse.

| Motion | Value (tuned) | Notes |
|---|---|---|
| Summon morph | spring(response 0.28, dampingFraction 0.80), content opacity staggered +80ms behind shape | Overshoot allowed, ≤3% of final width; the biomimetic beat |
| Collapse | spring(response 0.22, dampingFraction 0.90) | Faster and more damped than summon; exits should feel certain |
| Chip open/close | 160ms easeOut on shape growth, buttons fade +60ms | Replaces the unimplemented 140ms and shipped 180ms |
| State word crossfade | 120ms easeInOut | |
| Done settle | 320ms green tick fade-in, collapse at +900ms | |
| Refusal pulse | 2px horizontal shake, 3 cycles, 250ms total | Fires when PTT is pressed in a phase that cannot accept it |
| Belay snap | Island content clears in 120ms, collapse follows | Paired with the audio budget below |

Curves are named here and nowhere else: every duration and spring in Swift lives in one `DesignTokens.swift`, and a test greps the Sources tree to assert no numeric literal appears inside a `.animation(` or `withAnimation(` call outside that file.

## The tuning playground

Spec values become right by being felt, so the loop cannot be edit-rebuild-guess. `Conn --preview` grows an inspector: every `DesignTokens.swift` value (springs, durations, palette, personality parameters) rendered as a live control beside the previewed island, a state cycler, and a morph replay button that re-runs summon and collapse with the current values. A write-back action emits the updated tokens file so the tuned numbers land in code and get copied back into this spec's tables in the same commit.

Acceptance: moving the summon-response slider and pressing replay shows the new spring without a rebuild; write-back produces a `DesignTokens.swift` whose values match the on-screen controls; the tokens file stays the only place animation numbers exist. The tuning sessions themselves are the hand gates named throughout this spec.

## Latency budgets

Speed is the medium: a voice surface that hesitates teaches you to stop reaching for it, so these six budgets are product targets, not alerting thresholds. The instrumentation ships before any craft packet that could regress it, every budget is verified from real traces, and a measured breach spawns an optimization packet in the plan rather than a note.

| Moment | Budget | Trace span |
|---|---|---|
| Key-down to island visible with listening treatment | ≤100ms | client `ptt_down.client_ts` to client `ui_ack(listening)` |
| Key-release to first visual acknowledgment (thinking) | ≤90ms | `ptt_up.client_ts` to `ui_ack(thinking)` |
| Key-release to first model token (text or audio delta) | ≤900ms p50, ≤1500ms p95 | `ptt_up` to first `model_delta` trace event |
| Key-release to first tool execution, tool turns | ≤1200ms p50 | `ptt_up` to `tool_exec` |
| Tool proposal to chip visible | ≤120ms | `tool_proposed` to `ui_ack(chip)` |
| Belay to silence | ≤150ms to audio flush confirmed, ≤400ms to session end | `kill_switch` to `audio_silent` |

Instrumentation this requires (all currently missing, per the Phase 1 latency teardown):

- Clients stamp a monotonic `client_ts` on every `ptt_down`, `ptt_up`, `approval`, and `stop` WebSocket message; the daemon records a clock-offset handshake at connect so spans mix client and daemon timestamps safely.
- The daemon trace gains event kinds: `ptt_down`, `ptt_up`, `phase_change` (every transition, old and new phase), `model_delta` (first per response only), `audio_silent` (emitted by the playback callback when the buffer empties after a flush).
- The Swift app reports `ui_ack` over the WebSocket after the render pass that first shows a state (CADisplayLink or `CATransaction` completion), sampled on the moments above only.
- A `latency` section lands in the receipt: computed spans for the six moments, per turn.

Acceptance: `python -m conn --eval` gains cases asserting the new trace kinds exist and spans compute; a report command (plan decides its home) prints the six spans from any real session trace; the live checklist gains a column reading them from the receipt instead of a stopwatch.

## Typography

The tracked-uppercase 9.5pt label style is retired everywhere; it was the loudest AI tell in the shipped panel. Second rule, from Samay directly: no monospace faces anywhere on the island. Coding monos read as developer-tool aesthetic, the opposite of calm and whimsical. Numeral alignment comes from tabular figures inside the text face (`.monospacedDigit()` on SF Pro gives lining tabular digits without a mono font), which keeps the cost meter stable while it counts.

The taste position: at 10 to 13 points, white on black, in a shape this small, high taste is restraint. One family, SF Pro, set with native optical sizing; personality lives in the motion and the sounds, not in a novelty face. If the island ever grows a surface large enough to want a voice of its own, the candidates are the house-approved humanist sans set, never a mono.

| Role | Face and size | Rules |
|---|---|---|
| Transcript / model line | SF Pro Text 13pt regular, island.text | 2-line max, center, no italics |
| User line | SF Pro Text 13pt medium, island.textSecondary | |
| State word | SF Pro Text 11pt medium, sentence case ("Listening", not "LISTENING"), tracking 0 | |
| Cost figure | SF Pro Text 10.5pt medium, `.monospacedDigit()`, island.textSecondary | `.contentTransition(.numericText())` stays |
| Tool name (acting) | SF Pro Text 10.5pt medium, island.textSecondary | |
| Chip preview | SF Pro Text 12.5pt medium | |
| Chip buttons | SF Pro Text 12pt medium | |

Baseline spacing inside the island snaps to a 4pt grid. The waveform centers on the notch center, which is the camera center, which is the screen center: optical alignment is free if the geometry math is honest, and a preview overlay (crosshair at screen center) makes it screenshot-checkable. Trace and receipt rendering live on the frozen console and are untouched. Acceptance: preview screenshots per state; a test asserts island Sources contain no `.tracking(` call, no `.uppercased()` on state labels, no `design: .monospaced`, and no mono font name; the cost text carries `.monospacedDigit()`.

## Sound

Four sounds, all optional via config, all silent when the system output is muted, peaks at or below -20dBFS. Character bar, from Samay: warm and elegant, ASMR-adjacent. Organic source textures (felt, wood, breath, fingertip on paper), soft attacks, no ring-out. Stock UI packs, system sounds, and synth beeps are disqualified; the four cues are designed or recorded for Conn specifically and must sound like one family:

| Cue | Character | Length |
|---|---|---|
| Engage (key-down) | Dry tick, barely there | ≤40ms |
| Commit (key-release) | Slightly softer tick, downward | ≤40ms |
| Approve | Two-note settle | ≤180ms |
| Belay | Damped thunk, no ring-out | ≤120ms |

Denial, refusal, and done are silent; the visual carries them. Files ship as `.caf` in the app bundle, played through the daemon's output device via the app (not the Python daemon), so they mix with model speech without a second device claim. Acceptance: files exist, an audition stop point with Samay approves or replaces each one before the lane closes, and a config flag `sound.enabled = false` verifiably silences all four.

## Reliability: the loop never lies about being alive

Third invariant, earned by the 2026-07-05 wedge (a daemon sat in `thinking` for two days, healthz said ok, the app adopted it, and PTT died silently). Statement: any death of the transport, the upstream session, or the daemon becomes user-visible state within one second, and no surface reports health it has not verified.

Defect ledger, all verified with file:line during the wedge investigation:

| # | Defect | Fix direction | Acceptance |
|---|---|---|---|
| 1 | Clean upstream close ends the event iterator silently, no `RtClosed` (`openai_ws.py:117-129`) | Yield `RtClosed` when the iterator exits without exception and `_closing` is false | pytest: fake ws that closes cleanly produces a `failed` transition |
| 2 | `connected` is `_ws is not None`, never invalidated on clean close (`openai_ws.py:36`) | Null `_ws` on every exit path from `events()` | pytest asserts `connected` false after clean close |
| 3 | Send failures during `CommitInput`/`CreateResponse` leave phase THINKING (`app.py` exec path) | Wrap adapter sends; on failure dispatch the disconnect path | pytest: send raising mid-turn lands in `failed`, not `thinking` |
| 4 | `healthz` reports ok unconditionally (`http.py:69-74`); launcher adopts any 200 (`DaemonLauncher.swift:11-13`) | healthz adds `phase_age_s` and `upstream_connected`; launcher adopts only if idle-and-healthy or phase_age under 120s, otherwise terminates the zombie and spawns fresh | pytest for healthz fields; manual gate: wedge a daemon, relaunch app, fresh session |
| 5 | App-launched daemon stderr goes to /dev/null (`DaemonLauncher.swift:20-30`) | Pipe stdout/stderr to `data/logs/daemon-YYYY-MM-DD.log`, kept 7 days | Log file exists after app launch; the wedge tracebacks of 2026-07-05 would have been captured |
| 6 | PTT in a non-accepting phase is silently swallowed (`state.py:142-152`) | Machine emits a `RejectedInput` effect; island plays the refusal pulse | pytest for the effect; preview renders the pulse |
| 7 | Idle watchdog only fires from IDLE (`app.py:310-314`) | Any-phase watchdog: no phase change and no pending call for 10 minutes forces the failed path | pytest with a frozen clock |
| 8 | Receipts lost unless the session ends cleanly (Jul 3 session: $0.065, no receipt) | Write the receipt file incrementally at every `response_done`, finalize on end | pytest kills the session mid-turn; receipt exists |

Two additions from the same investigation, in scope for this lane:

- AX context reads move into the Swift app. The app already holds the Accessibility grant (hotkey works); the Python daemon's separate TCC identity is why `selected_text` came back null today. The daemon asks the app over the WebSocket (`get_context` request/response), the app answers from its granted process, and the python-side AX path plus its interpreter-wide grant requirement are deleted. Fallback when the app is absent (console-only sessions): current degraded behavior. Acceptance: with zero grants on the python binary, "copy this selection" round-trips real selected text through the app path.
- Frontmost-app resolution filters to `.regular` activation-policy apps (today it answered "Kaku", an agent app, and was wrong to the user). Acceptance: pytest with a mocked workspace list.

Onboarding this round is the surfacing subset only: the daemon log file (#5), zombie-adoption policy (#4), and island-visible failure states (state table above). The guided first-run flow stays out.

## Build health

`make-app.sh` fails on the current Command Line Tools (SwiftPM manifest link error after a toolchain update); the working build uses `DEVELOPER_DIR=/Applications/Xcode-beta.app/Contents/Developer`. The script gains a toolchain probe: try `swift build --version` first, fall back to the Xcode-beta developer dir, fail loudly with the fix line if neither works. Acceptance: `./make-app.sh` succeeds from a clean checkout on this machine without manual env vars.

## Out of scope, reaffirmed or newly rejected

Unchanged from the shipped spec: arbitrary UI control, screenshot-to-model input, `conversation.item.truncate` barge-in precision, MCP adapters, the Phoenix write lane, shell execution. Newly rejected this round: voice approval (speech on the approval path), keyboard approval (the incident class), persistent idle island, console visual parity, native typed input, the full onboarding flow. Every rejection and deferral above is logged with its reason and a revisit trigger in [idea-ledger.md](idea-ledger.md); out of scope means not now, not lost.

## Gates for the execution plan

Every packet built from this spec inherits: pytest cases named in its done-definition, `Conn --preview` screenshots for visual packets, the no-magic-numbers token test for motion work, and a manual hands-on-the-hotkey stop point before any phase that changes the felt loop closes. The live-eval checklist gets rerun in full against the island build with the new latency columns before the project calls itself done.
