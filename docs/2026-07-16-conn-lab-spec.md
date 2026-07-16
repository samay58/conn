# Conn Lab specification

Approved 2026-07-16. Conn Lab is the repeatable macOS acceptance environment
for Conn. It moves product engineering off the user's desktop without
substituting mocks for the production action path.

## Purpose

Conn Lab runs the real Python daemon, signed Conn.app, Accessibility,
ScreenCaptureKit, native pointer and keyboard input, fixtures, and installed
macOS apps inside a disposable macOS guest. Each run starts from known state
and records Conn's receipt beside an independent account of what changed.

The lab is capability-equivalent, not a copy of a personal Mac. It contains no
Apple ID, personal browser profile, personal notes, host home-directory mount,
or personal application data.

## System boundary

Python remains the policy plane. It owns grants, risk, provenance, context,
cost, model tools, and receipt validation.

The signed Conn.app remains the execution plane. It owns installed identity,
Accessibility, ScreenCaptureKit, coordinate conversion, dispatch, and effect
observation.

Lab code may seed app state and evaluate outcomes. It cannot add app-specific
behavior to the production compiler. The web console remains read-only.

The following truths remain fixed:

- one mutation at a time
- re-resolution immediately before dispatch
- raw native success never means verified
- visual motion alone never proves semantic success
- possibly dispatched actions never retry automatically
- secure, denied, destructive, stale, and genuinely ambiguous actions refuse
- risk, effect class, proof predicate, raw strategy, app identity, and
  coordinates are not model choices
- every non-verified result has one stable reason code
- observations replace stale context
- payloads, retries, tool calls, duration, and model cost are bounded

## Pinned environment

The lab uses Tart 2.32.1 and the macOS Tahoe base image:

```text
ghcr.io/cirruslabs/macos-tahoe-base@sha256:a8e1c8305758643f513fdccdd829c2243687c60791083dea42f73f0b7aeb435c
```

The golden guest is `conn-lab-golden`:

- macOS 26.5, build `25F71`
- 4 virtual CPUs
- 12 GB memory
- 80 GB disk
- 1440 by 900 point display
- automatic login to local `admin`
- no Apple ID
- persistent `Conn Dev Signing` identity
- Accessibility and Screen Recording approved once
- Safari, Notes, and Firefox 140.0.4

Runs use Tart's default NAT, disable host audio and clipboard sharing, mount
the repository read-only, and mount only the selected artifact directory
read-write. The daemon uses port 18787 inside the guest. Port 8787 on the host
is never used. Softnet is an explicit opt-in for a future measured networking
need. Missing Softnet privilege does not fail `doctor`.

Every accepted scenario uses a fresh copy-on-write clone. The clone is stopped
and deleted after artifacts are exported, including after timeout,
interruption, guest failure, or a failed command. A warm reusable guest may aid
local debugging, but its result cannot satisfy a release gate.

## Command surface

Run from the repository root:

```text
PYTHONPATH=src .venv/bin/python -m conn.lab doctor
PYTHONPATH=src .venv/bin/python -m conn.lab bootstrap
PYTHONPATH=src .venv/bin/python -m conn.lab run <scenario> [--mode scripted|live] [--fresh]
PYTHONPATH=src .venv/bin/python -m conn.lab suite smoke|release
PYTHONPATH=src .venv/bin/python -m conn.lab report <run-id>
```

`doctor` checks the pinned Tart version, base and golden images, signing
identity, fixture build, disk headroom, and artifact path. It reports Softnet
privilege as information.

`bootstrap` creates and sizes the golden image when absent. It stops for the
one required human task: install the signed app and approve Accessibility and
Screen Recording in the graphical guest. Existing ready images are not
modified.

`run` builds the candidate and executes one named scenario in a fresh clone.
`scripted` uses the frozen Realtime adapter. `live` uses the current Realtime
model and requires the normal API key.

`suite smoke` runs one fresh full-stack transaction and the 100-iteration
scripted adversarial matrix. `suite release` runs 20 fresh full-stack
transactions and the same matrix.

`report` reads one run ID and prints only the bounded comparison: scenario,
mode, receipt outcome and reason, oracle result, dispatch count, transaction
count, cost, and stage timings. It excludes image bytes, clipboard contents,
secrets, and private paths.

## Scenario contract

Versioned manifests describe:

```text
id
description
tier
mode
initial_state
spoken_or_typed_turns
navigation_grant_state
fault_schedule
expected_tool_family
expected_dispatch_count
expected_receipt
oracle
limits
required_capabilities
```

Faults are named transaction boundaries: before prepare, after prepare, before
dispatch, after first input, during verification, and during receipt delivery.
Production code has no arbitrary test-hook interface. The lab creates failures
through fixture behavior, bridge connection changes, guest process control,
window movement, grant revocation, and frozen Realtime behavior.

## Independent truth

Conn's receipt and the oracle are separate records.

- ConnActionFixture writes append-only truth events.
- Local browser pages report navigation, focus, playback, pointer, key, and
  scroll changes to a guest-local truth server.
- Safari evaluation checks requested URL and tab state through a lab-only
  adapter.
- Notes evaluation checks exact disposable note count, selection, and scratch
  content through a lab-only adapter.
- Firefox media evaluation reads the local page truth server.
- Screenshots preserve visible before and after state where useful.

An oracle match never upgrades a `dispatch_only` receipt to `verified`. A
verified receipt is accepted only when its own witness is valid and the
independent oracle agrees.

## Artifacts

Each run writes below:

```text
data/lab-runs/YYYY-MM-DD/<run-id>/
```

The bundle identifies the scenario, guest, Tart and image versions, Conn source
and binary identity, signing identity, daemon trace, action receipts, truth
events, bounded screenshots, logs, latency, cost, receipt, and oracle. `data/`
is ignored by Git.

## Automated coverage

The lab automates:

| Fully automated | Synthetic input | Physical Mac remains |
|---|---|---|
| Policy, Realtime, bridge, signing, grants, Accessibility, menus, Safari, Notes, Firefox, ScreenCaptureKit, pointer, keys, receipts, reconnects, stale-state refusal, crash cleanup | Recorded speech input and push-to-talk state | Microphone acoustics, physical hotkey hardware, notch presentation, external displays, daily-use judgment |

## Acceptance

Conn Lab is accepted when:

- one explicit command reaches a receipt and independent verdict from a clean
  guest
- fresh clone reset restores the exact initial-state digest
- VM-capable production lanes execute through the signed Conn.app
- current product blockers reproduce before their fixes and pass afterward
- no lab process posts host input, shares the host clipboard or audio, mounts a
  personal path, or writes outside the selected artifact directory
- before and after host snapshots record focus, pointer, clipboard,
  Applications metadata, and selected personal-data metadata without treating
  normal user activity as a lab failure
- no wrong target, false verified result, stale dispatch, or retry after
  possible dispatch occurs
- each verified receipt agrees with the independent oracle
- 20 fresh-clone smoke runs have no unexplained flake
- ordinary test suites create no file in the real `data/` tree
- artifacts bind build, guest, scenario, cost, latency, receipt, and oracle

The lab reduces human testing. It does not declare Conn ready for daily use.
The acoustic check, manual confidence drill, and 30-command product gate remain
physical-Mac judgments.
