# Conn: state of play

Written 2026-07-06. A single "where we are" document for Conn, separate from the
design specs (intent) and the orchestration ledger (token accounting and gate
results). Read this first to reload the project; then go to the specs for the
why and the plan for the packet-by-packet how.

## What Conn is, in one paragraph

Conn is a push-to-talk voice command surface for the Mac, built on the OpenAI
Realtime API (gpt-realtime-2). You hold a key, say a command, release. Conn
understands the target, takes the smallest safe action through a local tool
harness, shows an approval chip for anything risky, and leaves a trace and a
cost receipt for every session. No always-on mic, no ambient screen watching,
no chatbot. The name is the naval handoff of steering authority: "you have the
conn" is spoken, bounded, revocable command. Push-to-talk is taking the conn;
the stop button is "belay that."

## Why it exists (the product thesis)

Voice is worth using only where it beats the keyboard. Conn bets on three spots
first: app switching while your hands are mid-task, vault search without
breaking focus, and read-back of current context. The safety model is the whole
point: the model proposes, the harness disposes. Low-risk actions run at once;
risky actions wait behind a crisp approval chip stating exactly what will
happen; disabled actions return structured refusals so the model learns the
boundary. Every session is traced and priced, so you can prove where voice
actually beat the keyboard rather than demo it once.

The north star, recorded for scope honesty: Conn is meant to become a general,
flexible computer tool. The current rounds build the surface, the speed
discipline, and the reliability spine that generality will ride on. Capability
breadth (arbitrary UI control, per-app profiles, a write lane into Phoenix)
stays deliberately out until traces show the need.

## The three hard safety invariants

These are never traded away, in any packet:

1. **The harness owns permissions; the model only proposes.** Risk levels map
   to gates: `read` and `act_low` run immediately, `act_confirm` shows a chip
   and waits (30s then denied), `blocked` returns a structured refusal. Config
   can escalate any tool but can never unblock a v0-disabled tool.
2. **Continuations are withheld until tool results are real.** The model cannot
   speak about a tool outcome until the daemon sends the function result and
   issues the next `response.create`. A pending-call ledger enforces
   all-calls-resolved-before-continuation. This is the anti-hallucination
   invariant: there is no window where the model can claim something happened
   before it did.
3. **The budget cap is a hard stop.** `response.create` is the only spend
   trigger and the daemon owns every one, so the budget gate is one function in
   one place. Default $1.00/session hard cap, warn at $0.50.

Two more rules earned from incidents: **approvals are pointer-only** (a stray
Return keystroke once silently approved a real action, so the panel/island
never takes keyboard focus), and as of the July 5 round, **the loop never lies
about being alive** (any death of the transport, upstream session, or daemon
becomes user-visible state within one second, and no surface reports health it
has not verified).

## Architecture

One Python daemon owns everything; thin views render it.

- **The daemon** (Phoenix `.venv`, single asyncio loop) holds the WebSocket to
  OpenAI, the API key, PTT-gated mic capture, audio playback, the tool harness,
  approvals, traces, and the cost meter. A native process owning raw audio is
  the documented WebSocket case, so there is no ephemeral-token dance and no
  client that could leak the key. Sideband by construction.
- **The web console** (vanilla HTML/CSS/JS at 127.0.0.1:8787) is a pure view
  and approval surface. It never talks to OpenAI. It is now frozen as the
  engineer's debug surface.
- **The native macOS app** (`macos/`, SwiftUI + AppKit menu-bar app) is the
  primary surface. It speaks the daemon's WebSocket protocol, autolaunches the
  daemon if none is running, owns the Right Option hold-to-talk through its own
  Accessibility grant, and installs to /Applications via `make-app.sh install`.
- **Push-to-talk is dual**: hold Space in the console (zero TCC grants, always
  works) or hold Right Option globally via the app's hotkey. Console PTT is the
  foundation; the global hotkey is the upgrade.
- **Typed input is a peer of voice**, not scaffolding: the same conversation-
  item path drives live sessions, giving a free degraded mode when audio breaks.
- **Demo mode swaps one adapter**: a scripted fake plays scenario files through
  the identical machine, harness, trace, and cost paths, with zero credentials
  and (with `--simulate-tools`) zero side effects.

### The state machine

Nine phases: idle, listening, thinking, acting, awaiting_approval, speaking,
done, failed, budget_hold. The machine is pure (no I/O) and exhaustively tested,
including barge-in, sub-300ms tap abort (zero spend), denial and timeout paths,
budget hold, reconnect, reject-input, and any-phase watchdog.

