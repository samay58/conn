# Conn voice-first reliability program

Status: proposed 2026-07-12 after live dogfooding; adversarially reviewed and
approved for implementation 2026-07-13. This spec extends and,
where stated, supersedes the model-facing action design in
`docs/2026-07-09-verified-action-engine-spec.md`. The verified transaction
kernel, Python policy ownership, native execution ownership, pointer-only
approval, and evidence-backed completion rules remain mandatory.

Verification note, 2026-07-13. Every causal diagnosis below was re-verified
against the July 12 artifacts and current source before implementation. One
finding changes how the numbers must be read: the session's daemon outlived
the app (the restart-ownership defect this spec diagnoses), so the trace
file was still growing the next day and every count depends on where the
file is cut. Anchored to the first upstream session (start through the
60-minute duration close), the failed dogfood shows 16 physical PTT cycles
and 41 upstream errors: 17 item-create rejections, 16 delete failures, 7
cancellations refused for lacking an active response, 1 duration close. The
error class shares are stable at any later cut. Two of the 17 create
rejections came from `send_tool_result`, which mints the same 36-character
`ctx_` IDs for snapshot-bearing tool results (15 came from turn context);
the item-lifecycle fix must cover both paths. Five of the 16 cycles
produced no transcript, all sub-300ms holds between 33 and 281ms discarded
by the duration-only tap rule; a 392ms hold was accepted and transcribed. Scope
rulings from the same review: R4 counterfactual scoring means recording
ranked candidates in the trace, not preparing full alternative plans, and
the empirical support envelope is recorded evidence only, with no runtime
suppression until recorded failures justify it.

## Decision

Conn is safe enough to refuse uncertain actions. It is not yet useful enough
to be a daily voice-first control surface.

The next program will replace model-authored action mechanics with a
capability-compiled semantic control loop:

```text
one physical PTT gesture
        |
validated voice turn and current context
        |
bounded semantic intent
        |
live native capability report
        |
locally compiled target, strategy, risk, and effect witness
        |
one verified action transaction
        |
verified result, one safe repair, or one useful clarification
```

The Realtime model describes the user's goal. Conn's local policy and native
planes decide how, whether, and how to prove it. The model will not choose raw
keys, AX mechanisms, menu traversal, risk, or low-level effect predicates for
ordinary actions.

This is not a command catalog, a macro engine, or a visual computer-use
system. It is a smaller deterministic waist between flexible language and
verified native actions.

## Why this program exists

The July 12 live session exposed a gap between mechanical safety and product
reliability.

Primary evidence:

- Trace: `data/traces/2026-07-12/session_a4f5c83703.jsonl`
- Receipt: `data/receipts/2026-07-12/session_a4f5c83703.json`
- Daemon log: `data/logs/daemon-2026-07-12.log`
- Current action probes under `data/action-probes/`
- Current scripted eval artifact under `data/evals/2026-07-12/`

The latest live trace contains:

| Signal | Observed |
|---|---:|
| Physical PTT cycles | 16 |
| Completed input transcripts | 11 |
| Model responses | 21 |
| Tool proposals | 10 |
| Tool executions | 5 |
| State-changing proposals | 7 |
| Verified state-changing actions | 2 |
| Mutations blocked before dispatch | 5 |
| Upstream protocol errors | 41 |

The two app opens verified. Every in-app navigation or creation attempt failed
before dispatch. Notes next-item navigation never executed. Safari New Tab
failed across repeated attempts.

The user experienced a system that could occasionally do something impressive
but could not complete ordinary work predictably. That is the product problem
this spec solves.

## Diagnosed failure classes

### Realtime turn context is broken

`src/conn/realtime/openai_ws.py` creates semantic context IDs as `ctx_` plus a
32-character UUID. The result is 36 characters. The live API rejected every
one because item IDs are limited to 32 characters.

