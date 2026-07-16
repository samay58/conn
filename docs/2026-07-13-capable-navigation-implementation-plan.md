# Capable navigation implementation plan

Status: approved direction, ready for execution. Updated 2026-07-13.

This is the execution companion to
`docs/2026-07-13-capable-navigation-spec.md`. The spec owns the product
contract. This file owns packet order, code boundaries, test seams, migration,
and release evidence. The failure source is
`docs/2026-07-13-dogfood-failure-analysis.md`.

## Outcome

Conn should complete ordinary reversible Mac navigation after one visible
session grant. It should prefer Accessibility, use native semantic browser or
key actions when they are stronger, and use a short-lived window screenshot
when an important target is not accessible. The user should not approve every
click. Conn should still refuse uncertain, stale, secure, destructive, and
denied actions before dispatch.

Completion means all of the following hold together:

- ordinary app support is based on live installed identity, not a fixed catalog
- model-visible Accessibility results are compact, ranked, and replaceable
- duplicate named targets use the full stable locator before returning
  ambiguity
- visual input is real image content captured and executed only by Conn.app
- direct URLs open in the requested or current browser instead of becoming
  searches
- one signed-app grant covers reversible foreground navigation
- every dispatch is bound to current app, window, observation, plan, and grant
- every non-verified outcome has a stable reason code
- raw native success, screen motion, and user praise never create `verified`
- a possibly-dispatched action never retries
- voice cancellation cannot leak text or audio into the next response

## Starting evidence

The last recorded mechanical baseline is 573 Python tests, 144 Swift tests,
14 of 14 harness evals, and 217 of 219 live intent items. The first execution
session must rerun the baseline and record the exact current counts because the
working tree is uncommitted and may have moved.

Four July 13 post-release sessions contain 29 user turns, 40 proposals, nine
predispatch blocks, and 12 native outcomes. Only three app opens verified.
There were 12 live click attempts across the wider trace set and none reached
dispatch. The implementation must retain these sessions as evidence, not as a
substitute for deterministic fixtures.

The default budget is now $5.00 with a $2.50 warning. Higher headroom does not
relax observation limits, context replacement, or cost accounting.

## Approved decisions

These decisions are closed for this implementation. Reopen them only if a
measured platform constraint makes the specified path impossible.

| Question | Decision |
|---|---|
| Navigation authority | One pointer-granted lease for reversible foreground navigation |
| Consequential actions | Existing one-action pointer approval |
| Destructive actions | Refused in this release |
| App support | Resolve installed apps dynamically through LaunchServices and bind live signing identity |
| Visual grounding | Two-stage goal, capture, constrained grounding, native plan flow |
| Visual execution | Current window by default, normalized region, native revalidation, one event sequence |
| URL schemes | General browser navigation accepts HTTP and HTTPS only |
| Upstream reconnect | Preserve the grant while the daemon session and signed app connection survive |
| App bridge reconnect | Revoke the grant and invalidate prepared plans |
| Lock and sleep | Suspend dispatch and invalidate plans; resume only through the same signed connection after unlock |
| Enter key | Consequential unless live target and effect prove a reversible non-submit context |
| Eye verdict | Explicit sidecar linked by receipt ID; never inferred from speech |
| Visual model | Use the current Realtime model first; do not add a second model or service |
| Rollout | `actions.visual_enabled` remains the kill switch and defaults off until visual gates pass |

Image size, compression, drift tolerance, visual latency, and visual cost bars
must be calibrated in the visual transport packet. The plan defines how to
measure them but does not invent values before a real capture and wire probe.

## Non-negotiable invariants

Python remains the policy plane. Conn.app remains the only production
observation and execution plane. The browser console remains read-only.

- one mutation runs at a time
- every plan re-resolves immediately before dispatch
- mutation `ok` is true only for target-bound verified evidence
- native API success records dispatch, not effect
- uncertain dispatch never falls back or retries
- a model cannot author its risk class, effect class, proof predicate, raw key
  chord, coordinate, app identity, or signing identity
- secure fields, denied bundles, destructive actions, and stale plans refuse
- no production Python Accessibility, screenshot, or input fallback
- no per-app action branches, selectors, coordinates, or command catalogs
- no console grant, approval, initiation, or native RPC ownership
- image bytes, secrets, clipboard bodies, and full native trees never enter a
  trace preview or receipt
