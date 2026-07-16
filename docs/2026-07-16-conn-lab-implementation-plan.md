# Conn Lab implementation plan

Approved and executed 2026-07-16. This document records the packet contract,
test sequence, and evidence needed to reproduce the implementation.

## Delivery rule

Packets run in order. Each behavior change starts with the smallest failing
test, implements one vertical slice, passes targeted tests, then passes the
relevant broader suite. Only one packet is active at a time.

The working tree at entry was dirty and uncommitted. No file was staged,
stashed, reset, cleaned, or discarded during implementation. `data/` remained
evidence outside Git.

## L0: platform proof

Goal: prove the VM can exercise production paths before building orchestration.

Work:

- freeze the starting commit, dirty-tree digest, installed build, and data
  manifest
- record the Python, harness, Swift, and release-build baselines
- pin Tart and the Tahoe image digest
- prove headless boot, guest command execution, read-only source mount,
  writable artifact mount, Aqua launch, signed bridge, Accessibility,
  ScreenCaptureKit, pointer and keyboard input, and clone reset
- rebuild the signed app and prove TCC grants survive
- compare host Conn processes and UI state before and after

Gate: stop if the signed execution plane, native capture, or native input
cannot run in the guest.

Evidence: `docs/2026-07-16-conn-lab-platform-proof.md`.

## L1: runner and isolation

Goal: own disposable VM lifetime without touching host Conn.

Work:

- add strict scenario, run, oracle, and artifact records
- add bounded subprocess execution and cleanup
- require the guest marker before any command
- allow only the repository read-only mount and lab artifact read-write mount
- reserve guest daemon port 18787
- stop and delete only validated disposable VM names
- test clone, inspect, boot retry, command, export, timeout, interruption, and
  cleanup with a fake Tart executor

Gate: failure paths leave the golden image, host app, host daemon, and host
ports untouched.

## L2: deterministic fixture desktop

Goal: reproduce product edge cases with stable independent truth.

Extend ConnActionFixture with:

- unique and duplicate accessible controls
- genuine ambiguity and secure fields
- lazy menus and recapture-stable menu candidates
- nested tab collections and competing Notes-like collections
- delayed verification and no effect
- opaque media
- stale window frames, reordered siblings, app changes, and dispatch
  uncertainty

Every scene emits an append-only `scene_ready` event with a canonical starting
digest. Twenty fresh clones must produce the same digest.

## L3: full Conn loop

Goal: run a real transaction through the production composition root.

Work:

- launch real Python in the guest
- attach signed Conn.app over the authenticated bridge
- inject a typed command through the lab driver
- activate the navigation grant through guest-local pointer input
- use the frozen Realtime adapter
- exercise observation, preparation, policy, grant, revalidation, dispatch,
  verification, receipt, continuation, trace, and cost
- inject a bounded audio file for voice-state coverage

Gate: one clean guest produces a Conn receipt and independent fixture result.

## L4: current blockers

Menu target:

- freeze the lost menu-scope shape
- retain the exact menu path through preparation and recapture
- refuse changed, missing, or ambiguous items

Requested app:

- bind an explicitly named installed app to its resolved bundle
- refuse another bundle with `requested_app_mismatch`
- preserve clarification for multiple installed matches

Grant guidance:

- source one exact instruction from Python
- use the same text in status, receipt, and spoken response

Visual fallback:

- request one bounded current-window image only after zero actionable
  Accessibility candidates
- bind capture, normalized region, app, window, frame, scale, grant, and
  connection
- dispatch nothing after missing permission, stale state, or changed identity

Gate: the menu and wrong-app failures reproduce red, then pass. Opaque media
dispatches once and remains honest when no trustworthy witness exists.

## L5: real-app capsules

Safari:

- exact launch and local URL
- new tab with descendant-count witness
- lazy menu activation
- requested-browser preservation

Notes:

- disposable local note creation
- harmless scratch typing
- relative selection
- multi-collection witness and ambiguity refusal

Firefox:

- exact launch and local URL
- opaque Play through visual activation
- explicit Space
- wrong-app prevention

Each case records receipt, oracle, visible state, reason, and bounded tool
count. Browser pages are local. Notes uses disposable local state.

## L6: recovery matrix

Cover:

- upstream reconnect with navigation grant preserved
- app connection loss with grant revoked
- revocation after preparation
- stale semantic and visual observations
- moved and resized windows
- app switch and secure-state transition
- timeout before input and after first input
- late receipt
- no retry after possible dispatch
- repeated zero-candidate reads
- model-context replacement
- budget warning and hard stop
- barge-in isolation
- fixture and daemon crash cleanup

A failing test exposed an unbounded snapshot loop. The state machine now permits
two Accessibility reads per user turn and returns `grounding_read_limit` on
the third.