The adapter then remembered the rejected ID and tried to delete it on the next
turn. The session produced 17 create errors (15 turn contexts plus 2
snapshot-bearing tool results, which take the same ID-minting path in
`send_tool_result`), 16 delete errors, and 7 cancellations rejected because no
response was active. Local traces claimed context was observed even though the
model never received it.

The current test captures outgoing JSON. It does not enforce the live wire
contract or wait for server acknowledgement.

### The model and native action contracts contradict each other

The model-facing schemas expose `desired_effect` for `app_menu` and
`computer_hotkey`. The native engine's `desiredEffectTargetsAction` returns
false for every caller-supplied effect on menu and key-chord operations.

Four recent proposals supplied the field exactly as the schema encouraged.
All four were rejected as `invalid_effect_target` before dispatch.

The model also chose `cmd+n` for New Tab and `cmd+\`` for the next Notes item.
Prompt examples did not make live strategy selection reliable.

This is not an AX failure. It is an impossible contract.

### The model owns decisions it cannot reliably make

For an ordinary command, the current model may need to choose:

- whether to read context
- whether to snapshot
- which tool family to call
- the exact menu path or key chord
- the target ref
- the desired effect predicate
- whether and how to recover

Each choice can be locally derived or constrained by current native state.
Leaving all of them to a stochastic audio model creates needless variance.

### Safe repair is structurally awkward

Preparation failures can be proven `not_dispatched` and marked retry-safe, but
the state machine closes the mutation chain after every non-verified mutation.
The model then improvises across extra responses or waits for the user to
repeat the command.

The latest New Tab turn used three model responses, attempted two invalid
plans, and still did nothing. The user paid latency, attention, and token cost
for a developer-contract failure.

### Audio turn isolation is suspect

`src/conn/audio.py` intentionally has no echo cancellation. While the mic gate
is closed, its 400ms pre-roll ring continues recording. During model playback,
that ring can contain Conn's own voice. A barge-in opens the gate and uploads
the ring before live speech.

Recent transcripts began with unexplained prefixes such as `in front mode`,
`descend`, and `acquired`. This does not prove echo, but the code path predicts
the observed shape. It needs a recorded PCM test and live confirmation.

Five of 16 PTT cycles produced no transcript. All were sub-300ms holds between
33 and 281ms, discarded by the fixed duration-only tap rule; a 392ms hold was
accepted and transcribed. The tap rule can silently discard a short voiced
command while the app still shows a panel.

### Restart ownership is still unreliable

The daemon log contains six port 8787 bind failures. A normal app quit can
leave its token-bound daemon alive. A new signed app correctly refuses to
adopt that daemon but cannot recover without manual cleanup.

Authentication is working. Ownership and lifecycle are not.

### Verification polling is safe but latency-brittle

Python's native bridge timeout is fixed near two seconds while some native
action budgets run up to four seconds. Swift may repeatedly recapture hundreds
of AX nodes during verification. A slow valid action can outlive the Python
request, become `possibly_dispatched`, and finish after the caller has given
up.

The verifier should read a targeted witness set with an action-aligned RPC
deadline. It should not poll a large tree every 25ms.

### The green gates do not measure the user goal

The 13 harness evals use a scripted Realtime adapter and mostly fake
executors. One case expects a menu action to fail and still passes. The
1,000-transaction test uses an in-memory Swift backend. The real fixture probe
covers a narrow no-effect case.

Those tests prove valuable safety mechanics. They do not prove:

- voice turn capture
- speech interpretation
- live tool selection
- valid action arguments
- current context delivery
- end-to-end recovery
- ordinary task completion
- long-session stability
- restart reliability
- truthful spoken output

### Current observability hides the user experience

The trace records only the first model delta's modality, not the assistant's
spoken words. The latest session therefore cannot prove whether completion
language was truthful.

Other gaps:

