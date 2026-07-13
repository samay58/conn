# Conn verified action engine

Status: approved 2026-07-09. Semantic slice implemented and hardened through
2026-07-12. Visual control remains deferred.

Implementation note: production does not retain the proposed legacy-engine
rollout flag. Conn.app accepts only semantic observe, prepare, and execute RPC;
Python cannot restore the old AX/input mutation lane through config. App launch
also binds the approved name to an exact bundle ID and code-signing identity.
Current production verification accepts only operation-specific app or
clipboard predicates and target-bound element predicates. It rejects global
window predicates on element actions, bounded-tree disappearance, and
decorative refs on global predicates. Menu commands, raw key chords, and
submit without surviving target-bound evidence therefore return
`dispatch_only`. This conservative narrowing supersedes the broader predicate
permission below until causal binding can be proved without accepting
unrelated activity.
The browser console is also read-only. A fixed loopback browser origin cannot
prove that its JavaScript was not replaced by a persistent service worker, so
approval remains exclusively in the signed Conn app. This supersedes the
console approval nonce design below.
These decisions supersede the temporary fallback and rollback passages below.
The 1,000-transaction test currently uses an in-memory native backend. Real
fixture smoke proof exists, but the six-app semantic matrix and three-session
product gate remain open.

Written 2026-07-09 after the first real-app drives showed that green unit tests and successful Accessibility return codes do not prove visible action. This spec supersedes the narrow plan to repair `app_menu` one bug at a time. It preserves Conn's product thesis, native island, Realtime session, local harness, approval model, trace discipline, and budget cap.

## Decision

Conn will replace executor-centric computer control with a verified action engine.

Every state-changing computer tool becomes a transaction:

1. Observe current state.
2. Resolve target against that state.
3. Compile one bounded action plan.
4. Apply risk policy and approval.
5. Dispatch through the safest available strategy.
6. Observe again.
7. Verify the requested effect.
8. Return an evidence-backed outcome.

An API return code is dispatch evidence. It is never completion evidence by itself.

The implementation moves all macOS observation and input work into Conn.app. Python remains the policy and orchestration process. This removes the split TCC identity, gives AX observation a real AppKit runloop, keeps ScreenCaptureKit and Vision native, and makes one process responsible for reading, acting, and verifying against the same UI state.

## Product promise

Conn's core promise becomes:

> Conn reports an action complete only when it can show evidence that the intended effect occurred in the intended app and window.

Support is action-specific, not app-specific. Chrome may expose reliable tab selection but an opaque canvas. Terminal may expose menus and windows but not terminal-cell semantics. Conn discovers capability at runtime and reports the truth for each action.

Three lanes define the user promise:

| Lane | Meaning | Completion language |
|---|---|---|
| Verified semantic | Target and effect are observable through native app, AX, process, window, or clipboard state | “Done” |
| Verified visual | Semantic state is insufficient; a confirmed visual action has before-and-after evidence tied to one window region | “Done” with visual lane recorded in trace |
| Dispatch only | Input was sent, but Conn cannot prove the effect | “I sent it, but could not confirm it worked” |

`dispatch_only` is a resolved outcome, not success. Conn does not retry it automatically because the first action may have happened.

## Why current architecture fails

Current safety protects target identity before action better than it protects action truth afterward.

- `SnapshotStore.resolve` re-walks the AX tree, checks window identity, path fingerprints, ambiguity, role, label, security state, and frame drift. This is strong precondition handling.
- `MacInputBackend.press_menu_path` and `AxActionEngine.pressMenuPath` return success when `AXUIElementPerformAction` returns success. The July 9 drive showed visible state can remain unchanged.
- `computer_click`, `computer_type_text`, `computer_scroll`, `computer_hotkey`, `app_focus_tab`, `app_menu`, `app_open`, and `app_switch` return mechanism-level facts such as `pressed`, `typed`, `activated`, or `lane`. Most do not observe their effect.
- The state machine withholds continuation until a real tool result exists. It cannot distinguish a truthful result from an executor that mistakes dispatch for completion.
- Multiple mutating tool calls from one model response may run concurrently. Later calls can act on state invalidated by earlier calls.
- AX work is split across Python and Conn.app. This creates two grant identities, two implementations, divergent capabilities, and different runloop behavior.
- Tool calls are not bound strongly enough to an upstream response and observation epoch. A late or repeated call can target a prior turn's state.

