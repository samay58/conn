# Next session: physical v1 acceptance

Updated 2026-07-21. Read `docs/STATE-OF-PLAY.md` and
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

Final mechanical boundary:

- 815 Python tests passed, three intentionally deselected, two dependency
  warnings
- three lifecycle tests passed
- 14 of 14 harness evals passed
- 273 XCTest cases and 5 Swift Testing cases passed
- one fresh-clone smoke and its 100-iteration adversarial matrix passed
- ordinary Python tests left `data/` unchanged at 13,217 files, 161,294,146
  bytes, digest
  `a6a92476ec851e517b90891b6c1885ed94ed0ddcf51ab9a41958ce2b92e70409`
- installed `/Applications/Conn.app` passed strict codesign verification under
  `Conn Dev Signing`; CDHash
  `57cdc5f871be4c7dd2ef963e874219e6aceb8031`

The stabilized live intent corpus remains 224 of 226, or 99.1 percent, at
$1.6300. Artifact:
`data/intent-evals/2026-07-20/results-1784547543.json`. Prompt and model-visible
tool schemas did not change after that run, so no billed rerun was warranted.

The required `$check` pass ran before later Notes witness, Safari history, and
host-isolation hardening. Six validated findings from that review were fixed.
The later changes have targeted regression tests, full suites, live VM proof,
and a manual diff review. Do not describe the earlier review as covering those
later lines.

## Next execution block

Run physical acceptance on the installed candidate. Do not expand capability
unless a frozen gate fails.

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
