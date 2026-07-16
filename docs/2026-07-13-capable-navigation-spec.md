# Capable navigation and real-app reliability

Status: approved for implementation 2026-07-13.

The packet-by-packet execution contract is in
`docs/2026-07-13-capable-navigation-implementation-plan.md`.

This spec responds to the failures aggregated in
`docs/2026-07-13-dogfood-failure-analysis.md`. It expands Conn from an
Accessibility-only action surface into a capable navigation agent while
preserving honest receipts and deterministic execution boundaries.

## User promise

When the user grants navigation control for a session, Conn can use the best
available reversible way to complete an ordinary Mac task. It may inspect the
current app, use Accessibility, read a screenshot, click a visible target,
scroll, use ordinary navigation keys, type into a non-secure field, and open a
direct URL in the requested browser. It does not ask for approval again on
every click.

Conn still distinguishes action from proof:

- `verified` means target-bound evidence shows the intended effect
- `dispatch_only` means the action was sent but no trustworthy witness exists
- `no_effect` means the action was sent and the witness did not change
- `possibly_dispatched` is never retried automatically
- user confirmation is recorded as an eye verdict but does not rewrite the
  machine receipt

Destructive or consequential effects are not included in the navigation
grant. Consequential actions keep the existing one-action pointer approval.
Destructive actions, including deleting content, overwriting data, closing
unsaved work, and entering a secure field, remain refused in this release.

## Product principles

### Capability ladder

Conn chooses the highest-confidence lane that can complete the goal:

1. a uniquely grounded Accessibility action
2. a semantic browser, menu, or key action
3. a screenshot-grounded coordinate action bound to the current window

The lanes are implementation choices. The user asks for an outcome, not a
mechanism. The model does not need to invent menu paths, shortcuts, or effect
predicates before Conn inspects the live surface.

### One navigation grant

The signed app exposes a visible `Navigation control` state. The user grants it
once for the active session. While active, it authorizes reversible foreground
interaction without repeated approval chips.

The grant ends when:

- the user turns it off
- Conn.app exits
- the daemon session ends
- the execution plane loses ownership and reconnects as a new session

A foreground app change does not end the grant. A transition into a secure,
denied, destructive, or consequential surface does not inherit it.

The grant survives an upstream Realtime reconnect because the local daemon
session and signed execution connection have not changed. Lock or sleep
suspends dispatch, invalidates prepared plans, and requires the same signed app
connection to reassert the active state after unlock. A new daemon session or
new app execution connection always requires a fresh pointer grant.

### Broad authority without false confidence

Ambiguity controls dispatch, not language. Conn may act broadly when the user
has granted control and the target is grounded. It may not guess among
indistinguishable targets or label a coordinate dispatch as verified without
effect evidence.

When the requested target is visually obvious but absent from Accessibility,
the screenshot lane is a supported action path. This is no longer treated as
an unsupported edge case.

### Current state replaces stale state

Only one observation is current for planning. A new observation replaces the
prior model-visible observation. Old native references, screenshots, window
frames, and coordinates expire together.

## Architecture

Python remains the policy plane. It owns the session grant, tool exposure,
risk classification, provenance, mutation serialization, model context, cost,
and receipt validation.

Conn.app remains the only production observation and execution plane. It owns
Accessibility capture, screen capture, app and window identity, coordinate
conversion, execution-time revalidation, input dispatch, and native effect
observation.

The browser console remains read-only. It cannot grant control, initiate
actions, approve consequential actions, or answer native RPC.

No Python Accessibility or input fallback is introduced. No per-app command
catalog is introduced.

## Observation contract

### Candidate query

Replace raw tree delivery with a native candidate query that accepts:

- search terms
- expected roles and actions
- app and window scope
- optional ancestor or selected-element scope
- result limit

Native code performs the search before returning data across the bridge. The
model receives 5 to 20 ranked candidates with:

- stable observation reference
- role, subrole, title, description, value summary, and supported actions
- concise ancestor trail
- sibling position and count when distinguishing
- window-relative frame
- why the candidate matched

A zero-match result is explicit. Blank containers do not become candidates
merely because nothing better matched.

### Screenshot observation

The visual lane captures only the current target window by default. Full-screen
capture is allowed when the user explicitly asks about the screen or no single
window contains the requested target.

The model receives actual image content, not a local file path. Every capture
records image dimensions, scale, window frame, app bundle, window identifier,
capture timestamp, and image token use.

Images used for execution are short-lived evidence. They are stored with the
trace under the existing data policy and are never exposed through the
read-only console without its capability gate.

### Context budget

A new native observation replaces the prior observation payload in model
context. The trace retains each observation for audit. The model conversation
does not.

Hard limits:

- at most 20 accessibility candidates per query
- at most one current accessibility payload
- at most one current screenshot per action plan
- explicit byte and token accounting for every observation
- no tool result may be truncated inside serialized JSON

## Grounding and clarification

### Accessibility re-resolution

Resolution intersects all stable evidence before returning ambiguity:

- semantic fingerprint
- role and action support
- ancestor trail
- path and sibling signature
- identifier when present
- bounded frame drift
- current app and window identity

Geometry may narrow a named semantic target. Geometry alone may not select an
anonymous target.

### Visual grounding

Visual grounding is a two-stage compiler flow:

1. The model proposes the goal-level activation and target description.
2. Conn tries Accessibility resolution against the current window.
3. If no useful target exists, Conn.app captures the current window and the
   model returns a constrained capture identifier, normalized region, label,
   and confidence.
4. Conn.app compiles those facts into one native plan under the original turn,
   observation epoch, and navigation grant.
5. Conn.app revalidates the capture and dispatches one input event sequence.

The model's visual result is grounding evidence. It is not a free-form input
strategy and cannot choose a different app, window, effect class, or action
family.

A visual plan contains:

- capture identifier and digest
- app and window identity
- captured window frame and scale
- normalized target point or bounded target region
- human-readable target description
- intended reversible effect class
- expiration

Immediately before dispatch, Conn.app confirms that the same signed app and
window remain frontmost and that the frame and scale have not changed beyond
the allowed tolerance. Any mismatch refuses before input.

### Clarification

Clarification questions use real candidate descriptors. The answer binds a
descriptor, not an old node reference. Conn takes a fresh observation and
resolves the bound descriptor against it.

After one failed clarification, Conn either uses another authorized lane or
states the measured capability ceiling. It does not repeat an equivalent
snapshot loop with different node IDs.

## Reversible navigation actions

The navigation grant covers:

- click, double-click, and right-click on a grounded target
- scroll and scroll-to-visible
- focus and selection changes
- ordinary text entry into a non-secure field
- Space, Escape, Tab, arrow keys, Page Up, Page Down, Home, and End
- Enter only when the compiled target and effect are reversible, or the user
  explicitly requests it in a non-consequential context
- common navigation chords such as Command-L and Command-T
- media play, pause, seek, and mute when reversible
- direct URL navigation in an explicit or current supported browser
- menu actions whose compiled effect is classified as reversible navigation

The grant does not automatically cover:

- delete, remove content, empty trash, or destructive menu actions
- submit, send, publish, purchase, transfer, or install
- overwrite or replace existing content
- close or quit when unsaved work may exist
- authentication, password, payment, or other secure fields
- permission changes, account changes, or system settings with lasting effect

Risk is assigned from the compiled effect and live target, not from the tool
name alone. `computer_click` is not inherently risky when it resolves to a
reversible media control. A click on an unknown control remains consequential
or ambiguous.

## App identity and support

The navigation grant is not limited to a fixed catalog of approved apps.
Resolve explicitly requested installed apps through LaunchServices, then bind
the plan to the resolved bundle and signing identity. If an app name resolves
to more than one installed target, ask one real clarification. Do not guess an
app when the transcript contains only `Open` or another incomplete request.

Explicitly denied bundles, secure surfaces, and system permission changes
remain outside the navigation grant. Support is capability-based: if a normal
foreground app exposes Accessibility or can be controlled through a bound
visual plan, Conn may navigate it without a hand-maintained app entry.

## Direct browser navigation

Add a semantic navigation intent distinct from web search:

```text
navigate(url, browser_scope)
```

The compiler validates and normalizes the URL, resolves the explicit or current
installed browser identity, and opens the URL in that browser. It does not turn
a URL into a search query and does not silently use a different default
browser.

This release accepts only `http` and `https`. It rejects credentials in the
authority, control characters, oversized values, and all other schemes.
Dedicated tools may continue to own an app-specific scheme such as an Obsidian
vault link, but general browser navigation does not.

The witness reads the browser's current document URL when accessible. A title
change alone is insufficient when the requested URL is known. If the browser
hides document state, the action remains `dispatch_only` with a specific
reason code.

Opening the browser, creating a tab when needed, and navigating are one user
goal. The implementation may serialize internal subtransactions, but the
assistant reports completion only against the final navigation witness.

## Activation and media

Add a semantic activation intent:

```text
activate(target, scope)
```

The Accessibility compiler tries supported semantic actions such as press or
pick. If no useful accessible target exists and navigation control is active,
Conn captures the current window and grounds the target visually. If the user
explicitly asks for a key equivalent such as Space, the semantic key lane may
run without first manufacturing an Accessibility target.

Verification uses the narrowest available effect:

- Play becomes Pause
- an accessible playback value changes
- a target control changes state
- a bounded visual region changes consistently with playback or pause

Motion alone is not enough to prove the requested semantic state. If no
trustworthy witness exists, return `dispatch_only`, not `verified`.

## Witnesses and deadlines

Create witnesses must select among multiple compatible collections using
window scope, stable structure, role, and kind. Genuine ambiguity refuses.
Every predicate result records its measured baseline, current value, and match
rule.

One absolute native transaction deadline covers:

- baseline capture
- target resolution
- dispatch
- post-action capture
- witness polling
- receipt serialization and delivery