- current observations replace stale model-visible observations
- existing trace and receipt versions remain readable

## Code shape

The implementation should deepen the existing modules instead of creating one
file per noun. The public execution surface stays small.

### Swift execution plane

`NativeSemanticActionEngine.perform(op:params:)` remains the bridge entry
point. Extract the current large actor into five deep internal modules while
preserving its external behavior:

- `NativeObservationIndex.swift` owns local snapshots, compact candidate
  search and ranking, descriptor binding, and full-locator re-resolution.
- `NativeActionCompiler.swift` lowers model goals into native plans, resolves
  dynamic app identity, assigns compiler-owned effect classes, and builds
  witnesses.
- `NativeTransactionExecutor.swift` owns the absolute execution deadline,
  fresh revalidation, one dispatch, verification, and complete receipt.
- `NativeVisualControl.swift` owns ScreenCaptureKit capture, capture metadata,
  bounded image encoding, visual-plan revalidation, coordinate conversion,
  and input certainty.
- `NativeApplicationResolver.swift` owns LaunchServices lookup, ambiguity,
  bundle identity, signing identity, current-browser resolution, and exact-app
  URL opening.

`NativeSemanticTypes.swift` remains the shared wire and plan vocabulary.
`NativeSemanticActionEngine.swift` becomes the actor facade and plan-store
coordinator. Do not split production policy into Swift. Do not create thin
wrapper types that only rename one call.

`NativeAXSemanticBackend.swift` may continue to capture a full bounded tree
locally. Full trees do not cross the bridge. Split a backend protocol only
where both the production adapter and fixture adapter need the seam.

### Python policy plane

Keep `ConnApp` as the composition root and the pure session machine free of
grant state.

- new `navigation.py` owns the lease, grant generation, session binding,
  signed app connection binding, suspension, revocation, and policy query
- new `observations.py` validates compact native candidates, builds bounded
  model projections, carries image attachments, and accounts for bytes and
  tokens
- new `artifacts.py` writes atomic valid JSON, bounded previews, hashes, and
  complete sidecars without clipping serialized JSON
- `risk.py` applies compiler-owned effect class plus the active lease
- `native_actions.py` owns goal schemas and validation, never coordinates or
  proof predicates supplied by the model
- `ax_bridge.py` carries explicit observation and visual RPC payloads
- `openai_ws.py` sends explicit image content and owns create/delete state for
  replaceable observation items
- `events.py` carries a typed optional model observation or attachment instead
  of asking the adapter to infer attachments from tool-result strings
- `actions.py` requires explicit reason codes and validates evidence

The current Python `computer_screenshot` executor becomes diagnostic-only and
is removed from the production tool registry when native visual observation is
available. It must not become an emergency fallback.

## Pre-approved test seams

These are the intended behavioral seams. Tests should use them rather than
private helpers or broad mocks.

| Seam | What it proves |
|---|---|
| `NativeSemanticActionEngine.perform`, `prepare_action`, and `execute_action` with production and fixture backends | External native transaction contract |
| `NativeObservationIndex` candidate and resolution results | Ranking, full-locator resolution, refusal, and descriptor freshness |
| `ToolHarness.prepare_call` and `run` plus `ActionReceipt` | Python policy, grant, validation, and retry certainty |
| Realtime adapter outgoing events against the strict fake server | Image input, item replacement, deletion acknowledgement, and wire order |
| Authenticated app WebSocket plus AppState and status menu | Grant ownership, visibility, revocation, and connection generation |
| FakeRealtimeAdapter plus native fixture backend | Goal-level orchestration without live apps |

Every packet starts with a targeted failing behavior test, records the failure,
implements the smallest complete vertical slice, then runs the targeted suite
green. Do not leave permanent expected-failure tests for supported behavior.
Fixture-shape tests may land green in the evidence packet because they prove
the capture, not the fix.

## Core contracts

### Compact candidate query

Extend the native observation query with:

```text
search_terms: [string]
expected_roles: [string]
expected_actions: [string]
scope: current_window | current_app | descendant
ancestor_ref: optional observation ref
result_limit: integer from 1 through 20
include_menu: boolean
```

