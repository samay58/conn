# Conn: state of play

Updated 2026-07-16. Read this first. Use `docs/2026-07-07-roadmap.md`
for remaining work and `docs/NEXT-SESSION.md` for the next execution block.

## Current verdict

The capable-navigation recovery and Conn Lab are implemented. The final L9
boundary passed 741 Python tests with three intentional deselections and two
dependency warnings, three lifecycle tests, 14 harness evals, and 232 Swift
tests. The 86 focused lab tests exercise the public command surface, typed
scenario catalog, bounded private guest execution, receipt-to-oracle records,
and artifact metadata.

The authoritative live intent corpus passed 225 of 226 items, or 99.56
percent, in
`data/intent-evals/2026-07-16/results-1784228271.json`. It cost $1.392171.
The sole miss asked to press Refresh; the model proposed unsupported key `r`
instead of grounding the visible button. The failure remains in the grader.

The safety kernel is unchanged and still pinned: mutations serialize, raw
native success cannot produce `Done.`, `possibly_dispatched` never retries,
one replan is permitted only after proven `not_dispatched`, and approval
remains owned by the signed app.

Conn Lab now runs the real daemon, signed app, native observation and input,
fixtures, Safari, Notes, Firefox, and the current Realtime model in disposable
macOS guests. It compares every Conn receipt with an independent oracle. The
20-run fresh-clone suite and 100-iteration scripted matrix passed with no host
state change. This moves repeated engineering probes off Samay's desktop.
Twelve public scenarios come from one validated JSON catalog instead of a
second CLI registry. Each run writes typed run, oracle, and artifact records.
Guest-only secrets travel through a bounded standard-input envelope and never
appear in host process arguments or reports.

The implementation now permits broad reversible foreground navigation after
one pointer-only session grant. Accessibility remains the preferred lane.
Conn.app can capture one bounded current-window image, bind normalized visual
grounding to it, revalidate app, window, frame, scale, grant, and connection,
then dispatch one bounded pointer sequence. The code default remains off for
missing or old config, while this candidate's repository config enables the
lane after its transport and adversarial gates passed. Destructive actions remain
refused; consequential actions keep one-action pointer approval. Apps resolve
dynamically through installed identity, and direct browser navigation honors
the requested or current browser. The design is in
`docs/2026-07-13-capable-navigation-spec.md`, with the execution contract in
`docs/2026-07-13-capable-navigation-implementation-plan.md`.

The lab contract is `docs/2026-07-16-conn-lab-spec.md`. Its implementation
record is `docs/2026-07-16-conn-lab-implementation-plan.md`.

The default session budget is now $5.00 with a $2.50 warning. The hard stop
remains enabled. This raises headroom without weakening cost accounting or the
explicit one-session override.

## July 13 post-release dogfood verdict

The full analysis is
`docs/2026-07-13-dogfood-failure-analysis.md`. The four shipped-build sessions
contain 29 user turns, 40 tool proposals, 9 predispatch blocks, and 12 action
receipts:

| Outcome | Count |
|---|---:|
| Verified app opens | 3 |
| Dispatch only | 7 |
| No effect | 1 |
| Failed after possible dispatch | 1 |

The sessions cost $2.554. The main confirmed causes are:

- snapshot search terms are silently ignored by Swift, so the model receives
  raw trees instead of bounded candidates
- repeated observations accumulate in model context and can exhaust the
  session budget before the task finishes
- duplicate fingerprints return ambiguity before the resolver tries its
  stronger structural locator
- clarification answers are not bound to real candidates
- the production action surface cannot control an opaque video player
- browser search cannot perform direct navigation or honor an explicit browser
- the native transaction deadline can expire while a successful action is
  still returning its receipt
- Safari and Notes create witnesses do not generalize across real layouts
- barge-in can splice unfinished result speech into the next response
- most non-verified receipts have no reason code, and large artifacts can be
  truncated into invalid nested JSON