- physical app PTT frames are labeled `console`
- `ui_ack` is defined but not wired from the primary Swift surface
- receipts call model responses `turns`
- blocked proposals are omitted from tool-call counts
- latency reports use the first matching session event instead of per-turn
  distributions
- tool result output is truncated without a linked full artifact
- probe files omit commit, build, config, and schema identity
- daemon logs lack timestamps, PID, parent PID, build, and exit reason
- `fixture-verified-*` filenames can contain a `no_effect` outcome

## Product definition

Conn becomes a usable voice-first agentic operating layer when it can do three
things together:

1. Understand a short ordinary command in the current Mac context.
2. Complete the intended action or ask one useful question.
3. Tell the truth about what happened.

Safety without useful completion is not enough. Broad language understanding
without bounded execution is not enough. The product requires both.

## Invariants

The existing verified-action invariants stay in force:

- Python owns policy, risk, approval, provenance, serialization, and model
  continuation.
- Conn.app owns production macOS observation, resolution, dispatch, and
  evidence collection.
- A raw native success cannot produce `verified`.
- `Done.` requires evidence-backed `verified`.
- `possibly_dispatched` never retries automatically.
- One equivalent strategy fallback is allowed only after proven
  `not_dispatched`.
- Every mutation re-observes and re-resolves immediately before dispatch.
- Stale turns, responses, observations, plans, and refs never execute.
- Secure fields and denied bundles remain blocked.
- Approval remains pointer-only and binds the exact plan.
- One mutation executes at a time.
- No visual coordinate fallback is added by this program.

New reliability invariants:

- One physical PTT gesture creates at most one accepted user turn.
- An accepted voiced turn is never silently discarded.
- Context is considered injected only after the upstream item is acknowledged.
- The model expresses semantic intent, not action mechanism or proof syntax.
- Compiler-owned predicates may narrow or refuse. They may never broaden risk.
- A predispatch compiler failure does not consume the one-dispatch budget.
- One safe replan is allowed only after `not_dispatched` and fresh observation.
- The same failed plan shape is never proposed twice in one user turn.
- An unexplained user-facing `Did not run.` is a product defect.
- Empirical support history may downgrade or hide a capability. It may never
  upgrade permission, target certainty, or verification.

## Strategy decision

Five approaches were considered.

| Approach | Benefit | Fatal weakness | Decision |
|---|---|---|---|
| Patch current schemas and prompts | Fastest initial relief | Leaves model responsible for mechanism, proof, and recovery | Use only for immediate defects |
| Large app command catalog | Deterministic for covered commands | Version-brittle, narrow, and expensive to maintain | Reject |
| Vision-first computer use | Broad visual coverage | Higher wrong-target risk, latency, and weak effect truth | Defer |
| Direct APIs, App Intents, or MCP first | Strong contracts where available | Fragmented Mac coverage and expands current scope | Later breadth plane |
| Capability-compiled semantic intents | Flexible language with deterministic local planning | Requires a careful small intent algebra | Adopt |

The selected design keeps task-shaped tools but changes their contract. The
model names the desired operation and semantic target. Local code observes
capability, resolves the target, selects a strategy, binds evidence, applies
risk, and executes one transaction.

## Target architecture

### Turn ingress

Create one `TurnIngress` record for every physical PTT gesture:

```text
turn_id
client gesture id
source: app_hotkey | console | typed
down and up monotonic timestamps
held duration
captured frame count
peak and voiced energy
playback active at press
pre-roll included or suppressed
context item state
transcription state
accepted or rejected reason
```

Rules:

- The Swift app sends a unique gesture ID and `source=app_hotkey` on both
  edges.
- Duplicate modifier events are idempotent.
- Playback is flushed locally before a barge-in mic gate opens.
- Pre-roll captured while model playback is active is discarded.
- The ring restarts with clean live mic frames after playback stops.
- A short hold with voiced energy is accepted. Duration alone cannot discard
  it.
