# Review and implement Conn's voice-first reliability program

You are taking over `/Users/samaydhawan/conn` to review, correct, and then
implement Conn's voice-first reliability program.

Work autonomously until the authorized semantic reliability program is
mechanically green and the available live evidence is recorded. Stop only for
a true external blocker, a material product decision that cannot be resolved
from the approved documents, or a required human acceptance step.

Do not expand into visual control, OCR, screenshots-to-model, coordinate
actions, a second computer-use model, broad app profiles, hidden macros, MCP,
sound, motion polish, character work, outbound actions, destructive actions,
or unrelated cleanup.

## Outcome

Turn Conn from a mechanically safe but brittle demo into a reliable
voice-first Mac control loop.

The target loop is:

```text
validated PTT turn
  -> bounded semantic intent
  -> live native capability report
  -> locally compiled target, strategy, risk, and effect witness
  -> one verified action transaction
  -> verified result, one safe predispatch repair, or one useful clarification
```

The Realtime model describes the user's goal. It does not choose raw keys,
menu traversal, AX mechanics, snapshot refs, risk, or low-level effect
predicates for ordinary actions.

Preserve all verified-action invariants. `Done.` remains evidence-backed only.

## Confirm repository and preserve user work

Before any action:

```bash
cd /Users/samaydhawan/conn
git rev-parse --show-toplevel
git status --short --branch
git log -5 --oneline
```

Read `/Users/samaydhawan/conn/AGENTS.md` completely. If `.beads/` exists, run
`bd prime` and `bd ready`.

Treat existing changes and untracked files as user-owned. Do not overwrite,
delete, stage, commit, or push them unless the user explicitly authorizes it in
this session. Never use destructive git commands.

## Skills

Use these skills where available:

1. `diagnose` for evidence-led failure analysis.
2. `build-macos-apps:swiftpm-macos` for package, build, and test structure.
3. `build-macos-apps:appkit-interop` for AX, AppKit runloop, hotkey, and native
   bridge work.
4. `tdd` for every implementation packet.
5. `swift-concurrency` for actor, callback, task, runloop, and bridge
   boundaries.
6. `check` once against the final diff.

Do not run broad security scans as routine ceremony. If the final diff
materially changes authentication, authorization, secret handling, or console
privilege, run one narrowly scoped security diff review at the end. Do not
repeat it after every packet.

## Read first

Read in this order:

1. `docs/STATE-OF-PLAY.md`
2. `docs/2026-07-12-voice-first-reliability-spec.md`
3. `docs/agent-wargames/2026-07-12-voice-first-reliability-wargame.md`
4. `docs/2026-07-07-roadmap.md`
5. `docs/NEXT-SESSION.md`
6. `docs/2026-07-09-verified-action-engine-spec.md`
7. `docs/agent-wargames/2026-07-09-verified-action-engine-wargame.md`
8. `docs/2026-07-06-capability-spec.md`
9. `docs/idea-ledger.md`

Inspect the failing runtime artifacts:

- `data/traces/2026-07-12/session_a4f5c83703.jsonl`
- `data/receipts/2026-07-12/session_a4f5c83703.json`
- `data/logs/daemon-2026-07-12.log`
- latest relevant files under `data/action-probes/`
- latest relevant file under `data/evals/2026-07-12/`

Then inspect the current implementation and related tests:

- `src/conn/realtime/openai_ws.py`
- `src/conn/realtime/base.py`
- `src/conn/state.py`
- `src/conn/events.py`
- `src/conn/app.py`
- `src/conn/audio.py`
- `src/conn/prompt.py`
- `src/conn/cost.py`
- `src/conn/trace.py`
- `src/conn/latency.py`
- `src/conn/tools/registry.py`
- `src/conn/tools/harness.py`
- `src/conn/tools/native_actions.py`
- `src/conn/tools/risk.py`
- `src/conn/server/http.py`
- `src/conn/ax_bridge.py`
- `src/conn/evals.py`
- `evals/tasks.json`
- `macos/Sources/Conn/AppDelegate.swift`
- `macos/Sources/Conn/AppState.swift`
- `macos/Sources/Conn/DaemonClient.swift`
- `macos/Sources/Conn/DaemonLauncher.swift`
- `macos/Sources/Conn/HotkeyMonitor.swift`
- `macos/Sources/Conn/NativeSemanticTypes.swift`
- `macos/Sources/Conn/NativeObservationStore.swift`
- `macos/Sources/Conn/NativeSemanticActionEngine.swift`
- `macos/Sources/Conn/NativeAXSemanticBackend.swift`
- `macos/Sources/ConnActionFixture/`
- relevant Python and Swift tests