The Firefox video refusal itself was safe: the tree exposed repeated anonymous
full-window groups and no named Play control. The product failure is that Conn
had no visual or semantic fallback after that honest ceiling. The Techmeme
`RIVER` refusal was a resolver defect because a named link had stronger
structural identity that the resolver never consulted.

## July 13 targeted witness evidence

The first live reliability-build session is
`data/traces/2026-07-13/session_64e67d4bf3.jsonl`. App opens verified and the
voice loop behaved correctly, but Safari New Tab returned `no_effect` twice
after visible dispatch, Notes New Note returned `dispatch_only`, and grounded
click plans with an empty title were rejected as missing a safe target.

The follow-up closed selected fixture and probe gaps:

- empty titles now fall through to the first non-empty safe target
- Safari create binds a descendant-role count to the tab collection subtree;
  the live receipt changed from `no_effect` to `verified` as the bound
  `AXRadioButton` count moved from 2 to 3
- when Safari hides the tab collection for a single-tab window, create caps at
  `dispatch_only` until a specific collection exists in the baseline
- Notes create filters out the folders outline and binds to the unique
  kind-compatible note table; the live receipt returned `verified` as the
  bound row count increased
- adversarial fixtures pin unrelated descendants, missing collections, and
  genuinely ambiguous note lists as non-verifying
- the probe artifacts retain `visible_confirmation_required`; the native tree
  and receipt agree, but no separate human eye verdict was recorded during
  those targeted runs

The live artifacts are:

- `data/action-probes/safari-tab-no_effect-1783956774100774000.json`
- `data/action-probes/safari-tab-verified-1783956963512428000.json`
- `data/action-probes/notes-note-verified-1783956973323729000.json`
- `data/intent-evals/2026-07-13/results-1783960836.json`

## July 12 dogfood verdict (historical baseline)

The live session in
`data/traces/2026-07-12/session_a4f5c83703.jsonl` recorded:

- 16 PTT cycles and 11 completed transcripts
- 21 model responses
- 40 upstream protocol errors
- 7 state-changing proposals
- 2 verified app opens
- 5 in-app mutations blocked before dispatch

Notes next-item navigation did not execute. Safari New Tab failed repeatedly.
The exact assistant speech and UI acknowledgement timing were not captured, so
the trace cannot audit completion language or perceived latency.

The dominant failures are systemic:

- semantic context IDs exceed the live API limit, then rejected IDs are
  deleted as if creation succeeded
- schemas invite `desired_effect` on menu and key-chord tools while the native
  engine rejects every supplied effect for those operation families
- the model is asked to invent shortcuts, menu paths, refs, and proof
  predicates that current native state can derive more reliably
- current evals test scripted harness behavior, not live intent selection or
  user-goal completion
- the daemon lacks a safe ownership lease across app restart
- audio pre-roll may include model playback during barge-in; this remains a
  high-confidence hypothesis pending a recorded PCM proof

## Runtime shape

Python owns:

- Realtime session and prompt
- pure state machine and provenance ledger
- risk, approval, mutation serialization, traces, and cost
- native plan preparation and receipt validation

Conn.app owns:

- current app, window, and Accessibility observations
- target identity and execution-time re-resolution
- plan fingerprints and signer-bound app launch
- dispatch, effect verification, and retry certainty

The web console can observe state only. It cannot approve, initiate actions,
claim the app role, or answer native RPC. No Conn surface takes keyboard
focus. Approval remains pointer-only inside the signed app.

Push-to-talk defaults to left-side Control + Option so external keyboards do
not depend on right-side modifier identity. Releasing either key ends the
press. The menu-bar menu can switch it to Right Command, Left Control, Left
Option, Right Control, Right Option, or F13. Choice persists across relaunches
and signed rebuilds. The Lofree's key beside Space reports Left Command, so it
cannot safely serve as a distinct Right Command trigger.

## Action contract

Every mutation follows this path:

1. Observe current app, window, target, and baseline.
2. Resolve the target against current native state.
3. Prepare one bounded plan and effect predicate.
4. Apply Python risk policy and pointer approval.
5. Revalidate the approved plan.
6. Dispatch one strategy.
7. Observe again and classify the outcome.
8. Continue the model only after every call is resolved.

Internal outcomes are `verified`, `dispatch_only`, `no_effect`, `blocked`,
`ambiguous`, and `failed`. Mutation `ok` is true only for `verified`.

- `Done.` means verified effect evidence.
- `Sent, not confirmed.` means dispatch happened without confirmation.
- `Did not run.` covers every unsuccessful outcome.

One equivalent fallback is allowed only after proven `not_dispatched`.
`possibly_dispatched` never retries automatically. Effects already true before
dispatch refuse instead of manufacturing success. AX notifications remain
trace hints and cannot verify an action without targeted state evidence.

Recovery is bounded per turn: one replan after a proven `not_dispatched`
failure, at most two predispatch compile failures, and no identical failed
plan shape twice. The receipt contract requires a `reason_code` and a
`safe_user_message` with no internal terminology. Tests now pin a stable reason
on every non-verified outcome. Predicate evidence records baseline, current
value, match rule, and match Boolean.

## Supported semantic operations

- bounded semantic intents: `create(kind)` compiled from live menu
  affordances with collection or window-count witnesses, and
  `select_relative(relation, kind)` compiled from the current native
  selection with a selected-state witness
- app open and switch by exact bundle and code-signing identity
- clipboard write with hash readback
- tab focus
- scroll-to-visible and bounded directional value movement
- non-secure text entry; submit runs only after text and focus revalidation
- element press
- lazy menu traversal and leaf dispatch
- raw menu paths and allowlisted key chords remain policy-gated diagnostics,
  hidden from the default model surface
- dynamic app open and switch through installed identity discovery
- direct HTTP and HTTPS navigation in the named or current browser
- pointer-only navigation lease for reversible foreground actions
- bounded current-window visual observation through Conn.app
- semantic or capture-bound activation and a fixed navigation-key vocabulary

Menu commands, raw key chords, and submit without a surviving target-bound
effect return `dispatch_only`. Global window changes and bounded-tree absence
do not count as proof because unrelated activity can produce both.

Secure fields, denied bundles, destructive effects, ambiguous targets, stale
plans, and legacy native mutation RPC refuse before dispatch. Production has
no Python Accessibility, screenshot, or input fallback. OCR, macros, app
command catalogs, and a second computer-use model remain out of scope.

## Measured evidence

Latest recorded evidence before the final L9 gate:

| Gate | Result |
|---|---|
| Python boundary | 741 passed, 3 deselected; 2 dependency warnings |
| Harness evals (harness-only label) | 14 of 14 passed |
| Strict Realtime replay | 1,000 turns plus the July 12 cassette, zero protocol errors |
| Lifecycle | 3 tests passed on port 18787; 50 graceful quits, 20 crash relaunches, and 3 orphan exits |
| PTT cycles (machine) | 500 with zero stuck phases, duplicate turns, or lost releases |
| Soak | three 100-turn scripted sessions, zero upstream errors or stuck states |
| Swift | 232 passed |
| Release build | signed with `Conn Dev Signing` |
| Live intent sample | 25 of 25; `results-1784226540.json`; $0.266418 |
| Live intent full corpus | 225 of 226 (99.56 percent); `results-1784228271.json`; $1.392171 |
| Fresh-clone release transactions | 20 of 20; p50 31.014s, p95 31.434s |
| Scripted adversarial matrix | 100 of 100 |
| Live-model VM transactions | control verified; Safari tab verified; Firefox Play dispatch-only with matching oracle |
| Automatic latency report | command passed; newest harness trace had no PTT turns, so live spans were N/A |

The 97 percent intent bar is met. The one residual miss is not waived.