Return zero to 20 candidates. Each candidate contains an observation ref,
label, role, subrole, supported actions, concise ancestor trail, sibling index
and count, window-relative frame, deterministic score and score reasons, and a
fresh descriptor for clarification. Blank untitled groups do not appear unless
the query supplies strong non-geometry evidence that names them.

The full tree stays in the native observation store. A model-visible candidate
payload and screenshot each have a replaceable observation item identity. A
new item is not considered current until creation succeeds. Superseded items
are deleted only after the replacement is acknowledged.

### Full-locator resolution

Resolution intersects all available evidence before it returns ambiguity:

```text
app and process identity
window identity
semantic fingerprint
identifier
role and supported action
ancestor trail
path and sibling signature
bounded frame drift
```

A unique intersection may resolve repeated named elements. Geometry may narrow
a named semantic candidate. Geometry alone cannot select an anonymous group.
Any reorder, window change, app change, secure transition, or unresolved tie
refuses before input.

Clarification options come from current candidate descriptors. An answer binds
the descriptor intent, takes a fresh observation, and resolves again. After
one failed clarification, Conn changes authorized lanes or returns the measured
ceiling. Equivalent failed plan shapes are bounded across changed node IDs.

### Navigation lease

The signed app menu exposes `Navigation control`. There is no keyboard
equivalent. The app sends an authenticated grant or revoke message. The daemon
creates a lease only for the current daemon session, authenticated app
connection identity, and monotonically increasing grant generation. The app
shows active only after the daemon echoes the accepted state.

Revocation, suspension, app exit, ownership replacement, new daemon session,
or new app bridge connection invalidates all plans compiled under the prior
generation. A late disconnect from an old connection cannot revoke a newer
lease.

The native compiler assigns one of these effect classes:

```text
reversible_navigation
consequential
destructive
secure_or_denied
unknown
```

An active lease auto-authorizes only `reversible_navigation`. Consequential
uses the current pointer approval. All remaining classes refuse. The model
never sees an argument that selects this class.

### Visual observation and plan

Conn.app captures the current target window with ScreenCaptureKit. Full-display
capture requires an explicit screen-wide request or a measured lack of a
single target window. Conn surfaces must be excluded.

Capture metadata includes:

```text
capture ID and digest
app bundle, PID, executable identity, and signing identity
window ID, title, and frame
display ID, point size, pixel size, and scale
turn ID and observation epoch
capture time and expiration
secure or denied state
encoded byte count
```

Python sends actual PNG or JPEG image content as a Realtime image input item.
It never sends a local path. Traces record metadata, digest, size, and token
usage without image bytes.

The model returns a constrained grounding result containing the capture ID,
normalized point or region, target label, and confidence. Conn.app builds the
plan using the original goal, current lease generation, capture digest,
window identity, and compiler-owned effect class.

Before input, Conn.app checks the same frontmost app and window, current frame
and scale, capture age, point bounds, secure state, denied state, and grant
generation. A mismatch dispatches nothing. Once mouse-down or the first key
event occurs, any uncertain failure is `possibly_dispatched` and cannot retry.

Visual change alone does not prove semantic success. Play may verify from a
Play-to-Pause accessible label, playback value, or another target-bound state.
Otherwise a successful visual click remains `dispatch_only`.

### Direct browser navigation

Add `browser_navigate(url, browser_scope)`. Normalize a bare host to HTTPS.
Accept only HTTP and HTTPS. Reject credentials in the authority, control
characters, oversized values, and every other scheme.

Swift resolves the explicit browser or current browser through
LaunchServices, binds its live identity, and opens the URL with that exact
application. It never silently switches to the default browser. The witness
compares normalized current document URL where accessible. A hidden URL yields
`dispatch_only` with `no_trustworthy_witness`.

`browser_search` remains search. Existing dedicated Obsidian behavior remains
separate. `app_open` and `app_switch` use the same dynamic installed-app
resolver. Configured app mappings become alias hints, not authority.

### Deadline and receipt

Policy preparation and pointer approval are outside the native execution
deadline. One absolute deadline starts when execution begins and covers fresh
baseline capture, re-resolution, dispatch, verification polling, receipt
serialization, and delivery to the bridge. Every native operation receives the
remaining time. Nothing resets the deadline.