- A rejected tap receives immediate visible feedback and a trace event.
- The primary Swift surface clears prior user and model lines at turn start.

Do not add continuous VAD or ambient listening. PTT remains the authority.

### Realtime protocol ledger

Add a small acknowledged item ledger inside the adapter.

It tracks:

- client event ID
- client item ID when supplied
- server item ID
- create sent, created, delete sent, deleted, or failed
- owning turn and observation epoch
- active response ID and lifecycle

Rules:

- Generated IDs obey the current API limit and have contract tests.
- Prefer server-generated item IDs when a custom ID is unnecessary.
- Never delete an item until its creation is acknowledged.
- A failed create never becomes current semantic context.
- Cancel only an active response, include its response ID, and record the
  reason.
- Nonfatal upstream errors are correlated to the client event that caused
  them.
- The session has zero expected protocol errors during normal use.

Use a strict local fake Realtime server in tests. It must enforce current
length limits, acknowledgement order, missing-item delete behavior, response
state, and terminal event shapes. A capturing mock is insufficient.

### Semantic intent algebra

The model-facing mutation vocabulary becomes task-shaped and bounded.

Initial intent families:

```text
open_app(app)
switch_app(app)
create(kind, scope?)
select(target, scope?)
select_relative(relation, kind?, scope?)
activate(target, scope?)
invoke_command(command, scope?)
set_text(target, text, submit?)
scroll(target, direction?, amount?)
clipboard_write(text)
```

Examples:

- `Open Safari` becomes `open_app(app=Safari)`.
- `Open a new tab` becomes `create(kind=tab)`.
- `Go to the next note` becomes
  `select_relative(relation=next, kind=document)`.
- `Show the sidebar` becomes `invoke_command(command=Show Sidebar)`.
- `Press Refresh` becomes `activate(target={name: Refresh, role: button})`.

Target descriptors may contain only bounded semantic slots:

- exact or normalized name
- optional role family
- focused target relation
- frontmost window scope
- named app scope
- nearby named ancestor when needed

Raw snapshot refs, exact menu paths, key chords, AX action names, native
strategies, risk classes, and effect predicates are not model-visible for
ordinary actions.

Read-only inspection remains available when language alone cannot name a
target. It returns a small semantic rendering, not native identity authority.

Keep explicit raw menu and hotkey tools only as policy-gated diagnostic escape
hatches. They are not advertised in the default Realtime tool set and cannot
produce verified success from dispatch alone.

### Native capability report

Before preparing a mutation, Conn.app returns a bounded `CapabilityReport`
bound to the current turn and observation epoch.

It contains:

```text
app and process identity
stable window identity
intent family
normalized semantic target candidates
candidate role and safe description
unique, ambiguous, secure, denied, or unavailable state
supported semantic operations
live menu path and shortcut when discovered
available strategy classes
available effect witnesses
expected outcome ceiling: verified | dispatch_only | blocked
staleness boundary
```

Reports contain 5 to 20 ranked candidates, not the whole AX tree. Ranking may
use exact normalized title, role compatibility, focus, semantic ancestry, and
live capability. Geometry can confirm a candidate but cannot break a semantic
tie.

The report is descriptive. It cannot authorize an action. Python applies the
risk floor after the native plan exists.

### Intent compiler

The compiler turns one intent and one current capability report into one
`PreparedAction`.

Compilation order:

1. Direct deterministic OS API when the intent has one.
2. Unique native semantic target and operation.
3. Exact live menu command discovered from the current menu tree.
4. Live shortcut exposed by that exact menu item.
5. Dispatch-only plan when policy permits but no causal witness exists.
6. Clarify or refuse.

The compiler may prepare multiple candidates without dispatching. It ranks
them by:

1. unique target
2. available causal witness
3. semantic strategy over raw event posting
4. lower uncertainty
5. lower measured latency

Only one authorized plan executes. Counterfactual candidates are trace and
offline-eval data. Their predictions are never effect evidence.