Apple's installed SDK contract confirms the distinction. `AXUIElementPerformAction` requests an action. `kAXErrorCannotComplete` can occur even when an action happened, so a retry can duplicate an effect. AX exposes supported action discovery, notifications, multiple attribute reads, and targeted messaging timeouts. These primitives support observation and evidence, but they do not supply a universal transaction layer.

## Invariants

Existing invariants remain:

- Harness owns permissions. Model only proposes.
- Approvals are pointer-only.
- Budget cap is hard.
- Transport, session, and daemon death become visible.
- Secrets remain local.

Continuation invariant changes from:

> Continue after every call has a real executor result.

to:

> Continue after every call has a terminal, evidence-classified outcome.

New invariants:

- No raw dispatch return can produce `verified`.
- No automatic retry after an action may have been dispatched.
- Approval binds to effect, target, payload, window, observation epoch, and allowed strategies.
- Mutating actions execute serially.
- Every mutation re-resolves target immediately before dispatch.
- Stale response events and stale observation refs never reach an executor.
- Visual fallback never touches denied apps, secure fields, or unapproved targets.

## System shape

```text
voice or text
     |
Realtime model
     |
tool proposal
     |
Python policy plane
  TurnContext -> registry -> schema -> risk -> approval
     |
authenticated native RPC
     |
Conn.app control plane
  Observe -> Resolve -> Plan -> Dispatch -> Verify
     |          |          |          |
  AX tree   typed refs   strategy   AX observer
  windows   effect      ladder     targeted reread
  screen    contract               window/process state
  OCR                              visual diff
     |
ActionReceipt
     |
Python ledger -> function result -> model continuation
```

No new daemon or cloud service is added. Conn remains two local processes plus the debug console.

## Python policy plane

Python retains decisions that must remain model-independent:

- Tool schemas and user-facing action vocabulary.
- Static risk class, dynamic guards, deny lists, and approval rules.
- Turn and response provenance.
- Approval lifecycle.
- Action serialization.
- Budget, traces, receipts, and model continuation.
- Model-visible result envelope.

Python does not choose AX versus keyboard versus visual strategy. Conn.app chooses from the strategies authorized by the approved plan and current native capabilities.

High-level deterministic tools remain distinct because narrow schemas help Realtime tool selection: `app_open`, `app_switch`, `browser_search`, `phoenix_search`, `phoenix_open_note`, and `clipboard_set` stay model-visible.

Computer interaction tools also remain task-shaped: snapshot, press, type, scroll, focus tab, menu action, and key chord. Internally they all compile to one action transaction contract. One giant `computer_act` schema is rejected because it moves planner complexity into the Realtime model and weakens tool-selection accuracy.

## Native control plane

Conn.app becomes sole owner of:

- Frontmost app and window resolution.
- AX tree reads and action discovery.
- Stable window mapping between AX and WindowServer identifiers.
- AX observers and notification collection.
- AX actions and settable attributes.
- Key, pointer, and scroll event posting.
- ScreenCaptureKit single-window snapshots.
- Vision OCR and visual region extraction.
- Before-and-after state capture.
- Effect verification.

Python's `MacAxBackend` and `MacInputBackend` remain only as a temporary migration fallback behind a non-default test flag. They are deleted after native parity and live acceptance. Production must not silently fall back across lanes after migration.

## Authenticated bridge

The existing localhost WebSocket cannot remain an unauthenticated action bridge.

At app launch:

- Conn.app generates a 256-bit random bridge token.
- `DaemonLauncher` passes it to the child daemon through an inherited environment variable.
- Conn.app includes the token in `client_hello`.
- Daemon accepts exactly one authenticated app control client.
- App RPC requests and replies carry request ID, turn ID, observation epoch, and monotonically increasing sequence number.
- A detached or replaced app client invalidates pending native requests.

Console WebSocket rules:

- Reject non-local `Origin` values.
- Console cannot register as app role.
- Console approvals require a per-session nonce embedded by the locally served page.
- Native island approval remains preferred.

This design fixes the recorded localhost impersonation debt before computer control broadens.

## Turn provenance

Every accepted user turn creates a `TurnContext` owned by Python:

| Field | Purpose |
|---|---|
| `turn_id` | Unique local turn identity |
| `response_epoch` | Invalidates late events from cancelled or prior upstream responses |
| `observation_epoch` | Invalidates refs after app, window, or material UI change |
| `frontmost_bundle` | PTT-down app context |
| `window_id` | PTT-down stable WindowServer identity when available |
| `started_monotonic` | Span and expiry source |

Adapter events include upstream response ID where supplied. Python maps each active response to one response epoch. Tool calls from any other epoch are ignored and traced as stale.

PTT-down context injection lands before this action round closes. Current app and window enter the model conversation at the start of each turn. Old snapshot and visual image items are deleted from Realtime conversation history when superseded. At most one semantic observation and one visual observation remain live.

Observation refs are valid only inside their originating turn and observation epoch. A new turn never reuses prior refs.

## Observation contract

Native observation produces a bounded `ObservationSnapshot` containing:

- Snapshot ID, turn ID, observation epoch, monotonic timestamp.
- Bundle ID, PID, process start time, app name.
- WindowServer window ID, title, frame, document URL when exposed.
- Focused element and focused window.
- Bounded semantic tree.
- Optional window image metadata, never image bytes in the trace.
- Secure-content and denied-bundle flags.

Each semantic node records:

- Ephemeral ref.
- Role, subrole, title, description, identifier, value type, redacted value.
- Enabled, focused, selected, expanded, visible state when exposed.
- Frame and display.
- Supported action names discovered through AX.
- Settable attributes relevant to the proposed operation.
- Parent ref and a bounded sibling signature.
- Menu shortcut attributes where present.

Reads use `AXUIElementCopyMultipleAttributeValues` where available. Each target app element gets a native messaging timeout. One slow app cannot block the control plane indefinitely.

Snapshots are demand-driven. No ambient screen stream is introduced.

## Target resolution

Current child-index paths remain useful hints but stop serving as primary identity.

Resolution order:

1. Same app process identity and stable window ID.
2. Unique `AXIdentifier` in that window when present.
3. Unique semantic fingerprint using role, subrole, title, ancestor chain, supported actions, and nearby stable siblings.
4. Original path with sibling fingerprint and bounded frame drift.
5. Refuse if more than one candidate remains.

Resolution never chooses the nearest candidate from an ambiguous set. Geometry can confirm a semantic candidate. It cannot break a semantic tie by itself in the verified lane.

Execution performs a fresh targeted read. Full-tree rereads happen only when targeted resolution fails or the verifier needs a scoped diff.

## Action request

Every model-visible mutation compiles to an internal `ActionRequest`:

| Field | Meaning |
|---|---|
| Operation | Press, focus, set text, submit, scroll, invoke menu, key chord, open, switch, clipboard write |
| Target | Current observation ref or explicit app/path target |
| Payload | Text, direction, menu path, key chord, URL, or app name |
| Desired effect | Bounded verification predicate |
| Risk | Read, navigation, local mutation, external side effect, destructive |
| Strategy ceiling | Semantic only, semantic plus events, or visual permitted |
| Timeout | Per-operation verification budget |
| Turn provenance | Turn, response, and observation epoch |

Model cannot choose implementation lane. Model may propose a desired effect only from a small predicate vocabulary. Harness validates refs and predicate shape. Bad predicates cause safe failure, never broader authority.

## Effect predicates