The Python timeout equals the advertised native deadline plus a measured bridge
delivery margin. A timeout before input is `not_dispatched`. A timeout after
input certainty changes is `possibly_dispatched`. A late diagnostic receipt may
be stored but cannot rewrite the outcome already returned to the model.

Every non-verified receipt has an explicit reason code. Evidence records the
predicate, baseline, current value, match rule, and matched Boolean. Trace
schema changes preserve a legacy reader.

## Packet dependency map

```text
P0 evidence freeze
  -> P1 code shape and evidence truth
    -> P2 bounded observation
      -> P3 full resolver and clarification
        -> P4 dynamic apps and direct navigation
          -> P5 navigation lease and effect policy
            -> P6 visual transport
              -> P7 activation, keys, and visual dispatch
                -> P8 witnesses, deadlines, voice, and receipts
                  -> P9 release evidence
```

Do not start coordinate dispatch before visual transport proves that the model
receives the intended image and that stale image state can be revoked.

## P0: baseline and failure freeze

Purpose: preserve the real failures before changing the engines.

Work:

- run the Python suite, harness eval, Swift suite, and release build; record
  exact counts and any explained warnings
- record a manifest count and digest for `data/`, run the Python suite, and
  prove the manifest is unchanged
- extract minimal sanitized fixtures for the Techmeme `RIVER` duplicates,
  Firefox anonymous groups, Safari nested tab collections, Notes folders plus
  virtualized note lists, and the delayed Notes typing receipt
- add strict Python replay inputs for direct URL routing, Apple Notes relative
  routing, repeated snapshot context, and the barge-in splice
- create a manifest mapping each fixture to source session, spoken command,
  current bad disposition, and intended post-fix disposition
- strip private note titles and text while retaining hierarchy, role, action,
  identity, and timing shape

Primary files:

- new `tests/fixtures/live_failures/`
- new `macos/Tests/ConnTests/Fixtures/`
- new `tests/test_live_failure_replays.py`

Exit:

- fixture-shape and replay-parser tests pass
- every source trace and receipt ID is documented
- the Firefox anonymous shape remains an intended refusal
- no suite writes a new file under the real `data/`
- no live app or daemon has been restarted

## P1: code shape and evidence truth

Purpose: create deep module boundaries without changing supported behavior,
then make reason and artifact contracts complete.

Red tests:

- every non-verified receipt requires a non-empty reason code
- shortened artifact previews remain valid JSON and link to full content
- image, secret, clipboard, and full-tree bodies cannot enter trace previews
- legacy trace and receipt fixtures still parse

Work:

- extract the five Swift modules and three Python modules described under Code
  shape with zero external behavior change
- centralize native outcome and reason-code validation in shared types
- replace nested-string clipping with an atomic artifact wrapper, digest,
  preview metadata, and full sidecar
- keep one source of truth for reason codes and one for observation identity

Primary files:

- `macos/Sources/Conn/NativeSemanticActionEngine.swift`
- `macos/Sources/Conn/NativeSemanticTypes.swift`
- new Swift modules listed under Code shape
- `src/conn/actions.py`
- `src/conn/app.py`
- new `src/conn/artifacts.py`
- `tests/test_action_contract.py`
- `tests/test_trace_truth.py`

Exit:

- targeted red tests are green
- full mechanical suites remain at or above the P0 counts
- bridge fixtures are byte-compatible except for additive reason and artifact
  metadata
- no new public abstraction exists without use in the next packet

## P2: bounded native observation and context replacement

Purpose: stop sending raw trees and stop context from growing with every look.

Red tests:

- `query.search` and all query fields reach the Swift parser
- a search returns ranked matching candidates instead of a full tree
- zero matches return an explicit empty list
- fallback never emits blank anonymous containers
- role, action, app, window, descendant, and limit filters compose
- candidate output never exceeds 20 entries or its byte cap
- 20 repeated observations leave one current semantic item
- replacement create failure leaves the prior acknowledged item current
- superseded deletion follows successful replacement acknowledgement

Work:

- implement `NativeObservationIndex` query and compact candidate DTO
- keep the full tree local in `NativeObservationStore`
- add typed `ModelObservation` attachment to Python events
- carry observation item identity explicitly through the adapter
- account for candidate bytes, input tokens, output tokens, and per-turn cost
- preserve full local artifacts without sending them to the model