No per-app command catalog is allowed. A small generic command grammar may
interpret stable verb and object classes such as create tab, close window,
select next document, or toggle sidebar. The compiler must still confirm the
corresponding live native affordance in the current app.

### Effect witness compiler

The model no longer writes `desired_effect` predicates.

The native compiler selects a bounded witness set from the resolved intent,
target, operation, and current state. Witness families include:

- expected frontmost bundle
- selected or focused target
- target value or attribute change
- text hash or bounded non-secure value
- clipboard hash
- tab or document collection count and selected identity
- focused window identity
- owned sheet or window creation
- exact window title or document URL transition when tied to the intent
- live menu item's mark or checked state
- bound AX notification plus a targeted confirming reread

Every witness records a read set. Verification rereads only that set and any
small owning collection. A broad layout change, arbitrary window change,
menu close, or unrelated notification remains insufficient.

For commands with no safe witness, the compiler may prepare a
`dispatch_only` plan if risk policy allows. It must not reject an otherwise
valid action merely because the model supplied a bad predicate, because the
model no longer supplies predicates.

### Adaptive transaction timing

The native plan declares:

- preparation deadline
- dispatch deadline
- verification deadline
- witness reread schedule
- overall bridge deadline

Python's bridge deadline must be the native overall budget plus bounded
transport margin. It cannot be shorter than the authorized native work.

Verification uses notification hints and targeted reads with adaptive
backoff, for example 50ms, 100ms, 200ms, then bounded final reads. Full-tree
recapture is a fallback for explicit small scopes, not the default loop.

Cancellation can abort before dispatch. After dispatch, timeout preserves
`possibly_dispatched` semantics.

### Risk model for voice-first use

Risk is based on effect class, not input mechanism.

| Effect class | Examples | Default |
|---|---|---|
| Read | context, snapshot, search | Auto |
| Reversible navigation | switch app, select tab, next document, scroll | Auto |
| Reversible local creation | new empty tab or window | Auto when exact and bounded |
| Local content mutation | type text, toggle setting, clipboard write | Existing policy or pointer confirmation |
| External side effect | send, publish, purchase, account change | Pointer confirmation or blocked |
| Destructive | delete, overwrite, irreversible command | Blocked until separately specified |

Python sets the floor. Native capability may escalate risk based on the live
target. It may never downgrade the floor.

Generic raw menu invocation remains confirm-gated unless it compiles to a
typed intent with a lower approved effect class.

### Bounded repair coordinator

Action preparation and execution return structured reason codes:

```text
reason_code
dispatch_state
retry_safe
attempt_index
repair_kind
repair_candidates
safe_user_message
```

Repair rules:

- Schema or compiler bug: fail the test gate. Do not ask the user to repeat.
- Stale observation before dispatch: observe once and recompile.
- `not_dispatched` with one equivalent candidate: one replan may run.
- Ambiguous target: ask one bounded clarification using safe candidate names.
- Unsupported verified witness: offer a truthful dispatch-only action only
  when policy permits and the user has not prohibited it.
- `dispatched` with no effect: stop. Do not retry.
- `possibly_dispatched`: stop and tell the user to inspect before any retry.
- Same reason and plan shape twice: stop the loop and surface the limitation.

One user goal may span several verified mutations, but each step is a separate
transaction with a fresh observation. This is checkpointed orchestration, not
a macro. The first non-verified step stops automatic progress.

### Useful failure language

The user-facing vocabulary expands beyond three opaque labels while keeping
internal details out of speech.

Examples:

- `Done.`
- `I found two Save buttons. Which one?`
- `Notes changed before I could act. Try again.`
- `I sent it, but could not confirm it worked.`
- `The action may have been sent. Check before retrying.`
- `Conn lost its app connection before sending anything.`

Do not speak AX terms, internal codes, fingerprints, or strategy names.

The island may retain the three visual outcome classes, but its supporting
line should show the safe reason and next move when available.

