# Conn: state of play

Updated 2026-07-13. Read this first. Use `docs/2026-07-07-roadmap.md`
for remaining work and `docs/NEXT-SESSION.md` for the next execution block.

## Current verdict

The voice-first reliability program (packets R0 through R8 of
`docs/2026-07-12-voice-first-reliability-spec.md`) is implemented and
mechanically green. Every July 12 deterministic defect has a pinned fix:
context item IDs obey the live limit and follow server acknowledgements,
cancellation binds an active response, the daemon carries an ownership lease
and exits with its app, playback-contaminated pre-roll is suppressed, short
voiced holds are accepted while silent taps reject visibly, and the
model-facing action contract no longer asks the model for menu paths, key
chords, or effect predicates. Ordinary actions flow through two bounded
semantic intent tools (`computer_create`, `computer_select_relative`) that
Conn.app lowers onto live native affordances with compiler-owned witnesses.

The safety kernel is unchanged and still pinned: mutations serialize, raw
native success cannot produce `Done.`, `possibly_dispatched` never retries,
one replan is permitted only after proven `not_dispatched`, and approval
remains pointer-only in the signed app.

The July 13 verified-outcome follow-up is also mechanically green. It fixed
empty native targets, grounded create witnesses in real Safari and Notes
hierarchies, named destructive requests as out of scope, raised the live
intent gate above target, extended reconnect recovery, and isolated test
artifacts from dogfood data. Human acceptance is still open: the signed voice
runs need an eye verdict, followed by the acoustic and product drills.

## July 13 verified-outcome evidence

The first live reliability-build session is
`data/traces/2026-07-13/session_64e67d4bf3.jsonl`. App opens verified and the
voice loop behaved correctly, but Safari New Tab returned `no_effect` twice
after visible dispatch, Notes New Note returned `dispatch_only`, and grounded
click plans with an empty title were rejected as missing a safe target.

The follow-up closed those mechanical gaps:

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
plan shape twice. Every receipt carries a `reason_code` and a
`safe_user_message` with no internal terminology; ambiguity asks exactly one
question.

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

Menu commands, raw key chords, and submit without a surviving target-bound
effect return `dispatch_only`. Global window changes and bounded-tree absence
do not count as proof because unrelated activity can produce both.

Secure fields, denied bundles, ambiguous targets, stale plans, and legacy
native mutation RPC refuse before dispatch. Production has no Python AX/input
fallback. Visual coordinates, OCR, screenshots-to-model, macros, and a second
computer-use model remain outside this slice.

## Measured evidence

Latest mechanical run (2026-07-13, after the reliability program):

| Gate | Result |
|---|---|
| Python | 573 passed, 3 deselected; 2 existing dependency warnings |
| Harness evals (harness-only label) | 14 of 14 passed |
| Strict Realtime replay | 1,000 turns plus the July 12 cassette, zero protocol errors |
| Lifecycle cycles (real processes) | 50 graceful quit/reopen, 20 crash/relaunch, 3 orphan exits |
| PTT cycles (machine) | 500 with zero stuck phases, duplicate turns, or lost releases |
| Soak | three 100-turn scripted sessions, zero upstream errors or stuck states |
| Swift | 144 passed, including real-shape witness and adversarial refusal cases |
| Release build | passed and installed with the persistent signing identity |
| Live intent eval (full corpus) | 217 of 219 (99.1 percent); `results-1783960836.json` |

The intent bar is met. Named note opens now route to `phoenix_search`, semantic
screen reads precede screenshots, and app-routing cases use off-target injected
context. All four destructive asks produced no tool proposal and exactly the
one-sentence safe refusal. The two retained misses were `Another tab`, which
selected the next tab instead of creating one, and `Select the following note`,
where the model asked for a name without proposing a tool. The grader was not
weakened.

Reconnect recovery now retries for five minutes with exponential spacing
capped at 30 seconds. Concurrent disconnect paths share one reconnect task.
Tests prove the state remains `FAILED`, shown as `Reconnecting`, until a
complete connection succeeds. The shared pytest config writes below its
temporary directory. A full 573-test run left the real
`data/` tree at the same 1,156 files and the same manifest digest,
`5a232aa99afadfb958ae3f82194e7bf739e178d7fc303516803dcf6f416ee78a`. The cleanup
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
- Google Chrome is not installed. Its signer is therefore unproven and Conn
  blocks it before native preparation.

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

## Open gates

The reliability program and the verified-outcome follow-up are mechanically
green. What remains is live and human evidence against the installed build:

- signed-build voice runs: `Open a new tab` in Safari and `New note` in Notes,
  end to end through the microphone with receipts checked against eyes
- a live barge-in probe confirming the pre-roll suppression acoustically
  (the recorded-PCM watermark proof is synthetic)
- the safe drill in `docs/MANUAL-TESTING.md`, including the real
  ConnActionFixture matrix against its independent truth log
- at least 95 percent first-try verified across observable actions in
  Terminal, Safari, Chrome, Notes, and Obsidian (Chrome still needs an
  installed, signer-pinned build or a spec change)
- menu-toggle mark-state witnesses and ref-targeted partial rereads remain
  future work; verification today rereads the bounded tree on an adaptive
  backoff

Product acceptance then needs 30 ordinary commands across three work sessions,
zero false completion language, and at least 90 percent of supported actions
faster than hands or useful while hands are occupied.

Do not call the semantic engine accepted for daily use until those gates pass.

## Key documents

| File | Purpose |
|---|---|
| `docs/2026-07-12-voice-first-reliability-spec.md` | Current reliability diagnosis, architecture, packets, and daily-driver bars |
| `docs/agent-wargames/2026-07-12-voice-first-reliability-wargame.md` | Adversarial decision record for the capability-compiled control loop |
| `docs/2026-07-09-verified-action-engine-spec.md` | Approved architecture and acceptance bars |
| `docs/agent-wargames/2026-07-09-verified-action-engine-wargame.md` | July 9 adversarial decision record |
| `docs/2026-07-07-roadmap.md` | Remaining priorities |
| `docs/NEXT-SESSION.md` | Next execution block |
| `docs/MANUAL-TESTING.md` | Safe manual confidence drill |
| `docs/LIVE_EVAL_CHECKLIST.md` | Human product gate |
| `docs/orchestration-ledger.md` | Historical implementation record |