Reconnect recovery now retries for five minutes with exponential spacing
capped at 30 seconds. Concurrent disconnect paths share one reconnect task.
Tests prove the state remains `FAILED`, shown as `Reconnecting`, until a
complete connection succeeds. The shared pytest config writes below its
temporary directory. After final billed evidence, a full 644-test run left the
real `data/` tree unchanged at 1,415 files, 6,048,162 bytes, and manifest digest
`bd59fbaacacfb8e8a73c475350a3887240ae7a6ee911f5eec8cea05fdc6cbfbb`. The cleanup
removed 659 traces that never entered `session_start`, 82 linked receipts, 121
linked tool-result files, and 31 linked support rows; all 424 initialized traces
were preserved.

Earlier signed-build checks from 2026-07-12:

- app bridge authenticated after launch
- Python and Conn.app Accessibility lanes both reported granted
- physical Control + Option press and release worked on the Lofree keyboard
- fixture no-effect probe returned `no_effect` in 525ms and agreed with the
  independent truth log

The 1,000-transaction test uses the in-memory Swift
`SemanticFixtureBackend`. It recorded 980 verified actions, 10 intentional
no-effect outcomes, 10 ambiguity refusals, zero wrong targets, and zero false
verified outcomes. It checks transaction logic and latency. It is not a real
ConnActionFixture or Accessibility acceptance run.

Other live smoke evidence from 2026-07-12:

- ConnActionFixture no-effect action: 3 of 3 returned `no_effect`; independent
  truth log agreed; no retry.
- Terminal, Safari, Notes, and Obsidian app switches: first transition returned
  `verified`; WindowServer's top visible window matched the expected bundle.
- Repeating a switch while that app was already frontmost refused with
  `effect_already_satisfied` before dispatch.
- Google Chrome was not installed for this 2026-07-12 smoke run. The engine at
  that time used a fixed support map; the new candidate uses live installed-app
  and signer resolution.

These are installation and transaction smoke checks. They do not establish
the spec's 95 percent six-app semantic-action bar.

## Review findings closed on 2026-07-12

Final consolidation fixed six classes of failure:

- verification now needs target-bound state evidence, not an already-true
  predicate, notification hint, tree omission, or unrelated global change
- uncertain dispatch never falls back or retries, and raw success cannot become
  `verified`
- target identity stays bound across approval, dispatch, and verification by
  process, window, semantic fingerprint, hierarchy, frame, and secure state
- model arguments, Realtime terminal calls, receipt Booleans, plan
  fingerprints, and privileged context identifiers fail closed
- the app bridge is authenticated and replay-resistant; the browser console is
  read-only; client queues are bounded; child processes receive no secrets
- named applications bind to exact bundle IDs and, for third-party apps, a
  locally proven signing team

The final security scan reviewed 55 production and protocol files. It promoted
15 candidates, fixed 14, suppressed one developer-fixture-only path, and left
zero reportable findings. Regression tests pin every production fix. Obsidian
is bound to team `6JSW4SJWN9`. Chrome stays blocked until its installed
signature can be inspected.

## Conn Lab evidence

The pinned guest is macOS 26.5 build `25F71` under Tart 2.32.1. Runs use
default Tart NAT, no host clipboard or audio sharing, a read-only source
mount, one read-write artifact mount, and guest port 18787. Softnet remains an
optional explicit mode and is not a release gate.

The final ordinary Python run left the real `data/` tree unchanged at 3,813
files and 34,117,511 bytes, with manifest digest
`106ba2217f93c3a960037bb8915f6c7b237041669781484c47c37e64d0516d03`.
Fixed navigation keys now refuse when the focused element is a secure field or
an unclassified text entry, including a fresh recheck immediately before
native dispatch.

Live receipts and separate oracles:

| Goal | Receipt | Independent result |
|---|---|---|
| Press fixture control | `verified` | `control_changed` once |
| Open Safari tab | `verified`; tab count 2 to 3 | original page hidden once |
| Create Notes note | `verified`; row count 2 to 3 | disposable database count 1 to 2 |
| Type Notes scratch text | `verified` | exact title changed to `conn lab scratch` |
| Select previous Notes note | `verified` | selected Notes object changed |
| Click Firefox Play | `dispatch_only`; `no_trustworthy_witness` | `pointer_play` once |

