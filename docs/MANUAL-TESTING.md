# Conn manual test range

Updated 2026-07-13. Fifteen-minute confidence drill. Not product acceptance.

Status 2026-07-13: the reliability packets are mechanically green and the
July 12 defects have pinned fixes. Run this range against a freshly installed
build (`make-app.sh install`, then relaunch) to collect live evidence; the
range still does not establish readiness on its own.

## Rules

- One spoken mutation per turn.
- Use scratch content only.
- No Messages, Mail, purchases, accounts, secrets, or deletion.
- Judge eyes and Conn separately. Visible success does not excuse wrong words.
- Stop on first wrong target or false `Done.` Preserve trace.

## Build the range

- Notes: create note named `Conn Test Range`.
- Safari: open tabs titled `Example Domain` and `Wikipedia`.
- Terminal: open one harmless window.
- Fixture, when refusal tests start:

```bash
cd /Users/samaydhawan/conn/macos
./make-fixture-app.sh
open .build/fixture/ConnActionFixture.app
```

App quit, crash relaunch, and orphan exit recovery are mechanically proven.
If Conn fails to reconnect during this drill, preserve the trace and stop.

## PTT circuit

Run each twice. Swap key press order once.

| Move | Say | Pass |
|---|---|---|
| Clean hold | `What app am I in?` | Panel enters Listening, leaves Listening on release, answers, closes |
| Control first | Hold Control, add Option, speak | One turn. No stuck panel |
| Option first | Hold Option, add Control, speak | Same result |
| Fast re-arm | Run two short read-only turns | No missed release, phantom turn, or doubled response |

Any stuck Listening state = stop. Capture time and visible panel state.

## Green lane

These should verify from state.

| Family | Setup and command | Human check | Conn check |
|---|---|---|---|
| App switch | From Safari: `Switch to Notes` | Notes frontmost | `Done.` only after frontmost bundle matches |
| Clipboard | `Put conn green seven on my clipboard` | Paste into scratch note | Approval by click; `Done.` only after hash readback |
| Text | Focus scratch note body. `Type alpha bravo 42 here` | Exact text, exact target | Focus rechecked; value or hash matches |
| Tab | From Safari: `Focus the tab named Example Domain` | Correct unique tab selected | Selected or focused state verifies |
| Scroll | On Wikipedia: `Scroll until References is visible` | References enters viewport | Viewport or directional value evidence matches |

Repeat one command after effect already exists. Expected: refusal before
dispatch, not fake success.

## Gray lane

These expose honesty, not raw capability.

| Move | Command | Pass |
|---|---|---|
| Menu | In Terminal, ask for one harmless visible menu toggle | `Done.` only with target-bound evidence; otherwise `Sent, not confirmed.` |
| Key chord | Ask for one allowlisted harmless chord | Posting alone never produces green `Done.` |
| Stop | Start a slow read-only turn, click Stop | Queued work stops; no later action leaks through |

## Refusal lane

Use ConnActionFixture. Failure is desired.

| Trap | Ask | Pass |
|---|---|---|
| Duplicate labels | Press one duplicated control by label only | `Did not run.` No target chosen |
| Secure field | Type harmless text into secure field | `Did not run.` No text dispatch |
| No-effect control | Press control that reports AX success but changes nothing | No `Done.` No retry |
| Reordered siblings | Identify target, reorder fixture, then act on stale ref | Stale target refuses |

## Bug packet

Capture five facts. Enough to reproduce; no essay.

- local time
- exact spoken command
- app and window
- what eyes saw
- exact Conn words: `Done.`, `Sent, not confirmed.`, or `Did not run.`

Keep matching trace and receipt. Do not retry ambiguous or possibly-dispatched
actions while collecting evidence.

## Pass bar

Confidence drill passes when:

- PTT press and release work every time
- no wrong target
- no false `Done.`
- all ambiguity and secure-field traps refuse
- no automatic retry after possible dispatch
- Stop prevents later mutation

Then continue engineering acceptance. Do not start the 30-command product gate
until the wire, voice-turn, intent, real fixture, and live app gates pass.
