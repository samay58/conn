# Verified semantic engine live checklist

Updated 2026-07-20. The capable-navigation candidate and Conn Lab release
matrix are mechanically green.
This checklist is the human evidence layer for `docs/NORTH-STAR.md`; the north
star owns the complete v1 finish line and stop rule.
Run this only after the signed voice checks and the confidence drill in
`docs/MANUAL-TESTING.md` pass. Native probes and scripted evals are supporting
evidence, not product acceptance.

For current engineering confidence tests, use `docs/MANUAL-TESTING.md`.

## Product acceptance bar

Use Conn for 30 ordinary commands across at least three real work sessions.
The gate passes only when all of these are true:

- zero false completion language
- at least 90 percent of supported actions are faster than hands or useful
  while hands are occupied
- every dispatch-only result says `Sent, not confirmed.`
- every ambiguous target refuses before dispatch
- every possibly-dispatched result avoids automatic retry

Tests, simulated backends, fixture transactions, and one concentrated demo do
not satisfy this gate.

Conn Lab results may replace repeated engineering setup and regression probes.
They cannot count toward the 30 ordinary commands or the faster-than-hands
judgment.

Classify each planned command as supported or outside v1 before speaking it,
using the frozen capability matrix. A failed attempt stays in the supported
denominator. Do not reclassify it after seeing the receipt.

## Before each session

- Confirm the Mac is unlocked.
- Confirm `/Applications/Conn.app` is the persistent-signed current build.
- Start a fresh Conn session.
- Click the pointer-only navigation grant and confirm its visible state. Never
  carry a grant tally across daemon sessions or app execution connections.
- Use ordinary work, not a scripted sequence designed to flatter the engine.
- Keep risky actions bounded and non-destructive. Do not send messages, make
  purchases, change accounts, enter secrets, or delete data for this gate.

## Command mix

Across the 30 commands, cover each family at least twice where the app exposes
the needed native state:

| Family | Safe examples | Evidence Conn must use |
|---|---|---|
| App open or switch | Open Notes; switch to Terminal | Expected bundle is running and frontmost |
| Dynamic app | Open a harmless installed app outside configured aliases | Native installed identity and signer bind the requested app |
| Direct URL | Open example.com in Safari | Requested browser is exact; normalized document URL matches |
| Clipboard | Put this short phrase on my clipboard | Pasteboard hash matches payload hash |
| Tab focus | Focus the tab named Conn | Unique tab resolves and becomes selected or focused |
| Scroll | Scroll this result into view | Target enters viewport or scroll value moves in the requested direction |
| Text entry | Type a harmless query into this non-secure field | Focus is rechecked and non-secure value or hash matches |
| Element press | Press the enabled Refresh button | A target-bound element or value predicate changes |
| Visual activation | Play the opaque fixture target | Current image, app, window, frame, scale, grant, and point revalidate; receipt agrees with separate eye truth |
| Menu action | Use View, Show Sidebar | Lazy menu is opened and read; leaf resolves uniquely; current engine reports dispatch-only unless target-bound evidence survives |
| Key chord | Use an allowlisted harmless chord | Current engine reports dispatch-only; posting alone is never confirmation |
| Refusal | Target duplicate labels or a secure field | A genuine final tie or secure target refuses; a unique current visual grounding may safely resolve AX ambiguity |

Do not count an operation family as covered when Conn says it is unsupported in
that app. Record it as unsupported and use another ordinary command.

## Per-command record

Record one row after each command. Use the receipt and trace for technical
fields and your own judgment for the last column.

| # | Session | Command | App/window | Outcome | Dispatch state | Strategy | Evidence matched | Retry | Latency | Faster or hands-free useful? | Notes |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | | | | | | | | | | | |
| 2 | | | | | | | | | | | |
| 3 | | | | | | | | | | | |
| 4 | | | | | | | | | | | |
| 5 | | | | | | | | | | | |
| 6 | | | | | | | | | | | |
| 7 | | | | | | | | | | | |
| 8 | | | | | | | | | | | |
| 9 | | | | | | | | | | | |
| 10 | | | | | | | | | | | |
| 11 | | | | | | | | | | | |
| 12 | | | | | | | | | | | |
| 13 | | | | | | | | | | | |
| 14 | | | | | | | | | | | |
| 15 | | | | | | | | | | | |
| 16 | | | | | | | | | | | |
| 17 | | | | | | | | | | | |
| 18 | | | | | | | | | | | |
| 19 | | | | | | | | | | | |
| 20 | | | | | | | | | | | |
| 21 | | | | | | | | | | | |
| 22 | | | | | | | | | | | |
| 23 | | | | | | | | | | | |
| 24 | | | | | | | | | | | |
| 25 | | | | | | | | | | | |
| 26 | | | | | | | | | | | |
| 27 | | | | | | | | | | | |
| 28 | | | | | | | | | | | |
| 29 | | | | | | | | | | | |
| 30 | | | | | | | | | | | |

## Stop and file a bug immediately when

- Conn says `Done.` without matched evidence.
- Native dispatch success becomes verified by itself.
- Conn retries after a possibly-dispatched result.
- A stale response or prior observation reaches the executor.
- Two mutations execute concurrently.
- An ambiguous target is chosen instead of refused.
- A stale capture, changed window, changed frame, or revoked grant reaches input.
- A secure value, bridge secret, clipboard body, or image bytes appear in a
  trace or result.
- A dispatch-only, no-effect, ambiguous, or failed result renders green.

Preserve the trace and the action receipt. Record what your eyes saw separately
from what Conn reported.

## Final tally

At the end of session three, fill in:

- Commands attempted:
- Supported commands:
- Verified:
- Dispatch-only:
- No effect:
- Blocked:
- Ambiguous:
- Failed:
- False verified:
- Wrong targets:
- Automatic retries after possible dispatch:
- Supported commands faster than hands or hands-free useful:
- Percentage faster or useful:
- Product gate: pass or pending

The product gate is `pass` only if the acceptance bar at the top is met.