### Tool contract (v0 surface)

Executable now: `computer_get_context` (frontmost app, window title, selected
text via AX), `computer_screenshot` (local, deleted at session end),
`app_open`/`app_switch` (allowlisted), `browser_search`, `phoenix_search` (qmd
BM25), `phoenix_open_note` (obsidian:// URL, must resolve inside the vault),
`clipboard_set`, `wait_for_user`.

Specced and **blocked** in v0, schemas exported so the refusal path teaches the
model: `computer_click`, `computer_type_text`, `computer_hotkey`,
`computer_ax_tree`. These are the road to the general-tool north star and need
per-app profiles with named, validated targets before they open. Zero
`osascript` anywhere means zero Automation prompts. The shell allowlist ships
empty.

## Where the code lives (standalone as of 2026-07-07)

- **Standalone repo:** `~/conn`, its own git repository with its own `.venv`,
  published at `github.com/samay58/conn`. Extracted from a private personal
  monorepo on 2026-07-07 (the idea-ledger next step, executed); history starts
  fresh at the extraction. Earlier development history stays in the private
  monorepo, where a symlink at the old path keeps internal references working.
- **Earlier mirror:** an earlier `samay58/conn` was published by `git subtree
  push` from the monorepo and was retired on 2026-07-07; this repo replaces it
  with a clean, self-contained history. Never reuse the retired mirror's
  history.

## What has been built

### v0, shipped 2026-07-02

The full daemon spine, harness, adapters, audio, hotkey, console, demo mode,
cost model, receipts, traces, six harness evals, and the native menu-bar app
with a floating voice panel, all in one day. Design captured in
`docs/gpt-realtime-2-computer-agent-spec.md`. This is the reference the later
rounds renegotiate from, not replace.

### The July 5 UX-craft round (specs + Phases 0 and 1 executed)

After a live test drive surfaced a two-day daemon wedge (stuck in `thinking`,
healthz lying, PTT dead silently), the project opened a craft-and-reliability
round. Two design docs govern it:

- `docs/2026-07-05-ux-craft-spec.md`: the notch island becomes the primary
  surface on the built-in display; the panel is demoted to non-notch fallback.
  Every value is verifiable (a latency number a trace computes, an enumerated
  state, a motion token, or a screenshot-checkable rule). Adds the reliability
  invariant and a defect ledger of 8 verified `file:line` defects.
- `docs/plans/2026-07-05-ux-craft-plan.md`: 19 packets across 6 phases, each
  dispatched to a model tier, TDD-enforced, with mechanical + adversarial +
  taste gates at every phase boundary.

**Phase 0 (measure and stop lying, daemon) is complete.** Trace schema v2 with
client timestamps, upstream-close honesty, state-machine effects (reject-input,
any-phase watchdog), reliability wiring (healthz staleness fields, incremental
receipts, send-failure disconnect path), latency spans and `--latency-report`,
plus the launcher log file / zombie-adoption policy / toolchain probe. All 8
reliability defects from the ledger addressed on the daemon side. Adversarial
review caught a watchdog false-positive and non-atomic receipt writes, both
remediated.

**Phase 1 (island structure, Swift) is complete.** DesignTokens.swift plus a
magic-number guard test, IslandGeometry derived from notch metrics (unit-tested,
returns nil on non-notch screens), the IslandController nonactivating shell,
client timing acks, and surface routing (island on notch displays, panel
elsewhere, `CONN_FORCE_PANEL=1` forces the old panel). Adversarial review caught
an invisible-island cgcolor bug (`Color.cgColor` is Optional and could no-op to
black on a transparent panel), fixed inline.

### The July 5 cleanup pass (C1 to C4, executed same evening)

A narrow tightening pass before Phase 2, governed by
`docs/2026-07-05-cleanup-execution-spec.md` and its adversarial review:

- **C1:** a `ConnSurface` protocol; `AppDelegate` picks one `primarySurface` at
  launch; the fallback panel is constructed lazily only when its debug action is
  used or no island geometry exists. Removes the extra live surface on the
  island path.
- **C2:** `Conn --preview` rewritten around the island, not the old panel, so
  the tuning loop optimizes the right surface.
- **C3:** a daemon-launch path resolver (env override, then the known Phoenix
  path, then clear failure) so a second machine no longer requires editing
  source.
- **C4:** the `events.py` boundary named (wire/protocol dataclasses only; no
  behavior, timers, or policy) with a drift-visibility test.

The app is installed to /Applications with the brass speaking-trumpet icon
(Samay's pick) and pinned to the Dock.

## Current state (as of 2026-07-07, post stock-take)

- **Tests: 260 Python + 26 Swift** (`ConnTests`, including the geometry,
  island-motion, panel-focus, waveform-tick, and token-writeback suites);
  design-token guard and demo evals 12/12 green.
- **Phases 0 and 1: done and gate-green.** Cleanup C1 to C4: done.
- **Phase 2 is complete, including the STOP 2 refinements.** Packet I6
  (IslandView rendering all nine phases plus toast, budget-hold override,
  and refusal pulse) landed 2026-07-06. The remainder landed 2026-07-07: I7
  promoted the state-gated island waveform into WaveformView.swift under
  the token guard, I8 put the interactive approve/deny chip inside the
  island silhouette (pointer-only, the approve click sends after a 120ms
  confirm settle so the daemon phase change never clips the
  acknowledgment), and I9 retargeted PreviewWindow at the canonical
  IslandView and added the `--shoot` screenshot rig. STOP 2 ran 2026-07-07:
  pass, with four refinements ordered; all four landed the same day in
  commit `91b1460` (lilac signature accent with the thinking ellipsis
  beat, the acting tool capsule with humanized labels, chip previews
  budgeted daemon-side to fit whole, and the gold budget-hold identity
  with a real Override once outline button).
- **Packet I12 (tuning playground) landed 2026-07-07.** DesignTokens is a
  runtime store behind the same static names; the preview grew an
  inspector with every raw motion, personality, and palette token as a
  live control, derived values read-only, and Write Back regenerating
  DesignTokens.swift from a template plus a spec-table diff on stdout. A
  round-trip test pins the template to the file on disk byte for byte.
- **Notch-island refine (2026-07-07):** the built-in-display island was
  repaired from an oversized clipped pill to a notch-flush surface, synthetic
  geometry adopts the measured menu-bar inset, and summon gained a restrained
  breathe-open. Verified live; commit `conn: refine notch island`.
- **Island personality motion (2026-07-07, commit 7361b6c):** the substance
  of Phase 3 packets I10 and I11, executed ahead of I7-I9 by Samay's
  directive. Squash-and-stretch summon (width leads height by 40ms, per-axis
  spring damping derived from the 2% and 4% overshoot tokens), breath while
  listening (plus or minus 1.5%, 3.2s, TimelineView paused in every other
  phase), exhale on done, and a mirrored staggered retract on every
  dismissal path; all scaled by `aliveness` (0 renders fully static,
  verified both ways). The spec's whimsy ceiling was renegotiated for the
  summon and retract beats in the same commit. Verified live with
  frame-level analysis of a screen recording; Samay's hand-on-hotkey
  judgment is the open taste gate.
- **Standalone repo published** (see "Where the code lives"); the old subtree
  mirror is retired and replaced by this repo's clean history.

### Open items

- **STOP 1 (Phase 0 hands-on reliability drill): done 2026-07-07 with
  findings.** Samay drove real commands live. Verdict: latency and
  snappiness strong, clipboard lane worked. Findings, all fixed same day
  in `14d1d83`: phoenix_search dead under the app-spawned daemon's minimal
  PATH (qmd/node resolution), frontmost gate falsely refusing apps outside
  the alias map ("Terminal not frontmost"), bare `--latency-report`
  rejecting its own drill instruction. Residue: the wifi-kill and
  PTT-during-thinking steps of the scripted drill were not explicitly
  exercised; fold into the next live session rather than a dedicated redo.
- **STOP-G (capability round taste review): pending.** Gate G mechanical and
  adversarial checks are green; the Fable taste review of
  docs/2026-07-06-gate-g-fable-brief.md has not run. Per the ledger, X1, the
  M packets, and P1 stay blocked behind it.
- **Personality hand gate: pending.** Samay drives the hotkey and judges
  cute versus fidget; `aliveness` and the overshoot tokens are the knobs.
- **STOP 2 (Phase 2 screenshot review): done 2026-07-07, pass with four
  refinements; refinements landed same day (`91b1460`).** Samay reviewed
  the 11-PNG set and drove the cycler. The summon animation sets the bar
  ("absolutely gorgeous"); typography and state vocabulary pass. The four
  ordered changes (lilac signature accent with a distinct thinking
  treatment, humanized tool capsule, whole-phrase chip previews, gold
  budget-hold identity with a real Override once button) shipped with the
  gates plus a fresh screenshot set as the verification, per the no
  re-review decision.
- **P0 reliability round (the frontmost spine): fixes landed 2026-07-08,
  live verification pending.** The 2026-07-07 live drive registered four
  bugs; all four are fixed and committed, with the discriminating test
  run first per the contract. Root cause of the shared three:
  NSWorkspace.frontmostApplication() is KVO-cached and never updates in
  a daemon whose main thread never pumps a runloop, so every read served
  the spawn-time app (Kaku) forever. Fixes: a per-call fresh frontmost
  source from the window server with the S3 activation-policy filter
  (tools/frontmost.py, both call sites); context reads routed through
  the app's Accessibility grant over the existing websocket with python
  fallback (S2 pulled forward, ax_bridge.py + AxContextReader.swift),
  and doctor now names the exact python binary for the grounded-lane
  grant; a switch-then-menu regression eval pinning the frontmost gate;
  meta/super aliased to cmd with the combo grammar in the tool
  description and cmd+t/w/n allowlisted at confirm tier; and the
  Broadcaster writer-task leak fixed (the PaMacCore -50 teardown line is
  ledgered, cosmetic). The round is green when Samay's live drive
  confirms it; the quick-test menu in `docs/NEXT-SESSION.md` is the
  script, and that file is deleted when the round closes.
- **STOP 3 (hand tuning) follows the P0 round.** I12 is live: Samay
  drives the playground and the hotkey until the motion is award-grade,
  tuned values write back to DesignTokens.swift and the spec tables in
  one commit. The deferred 12-principles adversarial pass and the Fable
  taste pass on a recording land here too.

## What's next

Canonical forward sequence: `docs/2026-07-07-roadmap.md` (blocks A through
E, with rationale and exit criteria). Summary as of the stock-take:

- **STOP 3 (hand tuning):** Samay drives the playground (`Conn --preview`)
  and the live hotkey until summon, breath, exhale, chip, and belay feel
  award-grade; tuned values write back to tokens and spec tables in one
  commit. The deferred adversarial 12-principles pass and
  taste-on-recording from I10's done-definition land here. This closes
  Block A.

Phases 4 and 5 after that: sound and the AX-via-app migration, then the full
live-eval proof run.

## Key files

| File | What it is |
|---|---|
| `README.md` | Run instructions, permissions, environment contract, layout |
| `docs/gpt-realtime-2-computer-agent-spec.md` | The v0 design spec (product thesis, architecture, tool contract, safety, cost, evals) |
| `docs/2026-07-05-ux-craft-spec.md` | The island round: surface, latency budgets, motion, typography, sound, reliability invariant |
| `docs/plans/2026-07-05-ux-craft-plan.md` | 19-packet execution plan with phase gates |
| `docs/orchestration-ledger.md` | Token accounting and gate results per phase (Fable doctrine) |
| `docs/idea-ledger.md` | Rejected and deferred ideas with concrete revisit triggers |
| `docs/DEPLOYMENT.md` | Running Conn on a second Mac |
| `docs/LIVE_EVAL_CHECKLIST.md` | Manual model-quality checklist (nine tasks) |
| `src/conn/` | The daemon: state machine, harness, adapters, audio, hotkey, server |
| `macos/Sources/Conn/` | The native app: island, panel, tokens, geometry, hotkey, daemon client |
| `console/` | The frozen web debug console |

## How to run it

```bash
# Native app (primary surface)
cd macos && ./make-app.sh && open Conn.app

# Demo, no credentials
cd /Users/samaydhawan/conn
PYTHONPATH=src /Users/samaydhawan/conn/.venv/bin/python -m conn --demo --simulate-tools

# Live (key daemon-side only, never seen by the browser)
export OPENAI_API_KEY=...
PYTHONPATH=src /Users/samaydhawan/conn/.venv/bin/python -m conn

# Tests and evals
PYTHONPATH=src /Users/samaydhawan/conn/.venv/bin/python -m pytest tests -q   # 260 tests
PYTHONPATH=src /Users/samaydhawan/conn/.venv/bin/python -m conn --eval       # harness evals
PYTHONPATH=src /Users/samaydhawan/conn/.venv/bin/python -m conn --doctor     # TCC/grant check
```