## Hard environment gate

Before production Swift changes:

```bash
cd /Users/samaydhawan/conn/macos
./make-app.sh
```

The build must use a toolchain that expands SwiftUI macros. If no working
toolchain exists, report the exact blocker. Do not fake Swift verification or
edit around missing macros.

Before signed live acceptance:

```bash
security find-identity -v -p codesigning
codesign -dv --verbose=4 /Applications/Conn.app 2>&1
```

If stable signing is absent, continue safe pure and fixture work where
possible, then name the exact user step needed for live TCC proof. Do not treat
an ad hoc signature as stable acceptance evidence.

## Mechanical baseline

Run before the first code change:

```bash
cd /Users/samaydhawan/conn
PYTHONPATH=src .venv/bin/python -m pytest tests -q
PYTHONPATH=src .venv/bin/python -m conn --eval
PYTHONPATH=src .venv/bin/python -m conn --doctor

cd /Users/samaydhawan/conn/macos
DEVELOPER_DIR=/Applications/Xcode-beta.app/Contents/Developer swift test
./make-app.sh

cd /Users/samaydhawan/conn
git diff --check
```

Use the actual working `DEVELOPER_DIR` if it differs. Record exact counts,
warnings, and environment limitations.

Do not proceed from a red baseline until the failure is explained and shown to
be unrelated to the requested work.

## Phase one: adversarially review the spec before coding

Do not assume the July 12 reliability spec is correct because it is detailed.
Verify it.

Produce an evidence-backed review that answers:

1. Do the cited trace counts and causal claims match the current artifacts?
2. Does current source still generate overlong semantic context IDs, remember
   rejected items, cancel unbound responses, and expose a menu or key-chord
   effect contract that native code rejects?
3. Can playback-contaminated pre-roll actually reach a barge-in turn? Treat
   this as a hypothesis until a recorded PCM test or live probe proves it.
4. Can `create(kind=tab)` and
   `select_relative(relation=next, kind=document)` compile from live native
   affordances without app-specific command data?
5. Is the proposed intent algebra small and app-agnostic, or is it a disguised
   command catalog?
6. Can one predispatch replan be implemented without weakening provenance,
   serialization, or uncertain-dispatch rules?
7. Does every proposed verified path have a causal target-bound witness?
8. Are the packet order and acceptance bars the fastest route to daily use?
9. Which proposed work is unnecessary or overbuilt?
10. What evidence would falsify the recommended architecture?

Compare at least these alternatives:

- patch defects and prompt only
- large deterministic command catalog
- capability-compiled semantic intents
- direct API, App Intents, or MCP-first execution
- vision-first computer use

Record corrections directly in the reliability spec and wargame. Do not
create a redundant review document unless the review produces a separate
long-lived decision. Add a concise entry to `docs/orchestration-ledger.md`.

If the review finds no material architecture flaw, continue directly into
implementation. If it finds a real contradiction, revise the spec before
coding. Ask the user only when the decision changes product scope, safety, or
an irreversible external action.

## Working method

Create a packet plan from R0 through R8 in the reliability spec. Keep one
packet `in_progress`.

For every packet:

1. Write a discriminating failing test, strict replay, or live probe first.
2. Observe the expected failure.
3. Implement the smallest coherent production change.
4. Run named tests.
5. Run the full relevant Python or Swift gate.
6. Inspect actual trace, receipt, build, or fixture output.
7. Update source-of-truth docs only after evidence changes.
8. Continue to the next packet.

Do not bundle the entire rewrite into one diff. Do not make unrelated cleanup
changes. Remove redundant docstrings, decorative comments, and obsolete paths
when the packet makes them unnecessary.

## R0: evidence and trace truth

Build the feedback loop first.

Required:

- exact assistant transcript events, not modality-only markers
- signed build, commit, config fingerprint, trace schema, PID, and parent PID
- correct `app_hotkey`, console, or typed source
- gesture, turn, response, plan, and transaction correlation
- receipts that distinguish user turns, model responses, proposals,
  executions, and goal outcomes
- blocked proposals included in metrics
- primary Swift surface `ui_ack` for listening, thinking, approval, and
  terminal outcome
- per-turn latency distributions
- linked full tool-result artifacts without unsafe trace content
- outcome-derived probe filenames
- local sanitized `Report Last Command`
- replay cassette for the July 12 failure sequence