The engine derives an obvious predicate when operation and role make one clear. Examples: selecting a tab should select that tab; setting text should change that field; switching app should change frontmost bundle.

For arbitrary buttons and menu commands, the model may add up to three predicates joined by one `all` or `any` group. Supported predicates:

- Frontmost bundle equals expected bundle.
- Window count changes by expected delta.
- Focused window title equals or changes from baseline.
- Element exists or disappears.
- Element attribute equals expected value or changes from baseline.
- Focused element resolves to expected ref.
- Non-secure text value contains expected text or matches expected hash.
- Clipboard hash equals payload hash.
- A named AX notification arrives from target app or element.
- Visual region changes beyond threshold, only in visual lane.

Predicate nesting stops at one group. Every predicate must bind to current app, window, ref, or captured baseline. Free-form natural-language predicates are not accepted.

If no observable effect predicate exists, action may still dispatch. Outcome cannot become `verified`.

## Action plan and approval binding

Conn.app resolves native capability and returns an `ActionPlan` before approval:

- Human effect sentence.
- Resolved target description.
- App and window identity.
- Payload hash and safe preview.
- Desired effect predicates.
- Ordered authorized strategies.
- Dispatch uncertainty rules.
- Verification budget.
- Plan fingerprint.

Python applies risk policy to this plan. Approval chip describes effect, not mechanism. Example: `Open a new Terminal tab`, not `AXPress AXMenuItem`.

Approval stores plan fingerprint. On approval, Conn.app validates app, window, target, payload, and observation epoch. Any mismatch returns `stale_plan`. It never silently recompiles a broader plan after approval.

An equivalent fallback may run under the same approval only if it was present in the approved plan and targets the same effect. Visual fallback is never silently added after approval.

## Strategy ladder

Conn.app selects first supported strategy from this order:

1. Direct deterministic OS or app mechanism already owned by Conn, such as LaunchServices, clipboard API, or Obsidian URL.
2. Supported AX action discovered on resolved element.
3. Settable AX attribute for focus, selection, value, or scroll position.
4. Keyboard shortcut read from the live target menu item.
5. Targeted CGEvent input after app, window, focus, and coordinates are revalidated.
6. Visual coordinate action against one current ScreenCaptureKit snapshot.

Profiles may reorder semantically equivalent strategies for a bundle. They cannot authorize a new risk class or bypass verification.

### Dispatch certainty

Each strategy reports one of three dispatch states:

| State | Meaning | Retry rule |
|---|---|---|
| `not_dispatched` | Rejected before effect could start | One approved equivalent fallback allowed |
| `possibly_dispatched` | Timeout, connection loss, or ambiguous OS result | Never retry automatically |
| `dispatched` | Input request was accepted | Verify; never retry merely because effect is unseen |

Apple documents that `kAXErrorCannotComplete` does not prove failure. Conn classifies it `possibly_dispatched`.

One automatic fallback maximum. Fallback budget resets only on a new model proposal after fresh observation.

## Operation rules

### App open and switch

- Dispatch through LaunchServices.
- Verify process identity and frontmost regular app.
- Cold launch may extend verification while app launch state is observable.
- A launch that starts the process but never becomes frontmost returns `dispatch_only` unless user requested background open.

### Menu action

- Read menu bar from target app.
- Resolve top-level item.
- Invoke its supported show or press action.
- Wait for `AXMenuOpened` or populated descendants.
- Read children after open. Lazy menu contents are never assumed from a closed tree.
- Resolve every path segment with exact normalized title first, then fuzzy match only when unique beyond ambiguity threshold.
- Leaf must be enabled and expose supported press/pick action or a live keyboard equivalent.
- Subscribe before dispatch to `AXMenuItemSelected`, `AXMenuClosed`, focused window, title, selected children, and relevant app notifications.
- Dispatch leaf action.
- Verify desired effect. `AXMenuClosed` alone is insufficient.
- If dispatch is ambiguous, do not send keyboard equivalent.

