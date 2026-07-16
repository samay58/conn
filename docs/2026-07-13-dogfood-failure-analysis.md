# Conn dogfood failure analysis

Updated 2026-07-13. This document aggregates the real voice sessions from
July 12 and July 13 and turns them into requirements for the next spec. It is
evidence for a spec, not an approved implementation plan.

## Verdict

The safety kernel is doing useful work, but the product gate is red.

Across the four post-release dogfood sessions, Conn handled 29 user turns and
40 tool proposals. Nine proposals were blocked before dispatch. Twelve actions
produced receipts: 3 `verified`, 7 `dispatch_only`, 1 `no_effect`, and 1
`failed` after a possible dispatch. The three verified actions were app opens.
No create, click, browser navigation, typing, or note-opening task verified.

This is why the mechanical suite and the lived experience disagree. The suite
proves transaction safety and selected fixtures. It does not yet prove that
Conn can ground and complete ordinary work in the changing Accessibility trees
of real apps.

The product direction is now explicit: after a user grants navigation control
for the session, Conn should have broad authority to use Accessibility,
model-visible screenshots, coordinates, ordinary navigation keys, direct URLs,
and browser control without asking for approval on every action. Destructive or
irreversible actions remain a separate grant. Honest receipts and no retry
after a possible dispatch remain mandatory.

The most visible failure, playing a YouTube video in Firefox, is not one bug.
Firefox exposed no named Play control, the snapshot search term was ignored,
the model received repeated copies of the same raw tree, and Conn has no safe
fallback for an opaque media surface. Five attempts dispatched nothing, cost
$0.4935, and left the user in the same place.

## Evidence set

There are 312 trace files from July 12 and July 13. Only six are real sessions
with spoken input. The rest are 290 demo or harness traces and 16 startup or
test traces with no user turn and no billed model use.

| Session | Build status | Main evidence |
|---|---|---|
| `session_a4f5c83703` | July 12 historical build | Realtime protocol failures that no longer recur |
| `session_64e67d4bf3` | Pre-release reliability build | Safari and Notes witness failures, empty safe target bug |
| `session_a7613a568b` | Post-release | Safari tab under-claim, browser navigation gap, RIVER ambiguity loop |
| `session_4a09e788eb` | Post-release | Notes witness miss, typing timeout, wrong note routing, barge-in splice |
| `session_ca9f9f62f8` | Post-release | Missing direct navigation, guessed app, premature narration |
| `session_86cb484325` | Post-release | Five failed attempts to play a Firefox video |

The four post-release sessions cost $2.554 in total. The older July 12
protocol failures are historical and should not be counted as current
regressions. They are useful only as replay coverage.

## What the logs show

### Observation search is not implemented end to end

Python sends snapshot terms such as `play`, `video`, `control`, and `RIVER` as
`query.search` in `src/conn/ax_bridge.py`. Swift's
`NativeObservationQuery` does not parse a `search` field. The backend therefore
walks and returns the whole bounded tree, up to 300 nodes, regardless of the
query.

In the Firefox session, five different searches returned the same 34-node
tree. Input context grew from 11,384 tokens to 51,196 tokens. In the RIVER
session, two 300-node snapshots led to individual model responses costing
$0.3144 and $0.3472. The session crossed its $1 cap before the user's final
clarification could be handled.

This is the largest mechanical defect because every failed grounding attempt
makes the next attempt slower, more expensive, and less likely to finish.

### The resolver confuses safe ambiguity with needless ambiguity

The Firefox refusal was correct. The tree contained 31 `AXGroup` nodes, no
title or description matching Play, and repeated blank groups covering the
whole 2048 by 1152 window. Choosing one would have been an unsafe guess.

The Techmeme refusal was not correct. The selected target was a named
`AXLink` titled `RIVER` with `AXPress` and a small frame. More than one node
shared its semantic fingerprint, so `NativeObservationStore` returned
`ambiguous` immediately. It never tried the stricter path, sibling, role, and
frame locator already present later in the resolver.

The repair must preserve both outcomes: refuse anonymous full-window groups,
but allow a named target when the complete stable locator resolves to exactly
one current node.

### Clarification is conversational, not grounded

Conn asked whether the user meant the video area or a control, even though the
native tree supplied neither candidate. After the user answered `video area`,
Conn ran the same search and chose the same anonymous group. The RIVER flow did
the same with invented distinctions such as top menu, footer, header, and
sticky.