The reporting path must exclude raw secure values, clipboard bodies, bridge
tokens, raw audio, screenshots, and image bytes by default.

## R1: wire and lifecycle integrity

Required:

- semantic context item IDs obey the live limit
- prefer server-generated item IDs when possible
- item create and delete state follows server acknowledgements
- failed create never becomes active context
- only acknowledged items are deleted
- cancel only a bound active response and include its response ID
- strict fake Realtime server enforces item limits, acknowledgements, missing
  deletes, response lifecycle, and terminal events
- app-launched daemon has a parent PID and launch nonce ownership lease
- authenticated graceful shutdown on normal app quit
- bounded orphan exit after owned parent loss
- foreign port owner is never killed or adopted

Required proof:

- zero expected protocol errors across 1,000 replayed normal turns
- 50 clean quit and reopen cycles
- 20 crash and relaunch cycles recover or show one actionable failure

## R2: voice turn integrity

Required:

- one unique gesture ID on both PTT edges
- duplicate modifier edges are idempotent
- accepted or rejected turn acknowledgement
- local playback flush before a barge-in mic gate opens
- pre-roll captured during playback is suppressed
- short voiced holds are accepted
- silent taps are rejected visibly
- stale model and user lines clear at turn start
- recorded PCM fixture with a synthetic playback watermark
- external-keyboard duplicate-edge tests

Do not add ambient listening or continuous VAD.

Required proof:

- 500 PTT cycles with no stuck phase, duplicate turn, lost release, or silent
  voiced-turn loss
- zero synthetic playback watermark in uploaded command audio

## R3: remove the impossible action contract

Required:

- remove model-visible `desired_effect` from ordinary mutation tools
- stop advertising raw hotkey and raw menu tools in the default model surface
- preserve hidden policy-gated diagnostic escape hatches if still useful
- add bounded semantic intent types and schemas
- model supplies goal and semantic slots only
- native preparation derives strategy, target binding, risk preview, and
  witness or truthful outcome ceiling
- no-witness action becomes dispatch-only when policy permits, not an invalid
  model-predicate failure
- first vertical slices are `create(kind=tab)` and `select_relative`

Do not introduce a giant `computer_act` schema.

## R4: capability compiler

Add a native `CapabilityReport` bound to turn and observation epoch.

It should contain a bounded set of semantic candidates, current support,
available strategies, witness availability, secure or denied state,
ambiguity, and verified or dispatch-only ceiling.

Compilation order:

1. direct deterministic OS API
2. unique native semantic operation
3. exact live menu command after lazy population
4. exact live shortcut exposed by that menu item
5. policy-permitted dispatch-only
6. clarify or refuse

Candidate confidence may rank. It may not authorize, break a semantic tie, or
become evidence.

No per-app command catalog. A new generic intent family must cover at least two
apps or one OS primitive.

## R5: targeted witness engine

Prepared plans add bounded read sets and witness sets. Replace broad 25ms tree
polling with notification hints and targeted rereads using adaptive backoff.

Align Python bridge deadlines with native action budgets plus bounded
transport margin.

Add causal witnesses for:

- create tab
- select relative item
- menu toggles
- focused window changes
- submit only where a surviving target-bound witness exists

Broad layout, arbitrary window change, tree omission, menu close, and
unrelated notification remain insufficient.

## R6: bounded recovery and useful failure UX

Receipts add stable reason and repair fields. Permit one fresh observation and
replan only after proven `not_dispatched`. Compile failures do not consume the
dispatch budget. Any dispatched or possibly-dispatched result stops.

Ask one bounded clarification for ambiguity. Stop identical repeated plan
shapes. Speak a safe reason and next move without internal terminology.

Examples:

- `I found two Save buttons. Which one?`
- `Notes changed before I could act. Try again.`
- `I sent it, but could not confirm it worked.`
- `The action may have been sent. Check before retrying.`

## R7: realistic evaluation and failure flywheel

Keep `conn --eval` but label it harness-only.

Add:

- strict protocol replay
- signed real-AX fixture gate
- prerecorded PTT and audio gate
- opt-in `conn --intent-eval` using the production prompt and current
  Realtime model with dispatch disabled
- reviewed corpus of at least 200 paraphrases across the top 20 ordinary
  commands
- failure artifact promotion into reviewed regressions
- reliability reporting by app version, intent, target role, and witness

No online self-modifying policy. Empirical history can only downgrade support.

