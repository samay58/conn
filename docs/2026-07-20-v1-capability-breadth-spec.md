# Conn v1 capability breadth

Status: frozen for v1 on 2026-07-20.

`docs/NORTH-STAR.md` owns the product promise and finish line. This document
defines the mechanical breadth gate. It does not add product scope.

## Purpose

Conn v1 should handle ordinary reversible foreground navigation across
different native UI shapes without learning app commands. The breadth gate
asks whether one small intent algebra can act correctly in real apps, prove
what happened, and refuse when the platform does not expose a safe lane.

The test is capability breadth, not universal automation. A result counts
only when the requested job is inside the v1 boundary and the reference app
exposes the required native shape in the prepared state.

## Frozen inputs

The denominator was frozen before production fixes:

- `lab/capability-matrix.json`: eight surfaces by nine generic jobs, 72 rows
- `lab/v1-command-corpus.json`: twenty ordinary commands
- `lab/frozen-failures.json`: four sanitized incidents from July 13
- `lab/fixtures/`: generated local browser and Preview inputs

A failed command stays in the denominator. Exposure is established by capsule
setup and native observation, not by whether Conn succeeds. Changing the
matrix, corpus, scenario catalog, app build, golden VM, or production source
creates a new candidate and invalidates affected evidence.

## Reference surfaces

- Finder over `/Users/admin/Conn Lab`
- Calendar with local data and no account
- Preview over a generated three-page PDF
- Safari and Firefox over guest-local pages
- Notes over disposable local notes
- Terminal for harmless window and menu behavior
- ConnActionFixture for deterministic and adversarial shapes

App-specific setup and independent oracles stay under the lab. Production
selection, policy, lowering, dispatch, and verification remain generic.

## Required jobs

- exact app and window selection
- unique control activation
- selection in lists, tables, outlines, rows, and tabs
- unique non-secure field focus followed by exact typing
- harmless menus and overlays
- document pages and browser history
- bounded scrolling to a named target
- current-window visual fallback when Accessibility has no useful target
- short goals continued through separate observed transactions

An app need not expose every job. Each primitive must succeed in at least
three structurally different exposed surfaces and have one adversarial case
that refuses before dispatch.

## Execution contract

Python owns grants, risk, provenance, context, cost, model limits, and receipt
validation. Conn.app owns signed identity, Accessibility, ScreenCaptureKit,
coordinate conversion, native input, and effect observation.

Every mutation follows the same boundary:

1. Observe current state.
2. Resolve one target.
3. Prepare one bounded plan and compiler-owned proof predicate.
4. Apply risk and grant policy.
5. Re-resolve immediately before dispatch.
6. Dispatch one strategy.
7. Observe again and classify from evidence.

Raw native success never means `verified`. Visual motion is not semantic
proof. A possibly-dispatched or dispatched action never retries
automatically. Secure, destructive, stale, denied, changed-app, and genuinely
ambiguous states refuse.

## Independent truth

Conn's receipt and the oracle are separate records. Browser pages write to the
guest truth server. Notes uses disposable local database state. Finder,
Calendar, Preview, and Terminal use bounded lab-only native or app adapters.
The fixture writes append-only truth events.

An oracle match cannot promote a Conn receipt. It can show that a
`dispatch_only` action worked, or that a native-success receipt had no effect.

## Completion bars

The frozen top twenty must reach:

- at least 19 of 20 on the first attempt
- 20 of 20 after at most one safe clarification or proven-not-dispatched
  replan
- zero wrong targets
- zero false `verified`
- zero stale dispatches
- zero automatic retries after possible dispatch
- a receipt and independent oracle for every dispatch
- no host UI or personal-data change

No replan is safe after a dispatched action. Such a failure remains failed in
both rates.

The native atlas, adversarial fixtures, ordinary suites, live intent corpus,
and exact-candidate twenty-clone release run must also pass. Physical
microphone, hotkey, display, confidence-drill, and daily-use gates remain
separate under `docs/NORTH-STAR.md`.

## Accepted evidence

The frozen breadth gate passed on the exact candidate on 2026-07-21. The core corpus completed 20 of
20 commands on the first attempt and after safe replan. The supporting suite
completed 9 of 9 cases. Together they prove all nine required jobs across at
least three structurally different surfaces, with one source-validated
adversarial refusal per job.

The final command produced 34 receipts from 34 dispatches. Nineteen were
`verified`; ten remained honestly `dispatch_only`. All 29 scenario oracles
matched, no host state changed, and no safe replan was required. Artifact:
`data/lab-runs/2026-07-21/v1-breadth-174932-summary.json`. SHA-256:
`2a6ea748c4e0c7f838f9e3bd3dc8e41b7637f43ee613c7a84296ba9511d13f60`.

Notes next selection closed through a generic structural-peer lane. It binds
the selected row to peers with matching role, subrole, actions, settable
attributes, and compatible geometry. It re-resolves the same collection and
peers before dispatch, verifies an exact peer-index move from 0 to 1, and
refuses stale selection, ambiguity, reordering, duplicate collections, or a
multi-peer jump. The disposable Notes database independently matched the exact
selected object. No Notes command, selector, or stored coordinate entered
production.

Safari and Firefox visual activation remain honest proof ceilings. Their local
page oracles can match one dispatch while Conn reports `dispatch_only` with
`no_trustworthy_witness`. Oracle truth never promotes those receipts.

## Stop rule

Implement only fixes required by red frozen rows. Do not add app command
catalogs, app selectors, saved coordinates, hidden macros, OCR, another model,
MCP, shell execution, destructive work, or outbound actions.

When the written gate passes, capability work stops. It reopens only under the
trigger in `docs/NORTH-STAR.md`.