### Empirical support envelope

Track reliability by:

```text
bundle id + signed app version + intent family + target role + witness family
```

States:

- proven
- experimental
- unsupported
- regressed

Runtime capability remains authoritative. History can downgrade or suppress a
path that repeatedly fails. It cannot turn an ambiguous target into a unique
one or dispatch into verification.

This is not online self-modifying policy. Promotion and regression require
recorded evidence and reviewed tests.

## Failure foundry

Every real failed turn should become a small local artifact that can be
replayed or labeled.

Required fields:

- correlation ID
- commit, signed build, config fingerprint, and schema version
- user turn and PTT timing
- sanitized transcript and transcription confidence when available
- app and window identity
- semantic intent
- capability report summary
- prepared candidates and selected plan
- risk and approval result
- dispatch and evidence receipt
- assistant's exact spoken transcript
- human verdict when supplied
- pipeline failure category

Failure categories:

- voice capture
- transcription
- turn or context transport
- intent selection
- capability discovery
- target resolution
- plan compilation
- risk or approval
- dispatch
- verification
- recovery
- bridge or lifecycle
- UI state
- latency

Add `Report Last Command` to the Conn menu. It writes a sanitized artifact for
the last turn and opens no external connection. It must exclude secure values,
clipboard bodies, bridge secrets, raw screenshots, and raw audio by default.

Promotion rule: a recurring real failure becomes a deterministic replay and,
when native state matters, a fixture case before its fix is considered done.

## Acceptance pyramid

### Contract tests

Pure tests cover intent parsing, risk floors, repair rules, receipt validation,
and wire-schema limits.

### Protocol replay

A strict fake Realtime server replays normalized client and server cassettes.
The exact July 12 failure sequence becomes a regression.

Pass requires:

- zero protocol errors
- no delete of an unacknowledged item
- no cancel without a bound response
- one correlated timeline per accepted turn
- stale events never reach preparation

### Signed fixture through the production bridge

Run the actual Python daemon, authenticated Swift app, real AX stack, and
ConnActionFixture. The fixture truth log remains independent.

### Recorded voice range

Feed short prerecorded commands through the actual PTT and audio ingress path.
Include:

- clean speech
- short voiced holds
- clipped first syllable
- playback followed by barge-in
- external-keyboard duplicate modifier edges
- quiet rejection

The first product proof sequence is:

1. Open Safari.
2. Create a new tab.
3. Open Notes.
4. Select the next note or document.
5. Enter harmless text into a safe field.

It must complete without manual repetition, upstream errors, or hidden raw
tool repairs.

### Live model intent eval

Add an opt-in `conn --intent-eval` that uses the production prompt and current
Realtime model but does not dispatch. It measures intent and slot selection on
a reviewed corpus of at least 200 paraphrases across the top 20 ordinary
commands.

This is separate from `conn --eval`. Scripted harness evals cannot claim model
quality.

### Daily-driver product gate

Use 30 ordinary commands across at least three work sessions after the lower
layers pass.

## Program packets

Each packet uses red, green, refactor. The failing replay or probe lands before
production code. One packet stays in progress at a time.

### R0: evidence and trace truth

Build the turn timeline and failure artifact before changing architecture.

Work:

- Add exact assistant transcript events.
- Add build, config, schema, PID, parent PID, and correlation identity.
- Distinguish user turns, model responses, proposals, executions, and goals.
- Record blocked proposals in receipts.
- Wire Swift `ui_ack` for listening, thinking, approval, and terminal outcome.
- Fix PTT source labeling.
- Calculate per-turn latency distributions.
- Add `Report Last Command`.
- Convert the July 12 session into a sanitized replay cassette.

Exit:

- Every sampled failure is assigned a pipeline stage.
- Top failure clusters explain at least 80 percent of sampled failures.
- Exact user-visible speech is auditable.
- Latency fields are populated in the signed app path.