## R8: daily-driver gate

Mechanical and semantic bars:

- zero wrong targets
- zero false `Done.`
- zero normal-path upstream protocol errors
- zero manual daemon cleanup
- 100 percent of ambiguous targets clarify or refuse
- 100 percent of possibly-dispatched outcomes avoid retry
- at least 95 percent first-try completion across supported top-20 ordinary
  commands
- at least 99 percent completion after one safe replan or clarification
- release-to-effect p50 at most 2.0s and p95 at most 4.0s for warm semantic
  actions
- three 100-turn soak sessions with no stale mutation, duplicate response,
  stuck UI, or unbounded repair loop

Product acceptance still requires Samay:

- 30 ordinary commands across at least three real work sessions
- zero false completion language
- zero unexplained failures
- at least 90 percent of supported actions faster than hands or useful while
  hands are occupied

If Samay cannot run that gate in the session, leave exact copy-paste test
instructions and do not call the product gate passed.

## Non-negotiable boundaries

- Python remains policy and orchestration plane.
- Conn.app remains sole production macOS observation and action plane.
- Harness owns risk and approval.
- Native capability may escalate risk, never downgrade it.
- Approval remains pointer-only and exact-plan-bound.
- Mutations serialize.
- One mutation dispatches at a time.
- Every mutation re-resolves immediately before dispatch.
- Raw native success never produces `verified`.
- `ok` is true only for evidence-backed verified mutation.
- `possibly_dispatched` never retries.
- Secure fields and denied bundles remain blocked.
- No production Python AX or input fallback.
- No visual or coordinate fallback.
- No app command catalog.
- No multi-action macro.
- No separate model.
- No new service, account, or API key.
- No `osascript` for action execution.
- No hardcoded coordinates.
- No config path from unverified dispatch to success.

## Verification before final claim

Run all relevant packet gates, then:

```bash
cd /Users/samaydhawan/conn
PYTHONPATH=src .venv/bin/python -m pytest tests -q
PYTHONPATH=src .venv/bin/python -m conn --eval
PYTHONPATH=src .venv/bin/python -m conn --doctor
PYTHONPATH=src .venv/bin/python -m conn --latency-report

cd /Users/samaydhawan/conn/macos
DEVELOPER_DIR=/Applications/Xcode-beta.app/Contents/Developer swift test
./make-app.sh install
codesign --verify --deep --strict --verbose=2 /Applications/Conn.app

cd /Users/samaydhawan/conn
git diff --check
```

Use the actual working developer path. Inspect real output, not status alone.

Run the `check` skill once against the full diff. Fix validated findings. Run
the final gates again after any fix.

If the diff materially changed authentication, authorization, secret
handling, or console privilege, do one narrow final security review of those
changes. Do not run broad repeated scans.

## Final source inspection

Search production source for:

- model-visible `desired_effect` on ordinary actions
- raw hotkey or menu strategy choice in the default tool set
- any raw dispatch success path to verified
- automatic retry after possible dispatch
- identical repeated plan shapes
- stale response or observation reaching execution
- concurrent mutations
- unacknowledged semantic context treated as live
- cancel sent without an active response
- production Python AX or input fallback
- app-specific command tables
- secure or clipboard value in trace
- green Done for unverified outcome
- visual or coordinate action code

## Documentation

Update only after evidence changes:

- `docs/STATE-OF-PLAY.md`
- `docs/2026-07-12-voice-first-reliability-spec.md`
- `docs/2026-07-07-roadmap.md`
- `docs/NEXT-SESSION.md`
- `docs/MANUAL-TESTING.md`
- `docs/LIVE_EVAL_CHECKLIST.md`
- `README.md`
- `docs/DEPLOYMENT.md`
- `docs/idea-ledger.md`
- `docs/orchestration-ledger.md`

Do not preserve stale counts or readiness claims. Do not add redundant docs.
No em dashes anywhere. Remove decorative comments and redundant docstrings.

## Completion report

Lead with the outcome.

Report:

- review corrections made before implementation
- packets completed
- exact test, replay, eval, build, restart, PTT, fixture, and soak counts
- live commands run and independent verdicts
- acceptance bars met or pending
- files changed
- environment blockers
- remaining risks
- exact next user action for any human product gate

Do not say complete because code compiles. Complete means the authorized
semantic reliability program is mechanically green, no known false-success or
unsafe-retry path remains, basic voice commands work through the signed app,
live evidence is recorded, docs match reality, and every unrun human gate is
named honestly.
