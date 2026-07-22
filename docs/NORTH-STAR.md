# Conn north star

Updated 2026-07-20. This file defines what Conn v1 is for, what counts as
done, and when feature work stops. Safety invariants in the approved specs
still win. If another planning document describes a broader finish line, this
file controls v1 scope.

## Product promise

Hold one chord, say one natural sentence, release, and trust Conn to make the
right reversible foreground change on the Mac or say why it could not. Conn
never acts without a grounded target. If it dispatches an action but cannot
prove the effect, it says `Sent, not confirmed.`

Conn should remove attention, not demand supervision. No command syntax. No
watching the daemon. No cleanup after a failed attempt. No claim stronger than
the evidence.

## V1 boundary

V1 covers ordinary reversible navigation:

- read current app, window, selection, and visible context
- open or switch to an installed signed app
- open a direct URL in the requested browser
- activate one unique button, toggle, tab, row, list item, or visible control
- select a nearby item in a list, table, outline, tab group, or document set
- focus one unique non-secure field and type exact text
- scroll or move through the current page or document
- use a harmless menu action or fixed safe key with honest proof limits
- place bounded text on the clipboard behind its existing approval
- use bounded current-window visual grounding when Accessibility has no useful
  target
- continue a short goal through separate observed and receipted transactions,
  stopping on any uncertainty

Reference surfaces are Finder over a disposable folder, Calendar over local
seeded data, Preview over a generated PDF, Safari and Firefox over local pages,
Notes over disposable notes, Terminal for harmless window and menu behavior,
and ConnActionFixture for adversarial cases. These surfaces test generic
capabilities. Production code does not gain per-app commands, selectors, or
coordinates.

V1 does not send messages, create calendar events, move or delete files, make
purchases, change accounts, enter secrets, run shell commands, or perform
other destructive or outbound work. It does not need OCR, MCP, another model,
hidden macros, broad app catalogs, sound, character work, or more motion.

## Done means all four gates pass on one release candidate

One candidate means one source commit, config, signed app binary, golden VM,
scenario catalog, capability matrix, and command corpus. Any change to those
inputs starts the affected gate again.

### Truth

- zero wrong targets
- zero false `Done.` outcomes
- zero stale dispatches
- zero automatic retries after possible dispatch
- zero normal-path Realtime protocol errors
- zero manual daemon or VM cleanup
- every non-verified result has one stable reason and plain user message
- ordinary test runs create no real `data/` artifacts
- full Python, lifecycle, harness, Swift, build, signing, replay, and soak gates
  pass
- twenty fresh-clone release runs on the exact candidate match receipt with an
  independent oracle

### Useful breadth

- capability matrix and top-20 command corpus are frozen before production
  changes begin
- platform exposure is established by the capsule's independent setup and
  native observation, not by whether Conn succeeds
- a failed row stays in the denominator; it cannot be removed, relabeled as
  unsupported, or replaced after seeing Conn's result
- every required generic primitive succeeds in at least three structurally
  different exposed reference surfaces
- every required primitive has one adversarial case that refuses before
  dispatch
- every dispatched lab action has a receipt and independent oracle
- every unsupported shape has an honest measured ceiling
- the frozen top-20 ordinary commands reach at least 95 percent first-try
  completion and 99 percent after one safe clarification or replan
- live intent corpus remains at or above 97 percent without weakening an
  honest grader

### Daily use

- physical microphone barge-in, hardware hotkey, notch, and external-display
  checks pass
- fifteen-minute confidence drill passes
- thirty ordinary commands run across at least three real work sessions
- zero wrong targets, false completion language, unexplained failures, or
  manual cleanup during those sessions
- at least 90 percent of commands classified as supported before each session
  are faster than hands or useful while hands are occupied; failed attempts
  remain in that denominator
- warm semantic actions reach release-to-effect p50 at most 2.0 seconds and
  p95 at most 4.0 seconds
- after session three, Samay would leave Conn running and expect to use it in
  the next work session

### Craft

- invocation, listening, result, refusal, and recovery states are immediately
  understandable
- Conn never steals keyboard focus
- spoken and visible language is short, specific, and earned by evidence
- common commands need no memorized phrasing
- failures preserve the user's place and produce a useful report
- no unresolved issue from the three work sessions makes Conn annoying enough
  to avoid

Taste here means restraint. Conn should feel calm, fast, exact, and quiet.
Polish that does not improve trust, speed, clarity, or willingness to use it
does not block v1.

Samay owns the final craft judgment. Mechanical evidence can show correctness,
speed, and consistency. It cannot decide whether Conn feels calm enough to
leave running or useful enough to reach for tomorrow.

## Stop rule

When all four gates pass on one candidate, Conn v1 is done. Mark the release,
update the project record, and stop capability expansion.

Afterward, active work is limited to invariant failures, crashes, regressions
in the frozen matrix, and repeated daily-use pain. A new capability enters only
when real use produces either one named must-have job or three matching
failures across two sessions, and the fix can remain generic with a lab
scenario and independent oracle.

Deferred ideas stay deferred until their written trigger fires. A possibility
is not a requirement.

## Current distance

Mechanical reliability, capable navigation, Conn Lab, intent quality, and the
frozen real-app breadth are built. V1 is not done.

Open gates:

- physical-Mac confidence drill
- acoustic, hardware, notch, and external-display checks
- thirty-command, three-session daily-use gate

The frozen breadth gate passed 20 of 20 core commands and 9 of 9 supporting
coverage scenarios. All nine required jobs have at least three structurally
different successful surfaces and one source-validated adversarial refusal.
Every independent oracle matched its receipt. The exact-candidate 20-clone
release suite also passed with 20 verified receipts, 20 matching oracles, zero
protected host changes, and cleanup after every run. This closes non-human v1
implementation; it does not satisfy the remaining physical daily-use gates.

Next work should close these gates in order. It should not expand v1 scope.