Menu tree and press happen in one native transaction. Python never asks app for a tree and later sends a disconnected path walk.

### Element press

- Re-resolve target and supported actions.
- Prefer AX action.
- Coordinate fallback only when plan already permits it, frame intersects current frontmost window, hit testing resolves to same semantic element, and action is confirm-gated.
- Verify target attribute change, target destruction, focused element change, sheet/window creation, or approved effect predicate.
- Generic layout or unrelated pixel change cannot prove success.

### Text entry

- Secure fields stay blocked.
- Re-resolve and focus target.
- Verify focused ref before every chunk.
- Prefer settable AX value for bounded non-rich text when target supports it; otherwise post Unicode chunks.
- Re-read non-secure value after entry and compare expected text or hash.
- Submit is a separate dispatch inside same approved transaction. It runs only after text verification.
- Browser fields with uncertain secure state cannot submit.

### Tab focus

- Resolve tab candidates from semantic roles and selected state.
- Ambiguity returns candidates.
- Dispatch supported select/press action.
- Verify selected attribute, focus, or a profile-approved browser tab signal.

### Scroll

- Prefer AX scroll-to-visible or writable scroll value.
- Verify target frame enters current window viewport or scroll value changes in requested direction.
- Wheel fallback requires visible scoped scroll area and current window hit test.

### Key chord

- Raw key chords remain explicit allowlist actions.
- Posting a key chord produces `dispatch_only` unless desired effect verifies.
- Shortcut derived from a live menu item inherits menu target, risk, and verifier.

### Clipboard

- Write through native pasteboard.
- Read back and compare cryptographic hash.
- Trace hash and length, never full payload.

## Visual fallback

Visual control exists because AX cannot represent every custom canvas or poorly exposed Electron surface. It is fallback, not foundation.

Visual observation flow:

- Capture only frontmost target window through ScreenCaptureKit.
- Exclude Conn surfaces.
- Normalize to a declared coordinate space with scale map.
- Run local Vision OCR for text boxes and confidence.
- Attach image to Realtime conversation only on explicit visual observation. Realtime supports `input_image` conversation parts.
- Delete superseded visual item after next visual snapshot.
- Store image locally only for current transaction unless debug retention is explicitly enabled.

Visual action rules:

- Screen Recording permission required.
- Denied bundles and secure fields blocked.
- Every visual coordinate action requires pointer approval.
- Target is a visual ref tied to image, window ID, region, OCR label when present, and coordinate transform.
- Before dispatch, capture a small fresh target-region image and reject if perceptual change exceeds drift threshold.
- Hit test with AX at target point. If hit test returns a conflicting semantic element, refuse.
- After dispatch, capture target window again and evaluate approved visual predicate plus available semantic state.
- Pixel change alone can verify only reversible navigation. Local mutation, outbound, and destructive effects require semantic or app-state evidence.

Visual lane ships disabled by default. It enables only after semantic engine gate passes and visual fixture tests meet the accuracy bar below.

Conn uses its existing Realtime model for visual interpretation first. A separate Responses computer-use planner is not added in this round. Official computer-use guidance validates screenshot, action, updated-screenshot loops, but a second model would add latency, cost, context synchronization, and a second policy boundary. Planner abstraction remains internal so later evidence can justify a sidecar without rewriting native execution.

## Quirk profiles

Profiles are small, data-only reliability patches keyed by bundle ID and optional version range.

Allowed fields:

- Attribute normalization rules.
- Roles considered tab-like.
- Notifications known to fire for an operation.
- Preferred order among already authorized equivalent strategies.
- Longer native messaging or verification timeout.
- Known opaque regions that require visual lane.
- Additional denied roles or regions.

Forbidden fields:

- Hardcoded coordinates.
- Full app command catalogs.
- Free-form scripts.
- Selectors that bypass live observation.
- Risk downgrades.
- Success without evidence.

Every profile entry cites a failing live probe and carries its own integration fixture. Profiles expire when app version leaves declared range unless explicitly version-agnostic.