A clarification must be built from real candidates and survive into a fresh
observation. Today the answer changes the words in the next query but does not
bind a candidate identity or distinguishing attributes.

### The action language cannot express a common media command

The production surface can press a grounded Accessibility element. Raw
hotkeys are diagnostic-only, Space is not allowlisted, coordinates are absent,
and there is no model-visible visual lane. When a browser exposes an opaque
player with no named Play element, `click play`, `hit Space`, and `click the
video area` are all impossible under the current contract.

This is an architectural capability gap. Prompt iteration cannot solve it.

### Browser search is being asked to perform navigation

`browser_search` always turns its argument into a Google search and opens it in
the system default browser. It cannot directly navigate to a URL or honor an
explicit browser such as Safari.

The live consequences were predictable:

- a literal Techmeme URL became a Google query
- an explicit Safari request opened the default Firefox browser
- `Navigate to clawmessenger.com` opened Safari but never entered the URL
- `Navigate to plopmessenger.com` created a tab and stopped there

The model also spoke as if the full goal was underway when it had only opened
an app or created a tab.

### Verification deadlines can turn success into uncertainty

The Notes typing transaction returned `native_bridge_timeout` after 2,701 ms.
Python's deadline was exactly 2,700 ms: the 1,200 ms native verification budget
plus a fixed 1,500 ms margin. The user then said, `Yeah, nice. You did it.`

The receipt was correctly classified as `possibly_dispatched` and was not
retried. The defect is the deadline contract. Python can time out while native
capture, resolution, dispatch, recapture, verification, and receipt delivery
are still completing within the work Conn authorized.

### The flagship create witnesses still depend on favorable app shapes

Safari create drops its witness whenever more than one collection subtree is
kind-compatible. In the post-release live session, the tab opened, the plan
had no predicates, the receipt returned `dispatch_only`, and the user confirmed
the visible result.

Notes create compiled a row-count witness, but the chosen collection stayed at
18 rows and returned `no_effect`. The trace has no explicit eye verdict for the
creation itself, so this cannot be called a false negative. The evidence is
still enough to show that a virtualized or recycled list needs a stronger
witness and better measurements in the receipt.

The targeted Safari and Notes probes covered one favorable hierarchy each.
They did not cover the real multi-collection Safari state or recover the Notes
before and after counts needed to explain the miss.

### Prompt rules can override live app context

While Apple Notes was active, the user asked for `the note under our current
note`. The prompt's blanket rule for named notes sent the model to
`phoenix_search`, then opened an Obsidian file. Explicit app context and
relative language should have won.

### Barge-in can splice two responses together

The user interrupted result speech with `Delete the note.` The destructive
action was safely declined, but the next transcript was
`I sent it,I can't help with destructive actions yet.` A stale cancellation
and response buffer crossed the turn boundary.

The policy result was safe. The voice response was not isolated.

### Failure evidence is too weak to debug reliably

Seven `dispatch_only` receipts and the Notes `no_effect` receipt have
`reason_code: null`. The logs cannot directly distinguish no witness, witness
mismatch, or another honest ceiling.

Large tool artifacts are also clipped at 65,536 characters inside a serialized
JSON string. The RIVER and Techmeme artifacts end mid-object and cannot be
parsed as complete nested results. Two recent probe filenames say `verified`
while the independent observer says the expected app was not frontmost. Those
probes are invalid acceptance evidence even if the mismatch was a transient
focus race.

## What not to weaken

- Do not let a duplicate anonymous fingerprint resolve by coordinates alone.
- Do not turn a user's verbal confirmation into a machine `verified` receipt.
- Do not retry any action after a possible dispatch.
- Do not add app-specific command catalogs to patch individual websites.
- Do not count a native probe as accepted when its independent observer
  disagrees or still requires a visible human verdict.
- Do not send raw full Accessibility trees to the model as a substitute for
  grounding.

## Spec direction

The implementation draft is
`docs/2026-07-13-capable-navigation-spec.md`. Its load-bearing changes are:

- bounded native candidate search and replaceable model context
- full-locator resolution with grounded clarification
- one session grant for broad reversible navigation
- direct browser navigation, semantic activation, ordinary keys, and a
  model-visible window-bound visual lane
- generalized witnesses and one authoritative native transaction deadline
- current-app intent routing, clean barge-in boundaries, complete reason codes,
  and valid diagnostic artifacts

Start with observation and context replacement because they make every later
fix cheaper to test. The manual drill and 30-command product gate stay paused
until the candidate build is mechanically green against the captured live
failures.