Primary files:

- `macos/Sources/Conn/NativeSemanticTypes.swift`
- `macos/Sources/Conn/NativeObservationStore.swift`
- `macos/Sources/Conn/NativeObservationIndex.swift`
- `src/conn/events.py`
- `src/conn/ax_bridge.py`
- `src/conn/observations.py`
- `src/conn/realtime/openai_ws.py`
- `tests/test_ax_bridge.py`
- `tests/test_realtime_wire.py`
- `NativeCandidateQueryTests.swift`

Exit:

- model-visible native output contains no `nodes` array
- real fixtures return zero to 20 useful candidates
- one current semantic observation survives repeated looks
- the cost report shows no linear semantic-context growth
- the Firefox query returns zero useful targets rather than anonymous groups

## P3: full resolver, clarification, and loop stop

Purpose: use stable structure before declaring ambiguity while preserving
refusal for genuinely indistinguishable targets.

Red tests:

- repeated titled `RIVER` links with one unique full locator resolve correctly
- two candidates with complete valid locators remain ambiguous
- anonymous full-window groups remain ambiguous
- reorder, move, window change, app change, or secure transition refuses
- geometry alone never selects an anonymous candidate
- clarification choices exactly match current descriptors
- a clarification answer takes a fresh observation and binds a descriptor
- equivalent failed plans stop after one clarification despite new node IDs

Work:

- evaluate the full evidence intersection before ambiguity
- separate stable descriptor binding from ephemeral node refs
- add loop signatures based on goal, descriptor, lane, and plan shape
- make clarification wording derive only from real current candidates

Primary files:

- `macos/Sources/Conn/NativeObservationStore.swift`
- `macos/Sources/Conn/NativeObservationIndex.swift`
- `macos/Sources/Conn/NativeSemanticActionEngine.swift`
- `src/conn/app.py`
- `src/conn/prompt.py`
- `NativeObservationStoreTests.swift`
- `NativeSemanticActionEngineTests.swift`
- `tests/test_semantic_intents.py`

Exit:

- the `RIVER` fixture resolves the structurally unique target
- every adversarial drift or genuine-tie fixture refuses before dispatch
- no repeated-snapshot loop survives the fixture replay
- no geometry-only anonymous target can compile

## P4: dynamic apps, direct navigation, and routing

Purpose: remove the fixed app catalog as a support gate and distinguish direct
navigation from search.

Red tests:

- a normal installed app outside config resolves and binds its identity
- duplicate app names produce real candidates for one clarification
- denied bundles and unprovable signing identity refuse
- signer and bundle identity are checked again at execution
- an incomplete `Open` request asks rather than guessing an app
- a URL remains a URL and does not become a Google query
- explicit Safari opens in Safari, not the default browser
- current browser is honored when no browser is named
- unsupported schemes, credentials, control characters, and oversized URLs
  refuse
- normalized document URL verifies; hidden URL remains dispatch-only
- Apple Notes relative language outranks the Phoenix named-note rule
- explicit search wording still uses `browser_search`

Work:

- implement `NativeApplicationResolver` once and reuse it for open, switch,
  direct navigation, and current-browser identity
- add `browser_navigate` to the model surface and native compiler
- downgrade configured app entries to aliases and expected identity hints
- add compiler-owned document URL witness
- tighten prompt routing precedence and live intent corpus contrasts

Primary files:

- `macos/Sources/Conn/NativeApplicationResolver.swift`
- `macos/Sources/Conn/NativeActionCompiler.swift`
- `macos/Sources/Conn/NativeAXSemanticBackend.swift`
- `src/conn/tools/registry.py`
- `src/conn/tools/native_actions.py`
- `src/conn/prompt.py`
- `evals/intent_corpus.json`
- `InstalledAppResolverTests.swift`
- `SemanticIntentTests.swift`
- `tests/test_semantic_intents.py`

Exit:

- safe app support no longer depends on a static config entry
- duplicate installed names clarify and denied identities refuse
- direct URLs open in the exact resolved browser in fixture tests
- every unverified browser result has a specific reason
- the targeted and full intent corpus meet their existing bars

## P5: navigation lease and effect policy

Purpose: grant broad reversible authority once without widening destructive or
unknown actions.

Red tests:

- grant defaults off and plans cannot claim it
- only the authenticated signed app connection can grant or revoke
- the browser console cannot grant, approve, or forge lease state
- active lease removes repeat approval for reversible fixture actions
- consequential actions still wait for one pointer approval
- destructive, secure, denied, and unknown actions refuse
- revoke, suspension, app exit, daemon session end, and new app connection
  invalidate prepared plans
- old-client disconnect cannot revoke a newer lease
- upstream Realtime reconnect preserves the lease
- lock or sleep suspends dispatch and invalidates current plans

Work:

- implement the Python lease and authenticated bridge messages
- add the pointer-only status menu toggle and echoed AppState status
- assign native compiler-owned effect classes
- gate prepared plans by lease generation and effect class
- revalidate lease generation immediately before native input

Primary files:

- new `src/conn/navigation.py`
- `src/conn/app.py`
- `src/conn/server/http.py`
- `src/conn/tools/risk.py`
- `src/conn/tools/harness.py`
- `macos/Sources/Conn/StatusItemController.swift`
- `macos/Sources/Conn/AppState.swift`
- `macos/Sources/Conn/DaemonClient.swift`
- `macos/Sources/Conn/NativeActionCompiler.swift`
- `tests/test_bridge_security.py`
- `tests/test_risk_gates.py`
- `tests/test_action_provenance.py`
- `NavigationGrantTests.swift`

Exit:

- ten reversible fixture actions run under one grant with zero repeat approvals
- revoke blocks the next action before dispatch
- the excluded-effect matrix remains unchanged or narrower
- the grant state is visible and truthful in the app
- no keyboard, voice, console, or model path can grant navigation

## P6: native visual transport

Purpose: prove the image path before permitting coordinate input.

Red tests:

- Conn.app captures the current target window and excludes Conn surfaces
- capture metadata retains digest, dimensions, scale, window, app, and time
- the model receives actual image content, not a path
- a replacement image leaves only one current image item
- image bytes never appear in trace, receipt, report, or console payload
- disabled visual control, Screen Recording denial, secure state, or no target
  window returns a stable measured ceiling
- the bridge payload and encoded image respect explicit size limits

Work:

- implement ScreenCaptureKit capture in `NativeVisualControl`
- add an authenticated `observe_visual` bridge operation
- carry the image as typed Realtime input and record token usage
- retire the production Python screenshot executor
- keep `actions.visual_enabled` false until the packet gates pass
- run one tiny billed image-input wire probe with no UI action
- measure candidate image sizes, quality, token cost, latency, and window-frame
  drift on the native visual fixture
- select the smallest image profile that preserves target grounding accuracy

Primary files:

- `macos/Sources/Conn/NativeVisualControl.swift`
- `macos/Sources/Conn/DaemonClient.swift`
- `src/conn/ax_bridge.py`
- `src/conn/observations.py`
- `src/conn/realtime/openai_ws.py`
- `src/conn/tools/registry.py`
- `tests/test_realtime_wire.py`
- `tests/test_ax_bridge.py`
- `tests/test_trace_truth.py`
- `NativeVisualObservationTests.swift`

Exit:

- the current Realtime model accepts the bounded image input
- one current image replaces stale images without context growth
- no image bytes leak through evidence surfaces
- permission denial produces an honest ceiling
- measured image profile, drift tolerance, latency, and cost are recorded
- if the current model rejects image input, stop for a product decision before
  adding another model or service

## P7: semantic activation, keys, and visual dispatch

Purpose: complete the Firefox video and similar opaque-control tasks through
one goal-level action surface.

Red tests:

- an accessible Play target compiles to AXPress
- an opaque player requests visual grounding under the active lease
- explicit Space compiles to the bounded semantic key lane
- stale capture, changed window, changed frame or scale, expired grant, secure
  state, denied app, or out-of-bounds point dispatches nothing
- multi-display point and pixel conversion is exact
- an AX hit-test that conflicts with the visual label refuses
- click, double-click, right-click, scroll, and supported keys each have one
  bounded native event sequence
- failure after first input is possibly-dispatched and never retries
- screen motion alone cannot verify Play
- Play-to-Pause or target-bound playback state may verify

Work:

- add goal-level `computer_activate` with mutually exclusive semantic target or
  visual grounding flow
