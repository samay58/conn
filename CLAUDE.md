# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What Conn is

Push-to-talk voice command surface for the Mac on the OpenAI Realtime API (gpt-realtime-2). Hold Control+Option, speak, release; the daemon takes the smallest safe action, risky actions wait behind a pointer-only approval chip, and every state-changing computer action runs as a verified transaction through the signed Conn.app. Every session leaves a trace and a cost receipt.

**Reload order for project context**: `docs/STATE-OF-PLAY.md` first (where we are and the measured bars), then `docs/NORTH-STAR.md` (the v1 promise, finish line, and stop rule), `docs/2026-07-07-roadmap.md` (what runs next and the judgment calls already made), `docs/NEXT-SESSION.md` (the next execution block), and the specs in `docs/`; the approved action spec is `docs/2026-07-09-verified-action-engine-spec.md`. `docs/idea-ledger.md` records what is deliberately not being built and the triggers that would change that; check it before proposing new capability.

A git-excluded local `AGENTS.md` mirror of this file (header aside) may exist at the repo root for Codex; when it does, apply any edit made here to it too.

## Commands

All Python commands run from the repo root with the project venv and `PYTHONPATH=src`:

```bash
# Tests (no hardware/TCC needed; addopts skip the "hardware" and "lifecycle" markers)
PYTHONPATH=src .venv/bin/python -m pytest tests -q
PYTHONPATH=src .venv/bin/python -m pytest tests/test_state_machine.py -q          # one file
PYTHONPATH=src .venv/bin/python -m pytest tests -q -k "approval"                  # by keyword
PYTHONPATH=src .venv/bin/python -m pytest tests -m lifecycle -q                   # real daemon quit/crash/orphan cycles on a test port
PYTHONPATH=src .venv/bin/python -m pytest tests -q -m hardware                    # hardware-marked only

# Run the daemon
PYTHONPATH=src .venv/bin/python -m conn --demo --simulate-tools   # scripted model, canned tools, zero side effects
PYTHONPATH=src .venv/bin/python -m conn --demo                    # scripted model, REAL executors (apps actually open)
PYTHONPATH=src .venv/bin/python -m conn                           # live; needs OPENAI_API_KEY (or ~/.config/openai/key)
PYTHONPATH=src .venv/bin/python -m conn --no-audio --no-hotkey    # live with typed input only, no mic/speaker/global key
PYTHONPATH=src .venv/bin/python -m conn --doctor                  # environment + TCC permission checks
PYTHONPATH=src .venv/bin/python -m conn --eval                    # 14 harness-only evals (scripted adapter; not model quality)
PYTHONPATH=src .venv/bin/python -m conn --intent-eval 25          # live model intent eval over evals/intent_corpus.json (billed; omit the number for all 219)
PYTHONPATH=src .venv/bin/python -m conn --latency-report          # latency spans + budget pass/fail on the newest trace
PYTHONPATH=src .venv/bin/python -m conn --action-probe fixture    # installed-app smoke probe (also terminal|safari|chrome|notes|obsidian) → data/action-probes/

# Disposable macOS lab
PYTHONPATH=src .venv/bin/python -m conn.lab doctor
PYTHONPATH=src .venv/bin/python -m conn.lab run safari-tab --mode scripted --fresh
PYTHONPATH=src .venv/bin/python -m conn.lab suite smoke
PYTHONPATH=src .venv/bin/python -m conn.lab suite breadth
PYTHONPATH=src .venv/bin/python -m conn.lab suite release
PYTHONPATH=src .venv/bin/python -m conn.lab report RUN_ID

# macOS app (SwiftPM, macOS 14+)
cd macos && ./make-app.sh              # release build → Conn.app (script picks a working toolchain, prefers Xcode-beta)
cd macos && ./make-app.sh install      # also copies to /Applications
cd macos && swift test                 # Swift unit tests (ConnTests); bare swift may need DEVELOPER_DIR=/Applications/Xcode-beta.app/Contents/Developer
cd macos && swift test --filter NAME   # one Swift test class/method
./Conn.app/Contents/MacOS/Conn --preview   # renders key island states for design iteration
```

Signing matters for dev workflow: `make-app.sh` signs with the persistent `Conn Dev Signing` identity when the keychain has it, so TCC grants (Accessibility, Microphone) survive rebuilds; the ad-hoc fallback loses grants on every rebuild. Action probes and live semantic actions require the persistent-signed app installed in `/Applications`; they block before dispatch otherwise.

The web console (`console/`) is vanilla JS with no build step, served by the daemon at `http://127.0.0.1:8787`.

## Architecture

Two processes plus a read-only browser surface:

- **Python daemon** (`src/conn/`): the policy plane. Owns the Realtime session, the pure state machine, the provenance ledger, risk/approval, mutation serialization, native plan preparation and receipt validation, traces, cost, and the HTTP/WS server (`server/http.py`).
- **Swift menu-bar app** (`macos/Sources/Conn/`): the execution plane and the primary UI. Owns the notch island (floating panel fallback on non-notch displays), configurable global push-to-talk, and all production Accessibility observation, target resolution, dispatch, and effect verification (`NativeSemanticActionEngine`, `NativeAXSemanticBackend`, `NativeObservationStore`). Connects to the daemon (`DaemonClient`), autolaunches one if none is running (`DaemonLauncher`). No Conn surface ever takes keyboard focus; approvals are pointer clicks on the island chip only. `macos/Sources/ConnActionFixture/` is an independent native test fixture with its own truth log.
- **Web console** (`console/`): observation only, and disabled unless started with `CONN_CONSOLE_CAPABILITY`. It cannot approve, initiate actions, claim the app control role, or answer native RPC.

