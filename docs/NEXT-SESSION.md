# Next session: physical v1 acceptance

Updated 2026-11-12. Read `docs/STATE-OF-PLAY.md` and
`docs/NORTH-STAR.md` first.

## WHERE WE LEFT OFF

Capability implementation and non-human release evidence are complete. Do not
add another v1 primitive unless an existing north-star gate proves one is
missing.

The exact breadth gate passed 29 of 29 scenarios:

- core corpus: 20 of 20
- supporting coverage: 9 of 9
- required jobs: 9 of 9 across at least three structurally different surfaces
- adversarial refusal families: 9 of 9 source-validated
- transactions and dispatches: 34 of 34
- receipt outcomes: 19 `verified`, 10 `dispatch_only`
- independent oracles: 29 of 29 matched
- safe replans: zero
- protected host changes: zero
- model cost: $0.0587
- clone timing: p50 34.146 seconds, p95 39.647 seconds

Artifact:
`data/lab-runs/2026-07-21/v1-breadth-174932-summary.json`.
SHA-256:
`2a6ea748c4e0c7f838f9e3bd3dc8e41b7637f43ee613c7a84296ba9511d13f60`.

The exact-candidate release suite passed 20 of 20 fresh clones. Every receipt
was `verified`, every independent oracle matched, the 100-iteration
adversarial matrix passed, protected host state did not change, and every
disposable guest was deleted. Total timing was p50 31.471 seconds and p95
32.932 seconds. Cost was $0.0440. Artifact:
`data/lab-runs/2026-07-21/lab-release-232513-suite.json`.
SHA-256:
`55da053dbbf68c325746581a3a4f9bd4343c2c0eb2d2d9b9a05cc39cc1d6f5e9`.

Notes next selection now binds the selected row to structurally matching peers.
The live witness moved from peer index 0 to 1, the receipt was `verified`, and
the disposable Notes database matched the exact selected object. A stale
selection, reordered peers, duplicate collections, or a multi-peer jump cannot
verify. Safari and Firefox visual activation remain honestly `dispatch_only`
when the page oracle matches but Conn has no trustworthy semantic witness.

Mechanical boundary on 2026-11-11, after the audit fixes in
`docs/STATE-OF-PLAY.md` ("November 10 and 11 hardening"):

- `./verify.sh` passed: 890 Python tests (all 14 harness evals included),
  three intentionally deselected, two dependency warnings; 289 XCTest cases
  and 5 Swift Testing cases
- three lifecycle tests passed
- installed `/Applications/Conn.app` passed strict codesign verification under
  `Conn Dev Signing`; CDHash
  `3b0837242c3ad055d469d8200fe0d218726808d2`

The live model is now `gpt-realtime-2.1`. Its intent corpus run passed 224 of
226, or 99.1 percent, at $1.3756, matching the best `gpt-realtime-2` run with
the same two misses. Artifact:
`data/intent-evals/2026-11-11/results-1794420938.json`. With the Shortcuts
tools added, the 232-item corpus passed 228, including all six Shortcuts items
(`results-1794424314.json`). The July lab breadth
and release suites above ran on `gpt-realtime-2` and have not been rerun.

The required `$check` pass ran before later Notes witness, Safari history, and
host-isolation hardening. Six validated findings from that review were fixed.
The later changes have targeted regression tests, full suites, live VM proof,
and a manual diff review. Do not describe the earlier review as covering those
later lines.

## Next execution block

Run physical acceptance on the installed candidate. Do not expand capability
unless a frozen gate fails. Two live checks cover the November fixes: kill the
daemon mid-turn and confirm the island shows "Reconnecting" within a second;
press Stop during a computer action and confirm Stop returns at once with the
action's real outcome.

Open decisions for Samay: typing under the navigation grant runs with no
approval chip; navigation has no per-host rule and chip previews hide the
payload; the idle disconnect never fires (keep sessions connected, or close
after five idle minutes and reconnect on the next push-to-talk).

## Connectors: the live steps (with Samay at the Mini)

Built and merged on 2026-11-11: the MCP client, gates, sign-in, eval fixtures
and the Phoenix side's local server. The private wiring plan is
`plans/018-wire-connectors-and-measure.md` (gitignored). `config.local.toml`
exists with `[mcp] enabled = false`. What is left:

1. `python -m conn --mcp-login granola`, then `wispr`, then `superhuman`, one
   browser sign-in each. Then `--mcp-tools`, pick Superhuman's two read tools,
   and pin the personal account with `fixed_args` (no pinnable argument is a
   stop).
2. Run the protected-meeting check from the plan, so work meetings come back
   withheld.
3. Approve up to $5 for the live intent eval. The gate is: the original 232
   items score at least 226, and the connector items score at least 90%.
4. `cd macos && ./make-app.sh install` (adds the Notes, Reminders and Calendar
   usage strings), set `enabled = true`, reopen Conn.app, approve the macOS
   prompts, and say the 16 commands in `plans/VOICE-CONNECTORS.md`.
   The first Reminders read asks macOS for Conn's Reminders access; until it
   is approved, reads fall back to AppleScript and take 9 to 20 seconds.
5. While saying them, check the island: a slow read shows its plain label
   ("Searching Granola") after 0.25 s and a fast one shows none; a write's
   whole preview ("Remind tomorrow 9 AM: Call the vet") sits above Deny and
   Approve; a write that cannot be confirmed reads "Sent, not confirmed".

Added on 2026-11-12, untested live: reads send structured results without
the duplicate text (Phoenix reads 55 to 65 percent smaller), and the
connector prompt section appears only when connector tools are exported.
One candidate for the eval run: skip the spoken preamble before Phoenix
reads, which now answer in 0.1 to 0.3 seconds. Measure it before keeping it.

## Added on 2026-11-12 (second half), live checks pending

- Cost per command: every turn now leaves a `turn_cost` trace event (lengths and dollars, never the words), the receipt has `per_command` and `by_category`, and `--cost-report [trace | --days N]` prints them. The first trial cost $0.031 per command; spoken audio was 37.5 percent of it.
- Cards: connector tools name a card template in config. Lists (who is waiting, today, calendar, a thread) and reply drafts show on a card under the island; Conn speaks one sentence. A send shows its whole text on the card while the chip waits for Approve, then settles as sent, sent-not-confirmed or not sent from the real result.
- Replies: `phoenix_draft_reply` drafts in Samay's voice from the live thread; `phoenix_send_text` sends through Messages or WhatsApp after Approve and reads the message back from the app's own store. WhatsApp is pressed only when the open chat is that person's and its message box holds exactly the approved text; the press goes through accessibility, never a keystroke. A refusal before sending says "not sent".
- Native: Obsidian note opens and Safari page loads now have witnesses; `computer_zoom` (no approval) and `computer_close_tabs` (approval, never the last tab) are new.
- Island: style D (the icon's character) is being refined to become the default; classic stays selectable. New app icon.

- Voice and tone: cedar with a light British accent; crisp, with an occasional dry aside built from a concrete detail of the result, never on failures, approvals or sends. Live intent eval on the new prompt: 268 of 276 at $2.42 (`data/intent-evals/2026-11-12/results-1794498661.json`); the original 232 scored 228, the new connector items 40 of 44. Misses worth a prompt pass: "summarize the latest recruiter email" (the mail rule wants a named person) and "I'm done with the dentist" (strike rule too strict).
- Waveform: driven by real speech through `WaveformEngine` (ripple from the center, noise gate, soft knee, breathing silence, its own thinking glide, eye blinks on pauses, reduced motion respected); `Conn --playtest-waveform` renders filmstrips from a wav.

Live checks still open: Safari address read on a real page, Safari tab close buttons, zoom menu names in Safari, Obsidian and Notes, the WhatsApp send end to end, the D island on a real desktop, mic gain and voice sync for the waveform, and whether the island's shadow swallows clicks just outside it.

## Human gates still open

- microphone acoustic barge-in
- hardware hotkey behavior
- notch and external-display presentation
- fifteen-minute confidence drill in `docs/MANUAL-TESTING.md`
- thirty ordinary commands across three sessions
- at least 90 percent of supported commands faster than hands or useful while
  hands are occupied
- warm semantic release-to-effect p50 at most 2 seconds and p95 at most 4
  seconds
- final judgment: would Samay leave Conn running and use it tomorrow?

Do not call Conn done before those gates pass. Do not expand v1 after they do.