The clock starts when execution begins after policy and any pointer approval.
Approval wait is excluded. Execution-time baseline capture and every later
step share the same remaining deadline.

The Python transport deadline exceeds the complete native deadline by a
measured delivery margin. A valid receipt at the old 2.7-second boundary must
not be discarded. A true post-dispatch timeout remains
`possibly_dispatched` and never retries.

## Intent routing

Explicit app and screen context outrank generic corpus rules.

- `the note under our current note` in Apple Notes means relative selection
- `open the Phoenix note` means vault search
- `open techmeme.com in Safari` means direct Safari navigation
- `search for Techmeme` means web search
- `click the video` may use visual grounding when Accessibility has no target

The model may propose a goal that requires internal steps. It may not narrate
the full goal as underway when only the first partial step was dispatched.

## Voice isolation

PTT barge-in cancels the active response, clears its unfinished transcript and
audio buffers, and starts the next response with an empty output buffer. A
stale cancellation is logged but cannot attach text to the next response.

The destructive-refusal sequence from `session_4a09e788eb` is a strict replay:
the new response must contain only the refusal, with no prefix from prior result
speech.

## Receipts and evidence

Every non-verified action and every predispatch refusal has a stable, non-null
reason code. Required examples include:

- `no_matching_accessible_target`
- `ambiguous_after_full_locator`
- `navigation_grant_required`
- `visual_plan_stale`
- `window_identity_changed`
- `no_trustworthy_witness`
- `witness_not_matched`
- `native_transaction_timeout`

Human eye verdicts can be linked to a receipt as `matched`, `not_matched`, or
`unclear`. They are diagnostic evidence. They do not change the machine
outcome.

Eye verdicts live in an explicit probe or manual sidecar linked by receipt ID.
Ordinary praise, follow-up speech, or task continuation is never inferred as an
eye verdict.

Large artifacts remain valid JSON. If a preview is shortened, the wrapper
records truncation metadata and links to a complete local artifact.

## Implementation packets

### Live failure fixtures

Extract red fixtures and strict replays from the RIVER, Firefox video, Safari
tab, Notes create and type, direct navigation, relative note, and barge-in
sessions. Preserve the real hierarchy shapes and adversarial duplicates.

Exit: every current failure reproduces without a live app, and the anonymous
Firefox target still refuses.

### Bounded observation

Implement the native query grammar, compact candidates, context replacement,
and valid artifact storage. Screenshot delivery remains behind its own visual
transport packet so coordinate action cannot outrun the image contract.

Exit: repeated observation does not grow model context linearly, and real-app
queries return useful bounded candidates or explicit zero matches.

### Safe resolution

Use the full stable locator, grounded clarification descriptors, and
equivalent-loop detection.

Exit: named duplicate links can resolve when structurally unique, while moved,
reordered, or anonymous duplicates refuse.

### Navigation grant and action policy

Add the signed-app session grant, visible state, revocation, reversible action
classification, and policy tests separating navigation from consequential
effects.

Exit: one grant authorizes reversible navigation across apps without repeated
approval, while every excluded effect remains gated.

### Browser and visual control

Add direct navigation, semantic activation, ordinary key dispatch, visual
plans, coordinate revalidation, and visual effect observation.

Exit: the July 13 browser and video goals dispatch through the best available
lane and never use stale screen state.

### Witness and transaction hardening

Generalize Safari and Notes witnesses, record measured predicate values, and
make the native transaction deadline authoritative.

Exit: adversarial fixtures have zero false `verified` outcomes, and the delayed
Notes typing receipt arrives before Python times out.

### Voice and routing

Fix current-app routing precedence, partial-goal narration, cancellation
isolation, and repeated-failure language.

Exit: the live trace replays produce one clean response per turn and do not
leave the current app without explicit reason.

### Goal-level gate

Run the existing mechanical suites, then a real-app gate that scores complete
user goals and receipt-to-eye agreement.

The gate requires:

- zero false `verified` outcomes
- zero automatic retries after possible dispatch
- zero stale visual or accessibility plans reaching input dispatch
- 100 percent non-null reason codes on non-verified outcomes
- no linear context growth across repeated observations
- direct URLs open in the requested browser
- the approved video commands dispatch in a granted session
- at least 95 percent first-try completion across the supported engineering
  corpus
- at least 99 percent completion after one safe clarification or replan
- at least 90 percent of the 30-command product gate is faster than hands or
  useful while hands are occupied
- every machine `verified` receipt agrees with the independent eye verdict

An eye-matched `dispatch_only` may count as user-goal completion in the product
usefulness tally. It never becomes machine `verified`. Visual latency and cost
bars are set from the first transport and fixture measurements, not invented
before evidence exists. Warm semantic actions retain the current p50 2.0s and
p95 4.0s release-to-effect bars.

The manual drill and 30-command product gate resume only after these packets
are mechanically green on the candidate build.

## Deferred from this spec

This spec does not add macros, unattended background control, app command
catalogs, arbitrary destructive autonomy, a second service identity, or a new
secret. Those are separate product decisions.