- add `computer_key` with a fixed semantic enum, not arbitrary chord strings
- keep legacy `computer_click` during compatibility tests, then hide it from
  the default model surface after activation reaches parity
- compile normalized visual regions into native plans under original provenance
- dispatch through `NativeTransactionExecutor` with input certainty recorded
- add the visual fixture target and independent truth log

Primary files:

- `src/conn/tools/registry.py`
- `src/conn/tools/native_actions.py`
- `src/conn/tools/risk.py`
- `macos/Sources/Conn/NativeActionCompiler.swift`
- `macos/Sources/Conn/NativeTransactionExecutor.swift`
- `macos/Sources/Conn/NativeVisualControl.swift`
- `macos/Sources/ConnActionFixture/`
- `tests/test_native_action_protocol.py`
- `tests/test_grounded_gates.py`
- `VisualPlanTests.swift`
- `NativeKeyChordTests.swift`

Exit:

- the Firefox replay reaches exactly one safe dispatch under an active grant
- stale visual plans never reach native input
- the adversarial visual fixture matrix has zero wrong targets and zero false
  verified outcomes
- successful action without trustworthy effect evidence stays dispatch-only
- legacy raw click and hotkey tools are hidden diagnostics, not parallel
  production paths

## P8: witnesses, deadlines, voice isolation, and evidence linkage

Purpose: close the remaining known reliability failures before live acceptance.

Red tests:

- Safari nested and multi-collection tab shapes select the unique compatible
  collection
- unrelated descendant changes cannot verify tab creation
- Notes folders plus one note list verify; two genuine note lists refuse
- a virtualized list identity change verifies only through target-bound evidence
- a native result at the old 2,701ms edge reaches Python before transport
  timeout
- predispatch timeout is not-dispatched; post-input timeout is possibly
  dispatched and final
- late notification or receipt does not extend the deadline or cause retry
- every non-verified outcome and predispatch refusal has a stable reason
- cancelled transcript and audio cannot prefix the next response
- current app context outranks generic note routing
- narration never claims the whole goal after only a partial dispatch
- probe eye verdicts link by receipt ID without rewriting machine outcome

Work:

- generalize collection witness scoring with genuine-tie refusal
- use one absolute native execute deadline and measured bridge margin
- include baseline, current, rule, and match in predicate evidence
- clear unfinished response buffers immediately on cancellation and retain a
  cancelled-response tombstone for late events
- add explicit eye-verdict sidecars to probe and manual evidence
- bump trace schema additively and retain the legacy reader

Primary files:

- `macos/Sources/Conn/NativeActionCompiler.swift`
- `macos/Sources/Conn/NativeTransactionExecutor.swift`
- `macos/Sources/Conn/NativeSemanticActionEngine.swift`
- `src/conn/app.py`
- `src/conn/actions.py`
- `src/conn/state.py`
- `src/conn/realtime/openai_ws.py`
- `src/conn/trace.py`
- `tests/test_state_machine.py`
- `tests/test_voice_turn_integrity.py`
- `tests/test_receipt_incremental.py`
- `SemanticIntentTests.swift`

Exit:

- all Safari and Notes adversarial witnesses have zero false verification
- the delayed Notes case has no Python timeout cliff
- every unverified result has a stable reason and complete evidence
- the exact barge-in splice replay contains only the new refusal
- July 12 strict cassette and legacy artifacts remain green

## P9: release evidence and candidate handoff

Purpose: prove the complete system before asking for the manual drill and
30-command product gate.

Mechanical commands:

```bash
cd /Users/samaydhawan/conn
PYTHONPATH=src .venv/bin/python -m pytest tests -q
PYTHONPATH=src .venv/bin/python -m pytest tests -m lifecycle -q
PYTHONPATH=src .venv/bin/python -m conn --eval
PYTHONPATH=src .venv/bin/python -m conn --latency-report

cd macos
DEVELOPER_DIR=/Applications/Xcode-beta.app/Contents/Developer swift test
./make-app.sh
cd ..
git diff --check
```

Run the targeted 25-item live intent sample after prompt and schema changes.
Run the full billed corpus once when the surface is stable. Record its artifact,
rate, residual misses, and per-turn cost distribution. Do not change an honest
grader merely to raise the score.