## Compound intents

Reliability beats parallel mutation.

- Read-only tools may run concurrently.
- One mutating computer action may execute at a time.
- If model proposes multiple mutations in one response, Python preserves output order, executes first, and resolves remaining calls with `sequential_action_required` before dispatch.
- Model receives first outcome and fresh state before proposing next action.
- Any `dispatch_only`, ambiguous, blocked, or failed result stops automatic chain.
- User Stop cancels queued undispatched actions. It cannot claim reversal of already dispatched work.

A future `computer_sequence` tool is outside this spec. It may enter only after single-action verified success meets the live gate and a measured latency problem justifies batching.

## Result contract

Every action returns:

| Field | Meaning |
|---|---|
| `outcome` | `verified`, `dispatch_only`, `no_effect`, `blocked`, `ambiguous`, or `failed` |
| `ok` | True only for `verified` |
| `dispatch_state` | `not_dispatched`, `possibly_dispatched`, or `dispatched` |
| `strategy` | Actual native strategy used |
| `lane` | Semantic or visual |
| `target` | Safe target description and refs |
| `effect` | Predicate summary |
| `evidence` | Notification, targeted reread, state delta, or hashes |
| `retry_safe` | True only when engine proves nothing dispatched |
| `duration_ms` | Full observe-to-verify duration |

Machine ledger gains resolved statuses for `unverified`, `no_effect`, and `ambiguous`. Island uses distinct copy and color. None render green Done.

Model prompt rules:

- Say completion only for `verified`.
- For `dispatch_only`, state action was sent but not confirmed.
- Retry only when `retry_safe` is true.
- Re-observe before retry.
- Never turn unrelated UI change into success.

## Trace contract

Each transaction logs:

- Turn, response, and observation epochs.
- Plan fingerprint and approval fingerprint.
- Before-state digest.
- Resolved target fingerprint.
- Authorized strategy list and selected strategy.
- Dispatch state and native error.
- Notifications observed.
- Verification predicates and per-predicate result.
- After-state digest.
- Outcome, retry safety, and latency spans.
- Visual image metadata and hashes, never image bytes.

Failure artifacts are off by default. When enabled, bounded before-and-after semantic snapshots and window images live in session-scoped gitignored storage and delete at session end unless user explicitly keeps them.

## Configuration

New settings:

| Key | Default | Meaning |
|---|---:|---|
| `actions.engine` | `verified` after migration gate | `legacy` exists only during rollout |
| `actions.semantic_verify_ms` | 1200 | Normal semantic effect budget |
| `actions.launch_verify_ms` | 4000 | Cold app launch budget |
| `actions.visual_verify_ms` | 3000 | Visual effect budget |
| `actions.max_fallbacks` | 1 | Equivalent fallbacks after proven non-dispatch |
| `actions.require_verified_success` | true | Prevent dispatch-only success |
| `actions.visual_enabled` | false | Gate visual control |
| `actions.keep_failure_artifacts` | false | Retain bounded debug artifacts |

Existing app allowlist, AX denied bundles, hotkey allowlists, trusted interaction roles, and risk overrides remain. Config cannot turn `dispatch_only` into success or permit visual actions in denied bundles.

## Test architecture

Mocks remain necessary but stop serving as final proof.

### Pure tests

- Turn and response epoch rejection.
- Plan fingerprint binding.
- Mutation serialization.
- Dispatch certainty and retry rules.
- Predicate compiler and evaluator.
- Outcome mapping and prompt-visible envelopes.
- Risk floors across semantic and visual lanes.
- Secure-field and denied-bundle behavior.
- Conversation snapshot and image pruning.

### Native fixture app

Add a small test-only `ConnActionFixture.app` with deterministic surfaces:

- Button with immediate value change.
- Button with delayed value change.
- Button returning action success with no effect.
- Toggle, tabs, text field, secure field, scroll area.
- Duplicate labels and reordered siblings.
- Lazy menu populated only after open.
- Menu item with shortcut.
- Window create, close, sheet, and title change actions.
- Custom-drawn inaccessible canvas target.
- Background animation that creates unrelated pixel changes.