### Daemon layering (the part worth internalizing)

- `state.py`: the session state machine. **Pure**: no I/O, no clocks, no threads. It consumes `MachineInput` events and returns a list of `Command` dataclasses. The anti-hallucination invariant is enforced structurally here: `CreateResponse` is emitted only when the response is closed AND every call in the pending-call ledger is resolved.
- `events.py`: the shared event/command vocabulary. Frozen dataclasses and enums only; the boundary rule at the top of the file forbids logic here. Use `mono_ms()` for all span math, never wall-clock.
- `app.py`: composition root. One asyncio loop owns everything; the machine decides, this file executes. The budget gate lives here because `response.create` is the only spend trigger and every one flows through `_exec`.
- `realtime/base.py`: adapter protocol with normalized `Rt*` events. `openai_ws.py` (live) and `fake.py` (scripted demo, driven by `realtime/scenarios/`) are the only two files that know about the wire, so API drift and demo mode each touch exactly one file.
- `tools/`: proposal pipeline in `harness.py` (parse args, schema check, risk gate in `risk.py`: read/act_low/act_confirm/blocked), then two execution paths. Local reads and low-risk tools execute on a thread with timeout. Computer mutations are compiled into a bounded plan (`native_actions.py`) and executed by Conn.app over the bridge; production has **no Python AX/input fallback** (`ax.py`/`ax_input.py` are legacy/test paths; `fake_executors.py` backs `--simulate-tools`). Result envelope is always `{"ok": bool, "data"|"error", "duration_ms"}`.
- `ax_bridge.py`: the authenticated (HMAC-token) observation/action RPC channel to Conn.app.
- `provenance.py`: turn and observation epochs that bind each plan to the observation it was prepared against; stale plans refuse before dispatch.
- `identity.py`: TCC process identity. It names the code image the kernel actually runs so permission grants land on the right artifact.
- `trace.py`, `cost.py`, `approval.py`, `latency.py`: JSONL trace per session under `data/` (gitignored), token pricing from `config.toml` `[pricing]`, approval chips with 30s timeout-as-denial, latency spans computed from traces against the UX budget table.

### The verified-action contract (the core of the design)

Every state-changing computer action is one bounded transaction: observe → resolve target against current native state → prepare one plan with effect predicates → apply risk policy and pointer approval to that exact plan → revalidate → dispatch one strategy → observe again → classify from evidence. Outcomes (`actions.py`) are `verified`, `dispatch_only`, `no_effect`, `blocked`, `ambiguous`, `failed`. Mutation `ok` is true **only** for `verified`; native API success is a dispatch fact, not proof of effect. Receipts carry `reason_code` and `safe_user_message`; the model speaks the safe message, never internal terms. One replan is allowed only after proven `not_dispatched` (plus at most two predispatch compile failures per turn, never the same plan shape twice); a `possibly_dispatched` action is never retried automatically.

Ordinary actions are semantic intents, not mechanisms: the model calls `computer_create` / `computer_select_relative` with goal slots only, and the Swift engine lowers them onto live affordances (menu discovery, selection siblings) with compiler-owned witnesses. `desired_effect` no longer exists in any model-visible schema, and raw `app_menu` / `computer_hotkey` are `diagnostic=True` registry entries hidden from `export_openai` by default.

### Safety invariants (never traded away, in any packet)

1. **The harness owns permissions; the model only proposes.** `read`/`act_low` run at once, `act_confirm` waits on a chip, `blocked` returns a structured refusal. Config can escalate a tool but can never unblock a v0-disabled one.
2. **Continuations are withheld until tool results are real** (the pending-call ledger in `state.py`).
3. **The budget cap is a hard stop** ($5.00/session default, one gate in one place).
4. **Mutation `ok` means verified effect evidence**, and a possibly-dispatched action never auto-retries.

Plus rules earned from incidents: approvals are pointer-only inside the signed app (no keyboard focus, ever; the console cannot approve), and the loop never lies about being alive (transport/session/daemon death becomes user-visible state within one second).

### Cross-language test guard

`tests/test_design_tokens.py` is a Python test that scans the Swift sources: all motion/personality/palette/geometry constants must live in `macos/Sources/Conn/DesignTokens.swift`. Adding a magic number to an animation curve in any scanned Swift file fails the Python suite. Check its `EXCLUDED_FILES` list before editing exempt files.

## Conventions

- `config.toml` holds all tunables (model, budget, allowlists, vault paths, pricing, semantic timeouts). Secrets never live there; `OPENAI_API_KEY` is environment-only (or `~/.config/openai/key`) and must never reach config, the bridge, traces, or the browser. The installed app's push-to-talk key comes from its persisted menu setting (default Control+Option), not from `config.toml` `[hotkey]`, which is the daemon-only fallback.
- `data/` (traces, receipts, eval results, screenshots, action probes) is gitignored; never commit its contents.
- The neighboring `phoenix-voice-delegate` project shares discipline but **no code** with Conn; do not import from it.

## Agent skills

### Issue tracker

Issues live in GitHub Issues on samay58/conn, via the gh CLI. See `docs/agents/issue-tracker.md`.

### Triage labels

The five canonical triage labels are used unmodified (needs-triage, needs-info, ready-for-agent, ready-for-human, wontfix). See `docs/agents/triage-labels.md`.

### Domain docs

Single-context: one CONTEXT.md and docs/adr/ at the repo root; neither exists yet; they're created lazily, so proceed silently if absent. See `docs/agents/domain.md`.