### R1: wire and lifecycle integrity

Fix known deterministic defects first.

Work:

- Repair semantic item IDs and acknowledgement tracking.
- Delete only acknowledged items.
- Bind response cancellation to an active response ID.
- Add the strict fake Realtime server.
- Add authenticated daemon ownership lease and graceful shutdown.
- Exit an orphaned app-owned daemon after bounded parent-loss grace.
- Never kill or adopt an unproven port owner.

Exit:

- Zero protocol errors across 1,000 replayed normal turns.
- 50 quit and reopen cycles need no manual cleanup.
- 20 crash and relaunch cycles recover or show one actionable failure.
- A foreign port owner is never killed or adopted.

### R2: voice turn integrity

Work:

- Add gesture IDs and accepted or rejected acknowledgements.
- Flush playback before opening the barge-in mic gate.
- Suppress playback-contaminated pre-roll.
- Replace duration-only tap discard with signal-aware acceptance.
- Clear stale UI lines at turn start.
- Add recorded PCM and external-keyboard edge tests.

Exit:

- 500 PTT cycles produce zero stuck phases, duplicate turns, or lost releases.
- 100 percent of short voiced fixture commands are accepted.
- 100 percent of silent taps are rejected visibly.
- Synthetic playback watermark never reaches uploaded command audio.

### R3: remove the impossible action contract

Work:

- Remove model-visible `desired_effect` from ordinary tools.
- Stop advertising raw hotkey and menu strategy tools by default.
- Add bounded semantic intent types and schemas.
- Make native plan preparation derive the witness or outcome ceiling.
- Ensure missing witness becomes dispatch-only or a useful refusal, not an
  invalid model predicate.
- Add `create(kind=tab)` and `select_relative` as first vertical slices.

Exit:

- The exact New Tab and next-note replays compile without model-authored keys,
  menu paths, refs, risk, or predicates.
- Zero live tool calls can produce `invalid_effect_target` from model input.
- Existing false-verification tests remain green.

### R4: capability compiler

Work:

- Add `CapabilityReport` and bounded target ranking.
- Discover live menu commands and shortcuts after lazy menu opening.
- Compile the initial intent families.
- Add counterfactual candidate scoring without dispatch.
- Add empirical support-envelope recording.

Exit:

- 100 percent of advertised fixture capabilities compile to an authorized
  strategy and truthful outcome ceiling.
- 100 percent of ambiguous targets clarify or refuse before dispatch.
- Stale capability reports never dispatch.
- No per-app command catalog exists.

### R5: targeted witness engine

Work:

- Add read sets and witness sets to prepared plans.
- Replace full-tree polling with targeted rereads and adaptive backoff.
- Align bridge and native deadlines.
- Add causal witnesses for create tab, select relative item, menu toggles,
  focused window changes, and submit where safe.

Exit:

- Zero false verified outcomes.
- Supported fixture actions verify at least 98 percent.
- p95 fixture observation is at most 150ms.
- p95 warm dispatch plus verification is at most 800ms for bounded fixture
  actions.
- A delayed valid launch does not become a premature bridge timeout.

### R6: bounded recovery and useful failure UX

Work:

- Add typed reason and repair contracts.
- Permit one replan after proven `not_dispatched` and fresh observation.
- Keep zero retries after `dispatched` or `possibly_dispatched`.
- Add one-question ambiguity clarification.
- Stop repeated plan shapes.
- Render and speak safe reason plus next move.

Exit:

- At least 90 percent of recoverable corpus failures finish within one added
  model response or one user clarification.
- No identical failing plan is proposed twice in one user turn.
- `possibly_dispatched` never invites or triggers a retry.
- No safe-detail failure renders only unexplained `Did not run.`

### R7: realistic evaluation and failure flywheel

Work:

