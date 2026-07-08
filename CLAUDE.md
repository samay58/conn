# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What Conn is

Push-to-talk voice command surface for the Mac on the OpenAI Realtime API (gpt-realtime-2). Hold a key, speak, release; a local tool harness takes the smallest safe action, risky actions wait behind an approval chip, every session leaves a trace and a cost receipt.

**Reload order for project context**: `docs/STATE-OF-PLAY.md` first (where we are), then `docs/2026-07-07-roadmap.md` (what runs next and the judgment calls already made), then the specs in `docs/` and packet plans in `docs/plans/` (the how). `docs/idea-ledger.md` records what is deliberately not being built and the triggers that would change that; check it before proposing new capability.

## Commands

All Python commands run from the repo root with the project venv and `PYTHONPATH=src`:

```bash
# Tests (260, no hardware/TCC needed; pytest addopts skips the "hardware" marker)
PYTHONPATH=src .venv/bin/python -m pytest tests -q
PYTHONPATH=src .venv/bin/python -m pytest tests/test_state_machine.py -q          # one file
PYTHONPATH=src .venv/bin/python -m pytest tests -q -k "approval"                  # by keyword
PYTHONPATH=src .venv/bin/python -m pytest tests -q -m hardware                    # hardware-marked only

# Run the daemon
PYTHONPATH=src .venv/bin/python -m conn --demo --simulate-tools   # scripted model, canned tools, zero side effects
PYTHONPATH=src .venv/bin/python -m conn --demo                    # scripted model, REAL executors (apps actually open)
PYTHONPATH=src .venv/bin/python -m conn                           # live; needs OPENAI_API_KEY in the environment
PYTHONPATH=src .venv/bin/python -m conn --no-audio --no-hotkey    # live with typed input only, no mic/speaker/global key
PYTHONPATH=src .venv/bin/python -m conn --doctor                  # environment + TCC permission checks
PYTHONPATH=src .venv/bin/python -m conn --eval                    # 12 harness evals (evals/tasks.json), writes artifacts to data/
PYTHONPATH=src .venv/bin/python -m conn --latency-report          # latency spans + budget pass/fail on the newest trace

# macOS app (SwiftPM, macOS 14+; make-app.sh falls back to Xcode-beta toolchain if needed)
cd macos && ./make-app.sh              # release build, ad-hoc signed → Conn.app
cd macos && ./make-app.sh install      # also copies to /Applications
cd macos && swift test                 # Swift unit tests (ConnTests)
cd macos && swift test --filter NAME   # one Swift test class/method
./Conn.app/Contents/MacOS/Conn --preview   # renders key island states for design iteration
```

The web console (`console/`) is vanilla JS with no build step, served by the daemon at `http://127.0.0.1:8787`.

## Architecture

Two processes plus a browser surface:

- **Python daemon** (`src/conn/`): owns the Realtime session, the state machine, the tool harness, traces, cost, and the HTTP/WS server the surfaces connect to.
- **Swift menu-bar app** (`macos/Sources/Conn/`): the notch island, the primary UI. Connects to the daemon (`DaemonClient`), autolaunches one if none is running (`DaemonLauncher`). No Conn surface ever takes keyboard focus; approvals are pointer clicks only. The island carries its own approve/deny chip (packet I8).
- **Web console** (`console/`): the frozen debug fallback surface; approval clicks work here too, pointer-only.

### Daemon layering (the part worth internalizing)

- `state.py`: the session state machine. **Pure**: no I/O, no clocks, no threads. It consumes `MachineInput` events and returns a list of `Command` dataclasses. The anti-hallucination invariant is enforced structurally here: `CreateResponse` is emitted only when the response is closed AND every call in the pending-call ledger is resolved.
- `events.py`: the shared event/command vocabulary. Frozen dataclasses and enums only; the boundary rule at the top of the file forbids logic here. Use `mono_ms()` for all span math, never wall-clock.
- `app.py`: composition root. One asyncio loop owns everything; the machine decides, this file executes. The budget gate lives here because `response.create` is the only spend trigger and every one flows through `_exec`.
- `realtime/base.py`: adapter protocol with normalized `Rt*` events. `openai_ws.py` (live) and `fake.py` (scripted demo, driven by `realtime/scenarios/`) are the only two files that know about the wire, so API drift and demo mode each touch exactly one file.
- `tools/`: proposal pipeline in `harness.py`: parse args, schema check, risk gate (`risk.py`), execute on a thread with timeout, result envelope `{"ok": bool, "data"|"error", "duration_ms"}`. `registry.py` declares tool specs; `mac.py`, `phoenix.py`, `ax.py`, `ax_input.py` are executors; `fake_executors.py` backs `--simulate-tools`.
- `trace.py`, `cost.py`, `approval.py`: JSONL trace per session under `data/` (gitignored), token pricing from `config.toml` `[pricing]`, approval chips with 30s timeout-as-denial.

### Safety invariants (never traded away, in any packet)

1. **The harness owns permissions; the model only proposes.** `read`/`act_low` run at once, `act_confirm` waits on a chip, `blocked` returns a structured refusal. Config can escalate a tool but can never unblock a v0-disabled one.
2. **Continuations are withheld until tool results are real** (the pending-call ledger in `state.py`).
3. **The budget cap is a hard stop** ($1.00/session default, one gate in one place).

Plus two earned from incidents: approvals are pointer-only (no keyboard focus, ever), and the loop never lies about being alive (transport/session/daemon death becomes user-visible state within one second).

### Cross-language test guard

`tests/test_design_tokens.py` is a Python test that scans the Swift sources: all motion/personality/palette/geometry constants must live in `macos/Sources/Conn/DesignTokens.swift`. Adding a magic number to an animation curve in any scanned Swift file fails the Python suite. Check its `EXCLUDED_FILES` list before editing frozen panel-era files.

## Conventions

- `config.toml` holds all tunables (hotkey, model, budget, allowlists, vault paths, pricing). Secrets never live there; `OPENAI_API_KEY` is environment-only and must never reach config, logs, or the browser.
- `data/` (traces, receipts, eval results, screenshots) is gitignored; never commit its contents.
- The neighboring `phoenix-voice-delegate` project shares discipline but **no code** with Conn; do not import from it.

## Agent skills

### Issue tracker

Issues live in GitHub Issues on samay58/conn, via the gh CLI. See `docs/agents/issue-tracker.md`.

### Triage labels

The five canonical triage labels are used unmodified (needs-triage, needs-info, ready-for-agent, ready-for-human, wontfix). See `docs/agents/triage-labels.md`.

### Domain docs

Single-context: one CONTEXT.md and docs/adr/ at the repo root; neither exists yet; they're created lazily, so proceed silently if absent. See `docs/agents/domain.md`.