Fixture writes an independent local truth log. Tests compare Conn's receipt against fixture truth. Conn may not use truth log for execution or verification.

### Live probe runner

Add `conn --action-probe` as a hardware-marked manual runner. It drives a bounded matrix against Terminal, Safari, Chrome, Notes, Obsidian, and the fixture. Each probe records expected effect, engine outcome, human verdict, latency, strategy, and evidence.

The runner never performs outbound, destructive, account, purchase, or secret actions.

### Adversarial cases

- Window changes between plan and approval.
- Target disappears during approval.
- AX success with no visible effect.
- AX timeout after real effect.
- Notification unsupported.
- Notification arrives from unrelated element.
- App background update during verification.
- Two identical labels.
- Lazy menu mutation.
- App loses Accessibility or Screen Recording mid-action.
- App client reconnect during transaction.
- Old response emits tool call after barge-in.
- Visual scale, multi-display, Retina, and window movement drift.
- Prompt content on screen asks model to bypass policy.

## Acceptance bars

Semantic engine gate:

- Zero wrong-target actions in 1,000 fixture transactions.
- Zero false `verified` outcomes in 1,000 fixture transactions.
- At least 98% `verified` on supported semantic fixture actions.
- At least 95% `verified` first try across the six-app live probe matrix for actions whose desired effect is semantically observable.
- 100% ambiguous targets refuse before dispatch.
- 100% possibly-dispatched results avoid automatic retry.
- p95 semantic observation at or below 150ms in fixture.
- p95 semantic dispatch plus verification at or below 800ms, excluding cold app launch.
- Every live receipt agrees with human verdict before legacy engine can be removed.

Visual lane gate:

- Semantic gate already green.
- Zero wrong-window actions in 300 fixture visual transactions.
- At least 95% correct target hit in static visual fixture cases.
- Zero automatic visual actions without approval.
- Zero visual actions in secure or denied surfaces.
- Background animation alone never produces `verified`.
- p95 visual observe, act, and verify at or below 3 seconds.

Product gate:

- Quick-test menu from `NEXT-SESSION.md` rewritten around evidence-backed outcomes.
- Samay completes 30 ordinary commands across at least three work sessions.
- No false completion language.
- At least 90% of supported actions feel faster than hands or clearly earn their use while hands are occupied.
- Conn is not called daily-driver ready until this gate passes.

## Delivery sequence

### Evidence round

- Build native fixture and current-lane probe before changing production behavior.
- Reproduce menu false success against Terminal and Safari.
- Capture supported actions, menu notifications, lazy population, native return, and human-visible outcome.
- Pin current false-positive behavior in a failing integration test.

### Contract round

- Add turn and response provenance.
- Add typed result outcomes and ledger/UI states.
- Serialize mutating calls.
- Make `ok` mean verified effect, not executor return.
- Keep legacy executors behind rollout flag.

### Native control-plane round

- Authenticate app bridge.
- Move observation, frontmost resolution, and stable window mapping into Conn.app.
- Move all AX and input executors into Conn.app.
- Keep Python policy and approvals unchanged.
- Prove no Python Accessibility grant is needed for production.

### Semantic transaction round

- Add native observer, targeted reread, predicate evaluator, plan compiler, and action receipt.
- Migrate app open/switch, clipboard, tab focus, scroll, text, element press, menu, then key chord.
- Close each operation only after fixture and live probes pass.

### Visual observation round

- Add ScreenCaptureKit window capture, Vision OCR, Realtime image items, coordinate mapping, and image pruning.
- Keep visual dispatch disabled.
- Measure visual target and verification accuracy.

### Visual action round

- Enable confirmation-gated visual press for reversible navigation only.
- Expand effect classes only after separate evidence and explicit spec amendment.

### Proof round