Firefox is an honest capability ceiling. The action completed according to the
local page, but Conn did not claim verified because visual motion is not a
trusted semantic witness.

The final public smoke artifact is
`data/lab-runs/2026-07-16/lab-smoke-170232-summary.json`: one verified receipt,
one matching oracle, 100 of 100 scripted adversarial iterations, no observed
host change, $0.0022 recorded cost, and 31.979 seconds total. The direct VNC
boot is headless. Cleanup left no Tart, disposable guest, or Screen Sharing
process.

Two structural follow-ons remain for the capability-breadth delivery. Split
the full-stack scenario driver into capsule-owned setup and oracle seams, and
put semantic and visual native plan routing behind one explicit action
facade. Neither changes the current transaction contract.

`data/lab-runs/2026-07-16/lab-release-161704-summary.json` contains 20 of 20
verified fresh-clone transactions and 20 matching oracles. Its command exited
red only because the old host snapshot gate treated Samay's pointer and
clipboard activity as lab activity. That gate now reports raw host activity
without failing the transaction suite. Mounts, ports, audio, clipboard
sharing, VM names, and cleanup remain enforced boundaries.

One earlier release run returned `kAXErrorCannotComplete` after the fixture
changed exactly once. Conn recorded failed and possibly dispatched, did not
retry, and did not claim verified. The artifact is
`data/lab-runs/2026-07-16/lab-release-160545-19`. This is an honest native
uncertainty, not a false verified result.

## Open gates

Engineering acceptance in the VM is complete after the L9 release suite. Human
product acceptance remains:

- relaunch the installed candidate if an older Conn process is running
- run the physical microphone acoustic barge-in check
- run `docs/MANUAL-TESTING.md`
- complete the 30-command product gate across three ordinary work sessions

Visual dispatch is enabled for this candidate behind the existing config kill
switch. The latest live latency evidence is still the
July 13 eight-turn session: release-to-first-token p50 898ms and p95 1,724ms.
The automatic P9 report ran against a harness trace with no PTT spans, so it
does not replace that live measurement.

Product acceptance then needs 30 ordinary commands across three work sessions,
zero false completion language, and at least 90 percent of supported actions
faster than hands or useful while hands are occupied.

Do not call the semantic engine accepted for daily use until those gates pass.

## Key documents

| File | Purpose |
|---|---|
| `docs/2026-07-12-voice-first-reliability-spec.md` | Current reliability diagnosis, architecture, packets, and daily-driver bars |
| `docs/2026-07-13-dogfood-failure-analysis.md` | Aggregated post-release evidence and root causes |
| `docs/2026-07-13-capable-navigation-spec.md` | Approved product contract for one-grant reversible navigation |
| `docs/2026-07-13-capable-navigation-implementation-plan.md` | Packet order, code seams, TDD gates, migration, and release evidence |
| `docs/2026-07-16-conn-lab-spec.md` | Disposable macOS lab contract, interfaces, truth, and acceptance |
| `docs/2026-07-16-conn-lab-implementation-plan.md` | L0 through L9 execution record and evidence |
| `docs/2026-07-16-conn-lab-platform-proof.md` | Pinned VM and native capability proof |
| `docs/agent-wargames/2026-07-12-voice-first-reliability-wargame.md` | Adversarial decision record for the capability-compiled control loop |
| `docs/2026-07-09-verified-action-engine-spec.md` | Approved architecture and acceptance bars |
| `docs/agent-wargames/2026-07-09-verified-action-engine-wargame.md` | July 9 adversarial decision record |
| `docs/2026-07-07-roadmap.md` | Remaining priorities |
| `docs/NEXT-SESSION.md` | Next execution block |
| `docs/MANUAL-TESTING.md` | Safe manual confidence drill |
| `docs/LIVE_EVAL_CHECKLIST.md` | Human product gate |
| `docs/orchestration-ledger.md` | Historical implementation record |
