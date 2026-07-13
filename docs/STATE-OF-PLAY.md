# Conn: state of play

Updated 2026-07-12. Read this first. Use `docs/2026-07-07-roadmap.md`
for remaining work and `docs/NEXT-SESSION.md` for the next execution block.

## Current verdict

Conn's semantic action engine is implemented, hardened, and mechanically
green. Production mutations run through Conn.app as bounded transactions.
Python owns policy and orchestration. Raw Accessibility, LaunchServices,
pasteboard, key-event, or bridge success cannot produce `Done.`

The signed app is installed and basic live smoke probes work. The semantic
acceptance gate is still open. Current live probes cover app switching and one
no-effect fixture action. They do not cover the required operation matrix or
1,000 real fixture transactions. The 30-command product gate has not started.

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
and signed rebuilds.

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

## Supported semantic operations

- app open and switch by exact bundle and code-signing identity
- clipboard write with hash readback
- tab focus
- scroll-to-visible and bounded directional value movement
- non-secure text entry; submit runs only after text and focus revalidation
- element press
- lazy menu traversal and leaf dispatch
- allowlisted key chords

Menu commands, raw key chords, and submit without a surviving target-bound
effect return `dispatch_only`. Global window changes and bounded-tree absence
do not count as proof because unrelated activity can produce both.

Secure fields, denied bundles, ambiguous targets, stale plans, and legacy
native mutation RPC refuse before dispatch. Production has no Python AX/input
fallback. Visual coordinates, OCR, screenshots-to-model, macros, and a second
computer-use model remain outside this slice.

## Measured evidence

Latest mechanical run:

| Gate | Result |
|---|---|
| Python | 461 passed; 2 existing dependency warnings |
| Harness evals | 13 of 13 passed |
| Swift | 109 passed |
| Release build | passed with Xcode-beta toolchain |
| Doctor | all substantive checks passed; optional global-hotkey probe warned |
| Installed app | valid `Conn Dev Signing` signature, built 2026-07-12 |

An unlocked probe before the final rebuild received an empty Accessibility
snapshot. The newest persistent-signed build installed and verified cleanly,
but its fixture probe stopped before dispatch because the console was locked.
Unlock the desktop and rerun. If the snapshot is still empty, toggle Conn off
and on in System Settings, Privacy and Security, Accessibility, then relaunch
it. Python doctor success does not prove the app's separate TCC grant.

The 1,000-transaction test uses the in-memory Swift
`SemanticFixtureBackend`. It recorded 980 verified actions, 10 intentional
no-effect outcomes, 10 ambiguity refusals, zero wrong targets, and zero false
verified outcomes. It checks transaction logic and latency. It is not a real
ConnActionFixture or Accessibility acceptance run.

Live smoke evidence from 2026-07-12:

- ConnActionFixture no-effect action: 3 of 3 returned `no_effect`; independent
  truth log agreed; no retry.
- Terminal, Safari, Notes, and Obsidian app switches: first transition returned
  `verified`; WindowServer's top visible window matched the expected bundle.
- Repeating a switch while that app was already frontmost refused with
  `effect_already_satisfied` before dispatch.
- Google Chrome is not installed. Its signer is therefore unproven and Conn
  blocks it before native preparation.

Those successful smoke records predate the final reinstall. The current signed
binary still needs an unlocked live rerun. Refresh its Accessibility toggle
only if that rerun returns an empty tree.

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

Semantic acceptance still needs:

- an unlocked current-build fixture rerun; refresh Conn.app Accessibility only
  if the rerun returns an empty tree
- a real ConnActionFixture matrix across each semantic operation
- 1,000 real fixture transactions checked against the independent truth log
- at least 95 percent first-try verified across observable actions in Terminal,
  Safari, Chrome, Notes, and Obsidian
- human verdicts recorded separately from engine receipts
- Chrome installed and its signer pinned, or an explicit spec change removing
  Chrome from the matrix

Product acceptance then needs 30 ordinary commands across three work sessions,
zero false completion language, and at least 90 percent of supported actions
faster than hands or useful while hands are occupied.

Do not call the semantic engine accepted for daily use until both gates pass.

## Key documents

| File | Purpose |
|---|---|
| `docs/2026-07-09-verified-action-engine-spec.md` | Approved architecture and acceptance bars |
| `docs/agent-wargames/2026-07-09-verified-action-engine-wargame.md` | July 9 adversarial decision record |
| `docs/2026-07-07-roadmap.md` | Remaining priorities |
| `docs/NEXT-SESSION.md` | Next execution block |
| `docs/LIVE_EVAL_CHECKLIST.md` | Human product gate |
| `docs/orchestration-ledger.md` | Historical implementation record |