- Run semantic, visual, safety, latency, and product gates.
- Remove legacy engine and Python control lane only after all relevant gates pass.
- Update state, roadmap, live checklist, README, deployment, and idea ledger from measured truth.

## Rollback

No persistent user data migrates.

During rollout, `actions.engine = legacy` returns to current executors. Traces label engine version so results remain comparable. Legacy mode remains development-only after verified engine becomes default because it permits dispatch-level success.

Native control-plane changes are additive until parity. If native bridge fails, action refuses. Production never silently falls back to Python lane.

Visual lane has independent feature flag. Disabling it returns Conn to verified semantic behavior with no data migration.

## Scope and impact

This is a large architecture round. It touches more than eight files and adds several Swift components. Expected areas:

- Python state, events, app composition, harness, risk, registry, adapter, traces, config, evals, and server bridge.
- Existing AX modules during migration, then deletion or test-only reduction.
- Swift daemon client, app state, AX context/action code, launcher, island action status, and new native observation, transaction, verifier, screen capture, and bridge-auth components.
- Python and Swift tests plus test fixture app.

No new service, language, account, or API key is required. Existing OpenAI key remains. Accessibility is required for semantic control. Screen Recording is required only for visual lane. Full Xcode is required to build the native fixture and app.

## Explicitly not building

- Always-on screen capture.
- Autonomous background actions.
- Voice or keyboard approval.
- Free-form scripts or shell control.
- Hardcoded app command catalogs.
- Silent app-specific coordinate patches.
- Destructive or outbound visual actions in first visual round.
- Separate computer-use model in first implementation.
- Multi-action macro tool before single-action proof.
- Success based on model confidence or numeric confidence scores.

## Alternatives rejected

### Patch each executor

Smallest change. Add menu close check, text readback, and app-frontmost checks independently. Rejected as final architecture because every executor invents its own truth semantics, retries remain dangerous, and split TCC lanes remain.

### App-specific automation adapters

Could make six apps reliable quickly. Rejected as foundation because maintenance scales with app versions and commands. Quirk profiles retain narrow evidence-backed exceptions without becoming command catalogs.

### Vision-first computer use

Broadest apparent flexibility. Rejected as core because coordinate identity, security, latency, and effect verification are weaker than semantic state. Visual remains a gated fallback.

### Separate Responses computer-use planner

Official loop is strong for screenshot-driven interfaces. Rejected for first implementation because Conn already has a Realtime model with image input and function calling. A second model creates another context, policy, latency, and budget boundary before need is proven.

### Keep both Python and app control lanes

Appears resilient. Rejected because two identities and implementations caused current failures. One native control plane plus fail-closed RPC is more reliable than divergent fallbacks.

## Fragile assumption

This design assumes ordinary productivity actions expose at least one effect signal through AX, process/window state, clipboard state, or a stable visual region.

When assumption fails, Conn does not collapse into guessing. It returns `dispatch_only`, refuses automatic retry, and can offer confirmed visual fallback where policy permits. The product loses “Done” for opaque actions, not truth.

## Sources informing this design

- [Apple AXUIElement API](https://developer.apple.com/documentation/applicationservices/axuielement_h): supported attributes/actions, action dispatch, messaging timeouts, and observers.
- [Apple ScreenCaptureKit](https://developer.apple.com/documentation/screencapturekit): fine-grained app/window capture.
- [Apple Vision text recognition](https://developer.apple.com/documentation/vision/vnrecognizetextrequest): local OCR with confidence and bounding boxes.
- [OpenAI Realtime conversations](https://developers.openai.com/api/docs/guides/realtime-conversations): `gpt-realtime-2` image input and function result loop.
- [OpenAI computer use guide](https://developers.openai.com/api/docs/guides/tools-computer-use): screenshot, action, updated-screenshot loop plus human approval guidance.

## Final recommendation

Proceed with verified semantic engine and unified native control plane. Treat visual control as a separately gated fallback. Pause island tuning, sound, MCP, and capability expansion until semantic product gate proves Conn can act truthfully across real apps.