- Keep `conn --eval` scoped and label it harness-only.
- Add protocol replay, signed fixture, recorded voice, and live intent gates.
- Build the top 20 ordinary-command corpus from real usage.
- Add reviewed promotion from failure artifact to regression.
- Report reliability by intent, app version, target role, and witness.

Exit:

- At least 200 reviewed paraphrases score at least 97 percent correct intent
  and required-slot selection.
- Every reported failure has a stable correlation ID.
- The top recurring failure becomes a regression within one engineering
  session.
- No generated regression enters the suite without review.

### R8: daily-driver gate

Mechanical and semantic bars:

- zero wrong targets
- zero false `Done.`
- zero normal-path upstream protocol errors
- zero manual daemon cleanup
- 100 percent of ambiguous targets clarify or refuse
- 100 percent of possibly-dispatched outcomes avoid retry
- at least 95 percent first-try completion across the top 20 supported
  ordinary commands
- at least 99 percent completion after one safe replan or clarification
- release-to-effect p50 at most 2.0s and p95 at most 4.0s for warm semantic
  actions
- three 100-turn soak sessions with no stale mutation, duplicate response,
  stuck UI, or unbounded repair loop

Human product bars:

- 30 ordinary commands across at least three real work sessions
- at least 90 percent of supported actions are faster than hands or useful
  while hands are occupied
- zero unexplained failures
- zero false completion language

Do not call Conn a daily driver until these bars pass.

## Scope boundary

This program does not implement:

- ScreenCaptureKit action capture
- OCR or image injection
- visual coordinate actions
- a computer-use sidecar model
- a broad app command catalog
- hidden multi-action macros
- online self-modifying policy
- MCP expansion
- sound or character work
- island motion polish
- outbound, destructive, purchase, account, or secret actions

Direct APIs, App Intents, MCP, and visual control remain possible future
execution planes. They enter only after the semantic daily-driver gate proves
the orchestration contract.

## Implementation risks

### Intent algebra becomes a disguised command catalog

Mitigation: keep verbs generic, require live capability evidence, ban
bundle-specific command tables, and review schema growth. A new intent family
must cover at least two apps or one OS-level primitive.

### Compiler confidence becomes permission

Mitigation: confidence ranks candidates only. Python risk and exact approval
remain independent and may only be escalated.

### Shadow planning becomes false evidence

Mitigation: counterfactual plans never dispatch and never contribute to an
action receipt.

### Better recovery causes duplicate effects

Mitigation: one replan only after proven `not_dispatched`. Any uncertainty
stops the chain.

### Support history calcifies around old app versions

Mitigation: key by signed app version, expire stale evidence, and let current
capability downgrade or refuse at runtime.

### Reliability tooling captures sensitive content

Mitigation: sanitize at creation, store hashes and safe summaries, exclude raw
audio and screenshots by default, and never retain secure or clipboard bodies.

## Documentation consequences

Until R8 passes:

- `STATE-OF-PLAY.md` must say the safety kernel is mechanically green but the
  product control loop is not daily-driver ready.
- The roadmap begins with evidence truth, deterministic wire defects, turn
  integrity, and the model-to-intent boundary.
- The prior fixture matrix remains required, but real failed turns choose its
  highest-priority scenarios.
- Passing unit, harness, and in-memory transaction counts cannot be presented
  as product readiness.

## Immediate first proof

The first implementation session should not attempt the full compiler.

It should:

1. Reproduce the July 12 trace through a strict replay.
2. Fix context item lifecycle and response cancellation.
3. Wire exact model speech, UI acknowledgements, and correct PTT provenance.
4. Prove clean restart ownership.
5. Remove model-authored `desired_effect` from menu and key-chord paths.
6. Implement the smallest `create(kind=tab)` vertical slice through live menu
   discovery and a compiler-owned outcome ceiling.
7. Re-run the recorded New Tab voice command end to end.

This sequence reduces user pain, improves the feedback loop, and proves the
new boundary before expanding it.
