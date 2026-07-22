# Conn v1 capability breadth implementation record

Updated 2026-07-21. The execution contract is
`docs/2026-07-20-v1-capability-breadth-spec.md`.

## B0: freeze evidence

Completed.

- froze the 72-row capability matrix
- froze the twenty-command corpus
- froze sanitized menu-target, wrong-browser, repeated-zero-candidate, and
  opaque-Play incidents
- recorded 793 Python tests, 261 Swift tests, three lifecycle tests, and 14
  harness evals as the current local boundary
- proved ordinary Python tests leave `data/` unchanged

## B1: capsule and oracle seams

Completed.

- moved scenario selection into typed capsule setup and oracle records
- kept app-specific setup and truth outside production behavior
- added deterministic Finder, Calendar, Preview, browser, Notes, Terminal, and
  fixture cases
- kept one disposable headless Tart clone at a time with cleanup on every exit

## B2: action facade

Completed.

- routed semantic and visual native ownership through one explicit facade
- retained Python policy ownership and Conn.app execution ownership
- added focused facade tests without changing receipt semantics

## B3: failure promotion

Completed.

- added bounded promotion from sanitized trace or lab record to a review
  candidate
- separated captured facts, missing setup, expected behavior, and unresolved
  questions
- excluded image bytes, clipboard bodies, secrets, private paths, and
  arbitrary host content
- promotion never changes policy or blesses an expected result

## B4: native atlas

Completed.

The stable atlas artifact is
`data/lab-runs/2026-07-20/atlas-20260720-051006`. It records 47 exposed and 25
unresolved rows. The unresolved rows remain in the frozen report and are not
treated as Conn failures unless the required native shape is exposed.

The Firefox capsule was made deterministic by restarting Firefox, loading one
guest-local page, and waiting for its independent accessibility-ready event.
The final atlas matches the first complete 72-row exposure record exactly.

## B5: generic vertical slices

Completed where the platform supplied a safe lane.

- Finder named selection uses a live list row and verifies selection. Icon
  view remains unsupported because it exposes focus without selection.
- Finder search uses Find focus and exact typing as two observed, verified
  transactions.
- Calendar Today and next month dispatch once and remain honestly
  `dispatch_only` while independent month-state oracles match.
- Preview uses a unique structural `Page N of M` witness. Page Down followed by
  a fresh observation and Right Arrow reaches page three with two verified
  receipts.
- Terminal follows one exact create-window menu parent to its single enabled
  shortcut leaf, then verifies the window-count change.
- Firefox opaque Play uses bounded current-window visual grounding, dispatches
  once, and remains `dispatch_only` while the page oracle matches.
- the composed fixture goal creates one window, re-observes, then selects one
  row in a second verified transaction.

Each slice retained compiler-owned risk and proof. No app branch entered
production.

## B6: lab reliability

Completed.

- direct URL capsules now start from Terminal, which makes status-item setup
  deterministic and proves exact browser switching
- VNC connection retries are bounded to three attempts before any input
- the scenario contract accepts `verified` as stronger than an expected
  `dispatch_only` floor, but never accepts weaker evidence for `verified`
- the breadth report now prints first-try and after-safe-replan rates

## B7: close the breadth gate

Completed.

The initial Notes setters returned native success without effect. A live menu
probe found no exact next-note affordance, so Conn correctly did not retry
after dispatch. The replacement lane is generic: when virtualized content
offers no working semantic setter, the compiler binds the selected row and its
structural sibling, re-resolves both, sends one fixed navigation key, and
verifies an exact move among structurally matching peers. Changed order,
duplicate candidates, multiple selected rows, stale selection, and multi-peer
jumps refuse before input or cannot verify.

The disposable Notes database oracle matched the selected object, and the
receipt returned `verified`. Production contains no Notes branch.

The supporting suite now proves three surfaces for every required primitive.
Its nine adversarial refusal mappings are source-validated against the named
tests. The combined gate fails if a scenario contract, surface count, refusal
source, receipt, or oracle is missing.

## B8: release evidence

In progress on the stabilized breadth candidate.

- frozen breadth and supporting suite: complete, 29 of 29, coverage green
- ordinary Python: complete, 815 passed with real `data/` unchanged
- lifecycle: complete, 3 passed
- harness: complete, 14 of 14
- doctor and smoke: complete; one fresh clone and 100 adversarial iterations
- Swift: complete, 273 XCTest cases and 5 Swift Testing cases
- release build and strict codesign: complete
- live intent corpus: complete, 224 of 226
- complete-diff review: complete; six validated boundary, proof, containment,
  and gate findings fixed
- exact-candidate twenty-clone release suite: complete, 20 of 20
- install without restarting a running host Conn process

The accepted breadth artifact is
`data/lab-runs/2026-07-21/v1-breadth-174932-summary.json`, SHA-256
`2a6ea748c4e0c7f838f9e3bd3dc8e41b7637f43ee613c7a84296ba9511d13f60`.
It completed 20 of 20 core and 9 of 9 supporting scenarios, all first try,
with 34 dispatches, 29 matching oracles, zero host changes, and $0.0587 cost.

The exact-candidate release suite passed 20 of 20 fresh clones with verified
receipts, matching independent oracles, zero protected host changes, and
cleanup after every run. Total timing was p50 31.471 seconds and p95 32.932
seconds. Cost was $0.0440. Artifact:
`data/lab-runs/2026-07-21/lab-release-232513-suite.json`, SHA-256
`55da053dbbf68c325746581a3a4f9bd4343c2c0eb2d2d9b9a05cc39cc1d6f5e9`.

The stabilized live intent corpus passed 224 of 226, or 99.1 percent, for
$1.6300. Artifact:
`data/intent-evals/2026-07-20/results-1784547543.json`. The two honest misses
remain in the grader.

## Human gates

Still open:

- microphone acoustic barge-in
- hardware hotkey
- notch and external-display presentation
- fifteen-minute confidence drill
- thirty ordinary commands across three work sessions
- Samay's final decision to leave Conn running and use it tomorrow