Run `check` once against the complete diff and fix validated findings. Do not
run a separate security scan in this session. Existing security and invariant
regressions remain part of the ordinary suites.

Only after mechanical green, install and verify the candidate:

```bash
cd /Users/samaydhawan/conn/macos
./make-app.sh install
codesign --verify --deep --strict --verbose=2 /Applications/Conn.app
```

Do not kill or restart a running Conn.app or daemon. If the app is running,
report that a human relaunch is required to load the installed build.

Live evidence order after relaunch:

- native visual fixture capture, stale-frame refusal, and safe activation
- direct Safari URL and new tab
- Notes create, relative selection, and harmless typing
- Firefox Play through Accessibility, Space, or the visual lane
- acoustic barge-in check
- `docs/MANUAL-TESTING.md` confidence drill
- 30-command product gate across three ordinary work sessions

The first four are engineering evidence. The last three contain required human
judgment. A probe records the machine receipt and a separate eye verdict. Do
not call a live action verified without the receipt.

Release bars:

- zero wrong targets
- zero false verified outcomes
- zero stale dispatches
- zero automatic retries after possible dispatch
- 100 percent stable reason codes on non-verified outcomes
- at least 95 percent first-try completion across the supported engineering
  corpus
- at least 99 percent completion after one safe clarification or replan
- warm semantic release-to-effect p50 at most 2.0s and p95 at most 4.0s
- measured visual latency and cost reported against the P6 baseline
- at least 90 percent of supported actions in the 30-command product gate are
  faster than hands or useful while hands are occupied
- every machine `verified` agrees with its independent eye verdict

An eye-matched dispatch-only action can count as user-goal completion for the
product usefulness tally. It cannot count as machine verified.

## Migration and rollback

- new config fields must have safe defaults; old config remains readable
- navigation grant defaults off and is never restored across a new daemon or
  app execution connection
- visual control remains behind `actions.visual_enabled`
- grant revocation invalidates every prepared plan from the old generation
- trace and receipt schema additions preserve legacy readers and fixtures
- legacy raw menu, click, key, and screenshot tools stay diagnostic-only during
  migration and leave the default model surface after parity
- Screen Recording denial returns a measured ceiling; it never falls back to
  Python capture or input
- app resolution remains capability-based and generic
- if image input or coordinate revalidation fails its packet gate, disable the
  visual flag and retain the semantic improvements
- an installed build is not authority to restart a live user process

## Documentation closeout

Update documentation only when implementation evidence changes the facts.

- `docs/STATE-OF-PLAY.md` gets exact final counts, artifacts, live ceilings,
  and remaining human steps
- `docs/NEXT-SESSION.md` advances to the first incomplete packet or human gate
- `docs/2026-07-07-roadmap.md` records that visual control was promoted by the
  July 13 failure trigger
- `docs/idea-ledger.md` changes the visual lane from deferred to active, with
  acceptance still open
- `docs/MANUAL-TESTING.md` adds lease, dynamic app, direct URL, visual control,
  and grant-revocation cases only after those paths exist
- `docs/LIVE_EVAL_CHECKLIST.md` distinguishes genuine final ambiguity from AX
  ambiguity safely resolved through current visual grounding

Never leave a green claim in documentation after a later live session has made
it false.

## No-slop delivery gate

Apply this before each packet handoff and once across the complete diff:

- no em dash in added text, comments, commit subjects, or PR text
- no decorative separators, banner comments, or restating docstrings
- no generic wrappers, speculative protocols, or one-method files without a
  current packet use
- no duplicated policy in Swift or guessed execution facts in Python
- no app-specific production branch, selector, coordinate, or command catalog
- no hardcoded visual coordinates
- no dead config flags or compatibility paths left model-visible
- comments explain an invariant, platform constraint, or named incident
- tests assert behavior at the approved seam, not private implementation shape
- fixtures are minimal, sanitized, adversarial, and linked to real evidence
- every new failure branch has one stable reason code
- every loop and payload has a bound
- every model-visible observation has replace and revoke semantics
- exact counts and artifacts replace adjectives such as robust or complete
- `git diff --check` passes
- a search over added lines finds no forbidden wording or em dash
- the final diff receives one focused `check` review

The fresh session should not stage, commit, push, stash, reset, clean, or delete
user work unless the user gives that instruction in that session.