Gate: zero wrong completions, false verified outcomes, stale dispatches, or
retries after possible dispatch.

## L7: repeatability and speed

Work:

- record clone, boot, install, scenario, export, cleanup, and total timing
- run 20 fresh-clone full-stack transactions
- run the critical scripted matrix 100 times
- compare frontmost app, pointer, clipboard digest, Applications metadata, and
  watched personal-data metadata before and after
- report raw host activity without attributing ordinary user changes to the
  lab; isolation is enforced by mount, transport, port, and cleanup boundaries

Targets:

- stopped golden guest to verdict below three minutes
- warm debugging rerun below one minute
- zero unexplained flakes

Measured result: 20 of 20 fresh runs passed. Total p50 was 30.560 seconds and
p95 was 31.343 seconds. The 100-iteration matrix passed. Host changes were
empty.

## L8: live model

Run only after the scripted release suite is green.

Work:

- run the focused 25-item live intent sample
- run one full corpus after prompt and schema stabilization
- run fresh-guest live control, Safari tab, and Firefox visual scenarios
- compare model proposal, policy decision, native outcome, and oracle
- retain honest grading failures and stay below the $5 packet cap

Measured result:

- focused intent sample: 25 of 25, $0.266418
- authoritative corpus: 225 of 226, 99.56 percent, $1.392171,
  `data/intent-evals/2026-07-16/results-1784228271.json`
- control: verified receipt and matching oracle
- Safari tab: verified receipt and matching oracle
- Firefox Play: one bounded pointer dispatch, `dispatch_only` with
  `no_trustworthy_witness`, and one matching independent playback event
- total packet spend: $3.32165

The sole corpus miss proposed unsupported `r` for “Press the refresh button”
instead of grounding the visible control. It remains a failure.

## L9: delivery

Work:

- expose `doctor`, `bootstrap`, `run`, `suite`, and `report`
- use default Tart NAT; keep privileged Softnet as an explicit opt-in
- keep host snapshots diagnostic so Samay can use the Mac during a suite
- update the spec, state, roadmap, human test guides, idea ledger, and project
  commands
- rerun Python, lifecycle, harness, latency, Swift, build, codesign, lab
  release, data immutability, language, and diff checks
- review the complete diff once
- install the signed candidate only after mechanical green
- stage only intended source and documentation
- commit once on main and push only if local and remote state are safe

Human work deliberately remains:

- microphone acoustic barge-in check
- manual confidence drill
- 30-command product gate over three ordinary sessions

Measured result:

- 86 focused lab tests pass
- public `doctor` passes with default NAT and reports Softnet as unprivileged
  information
- final public smoke passed one fresh clone with one verified receipt, one
  matching oracle, 100 of 100 scripted iterations, and 31.979 seconds total;
  headless VNC cleanup left no Screen Sharing process
- `lab-release-161704` completed 20 of 20 verified fresh-clone transactions
  with 20 matching oracles; total p50 was 31.014 seconds and p95 was 31.434
  seconds
- that command used the old raw host-state gate and exited red because Samay
  moved the pointer and changed the clipboard during its ten-minute run; the
  transaction set itself was green
- the corrected host contract reports such activity without attributing it to
  the lab; 16 more fresh-clone transactions passed before terminating a stale
  host Screen Sharing process closed the seventeenth VNC connection
- cleanup deleted the interrupted clone; only the stopped golden and OCI
  images remained
- `lab-release-160545-19` records one explained native uncertainty:
  `AXPress` changed the fixture once, returned `kAXErrorCannotComplete`, and
  Conn kept the receipt failed and possibly dispatched without retry

## Packet evidence

| Packet | Focused evidence | Live evidence | Remaining ceiling |
|---|---|---|---|
| L0 | 644 Python, 205 Swift, 14 harness | Signed bridge, AX, capture, input, reset | One-time TCC setup |
| L1 | 10 focused runner/model tests | Clone, command, export, cleanup in 21.2s | None |
| L2 | 8 fixture tests, 212 Swift | 15 scenes, 20 identical resets | None |
| L3 | 31 focused Python | Typed and audio full transactions verified | Physical microphone |
| L4 | 10 Python, 11 app checks | Menu verified; visual dispatch-only with matched oracle | Native visual witness absent |
| L5 | 62 Python, 42 Swift | Safari and Notes verified; Firefox dispatch-only | Firefox exposes no trustworthy witness |
| L6 | 233 Python, 100 Swift | Exit-17 guest cleanup proof | None |
| L7 | 70 focused lab tests | 20 fresh clones and 100 scripted iterations | Physical Mac surfaces |
| L8 | 25 of 25 focused intent; 225 of 226 full | Three fresh live-model transactions | One honest intent miss |
| L9 | 86 focused lab tests; 741 Python; 232 Swift | 20 verified fresh clones plus one explained honest AX uncertainty | Human product gates |
