# Conn

Push-to-talk voice command surface for the Mac, built on the OpenAI Realtime
API (gpt-realtime-2). Hold a key, say a command, release: Conn takes the
smallest safe action through a local tool harness, shows an approval chip for
anything risky, and leaves a trace and a cost receipt for every session.

"You have the conn": the naval handoff of steering authority, spoken, bounded,
revocable. The stop button is "belay that."

Full design: [docs/gpt-realtime-2-computer-agent-spec.md](docs/gpt-realtime-2-computer-agent-spec.md)

## The native app (primary surface)

```bash
cd macos && ./make-app.sh && open Conn.app
```

Menu-bar app whose primary surface is the notch island: a black surface
that grows out of the notch on key-down with waveform, state word,
transcript, and live cost, breathes quietly while listening, and retreats
into the notch when the turn ends (spec:
[docs/2026-07-05-ux-craft-spec.md](docs/2026-07-05-ux-craft-spec.md), plan:
[docs/plans/2026-07-05-ux-craft-plan.md](docs/plans/2026-07-05-ux-craft-plan.md)).
The app autolaunches the daemon if one is not running (live if a key
resolves, demo otherwise). Hold Right Option to talk once Accessibility is
granted to Conn.app (menu: Enable Global Hotkey). No Conn surface ever
takes keyboard focus; approvals are deliberate clicks only. On non-notch
displays the older floating panel is the fallback surface. `Conn --preview`
renders key states for design iteration. The interactive approve/deny beat
inside the island lands with packet I8; until then the island shows an
approval preview row and the web console at 127.0.0.1:8787 carries the
approval clicks.

## Quickstart (demo, no credentials)

```bash
cd /Users/samaydhawan/conn
PYTHONPATH=src /Users/samaydhawan/conn/.venv/bin/python -m conn --demo --simulate-tools
# open http://127.0.0.1:8787
```

Type "find the transformer paper notes in my vault and open it", or hold Space
and speak (demo mode maps any speech to the default scenario). Watch the pill
walk through listening, thinking, acting, speaking, done; expand the footer
for the live trace and receipt. `--demo` without `--simulate-tools` runs the
scripted model against the real executors, so apps and notes actually open.

## Live mode

```bash
export OPENAI_API_KEY=...   # daemon-side only; the browser never sees it
PYTHONPATH=src /Users/samaydhawan/conn/.venv/bin/python -m conn
```

Defaults: model gpt-realtime-2, voice marin, reasoning effort low, session
cap $1.00 with a hard stop, warning at $0.50, idle disconnect after five
minutes. All tunable in `config.toml`. `--no-audio` runs live with typed
input only; `--no-hotkey` skips the global key.

## Permissions (TCC), in order of need

Everything attaches to the app that launches the daemon (Terminal, iTerm,
Ghostty). Pick one host and stay with it.

1. Microphone: auto-prompts on first launch. Required for voice.
2. Input Monitoring: only for the global Right Option hotkey. Grant manually
   in System Settings, Privacy and Security, then restart conn. Secure
   Keyboard Entry (an iTerm setting, or any focused password field) silently
   disables it. Console hold-Space PTT works without any of this.
3. Accessibility: optional. Adds window title and selected text to
   computer_get_context; without it you get the app name only.
4. Screen Recording: optional. Without it, computer_screenshot captures only
   the wallpaper and your own windows.

Check the machine any time:

```bash
PYTHONPATH=src /Users/samaydhawan/conn/.venv/bin/python -m conn --doctor
```

## Environment contract

| Variable / file | Purpose |
|---|---|
| `OPENAI_API_KEY` | Live sessions. Environment only; never in config or logs |
| `config.toml` | Hotkey, model, voice, budget, allowlists, vault paths, pricing table, server port |
| `data/` | Gitignored: traces (JSONL per session), receipts, eval results, session screenshots |

## Evals and tests

```bash
PYTHONPATH=src /Users/samaydhawan/conn/.venv/bin/python -m pytest tests -q   # 162 tests, no hardware needed
PYTHONPATH=src /Users/samaydhawan/conn/.venv/bin/python -m conn --eval       # 6 harness evals, writes artifacts
```

Live model quality has a manual checklist: [docs/LIVE_EVAL_CHECKLIST.md](docs/LIVE_EVAL_CHECKLIST.md).
Running Conn on a second machine (Mac Mini): [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md).

## Safety in one paragraph

The model proposes; the harness disposes. Low-risk tools (read context,
search, open allowlisted apps and notes) run at once. Anything escalated
shows a chip with the exact action and waits; 30 seconds without an answer is
a denial. Disabled tools (UI clicks, typing, hotkeys, accessibility tree)
return structured refusals. The daemon withholds the model's continuation
until every tool call has a real result, so it cannot claim something
happened before it did. Stop kills the turn and the session. The budget cap
is a hard stop, with per-turn costs visible live.

## Project layout

```
src/conn/            daemon: state machine, harness, adapters, audio, hotkey, server
console/             the web console (vanilla, no build step)
src/conn/realtime/scenarios/   demo scripts
evals/tasks.json     harness eval cases
docs/                spec + live eval checklist
data/                traces, receipts, evals (gitignored)
```

## Relationship to phoenix-voice-delegate

`01-active/projects/phoenix-voice-delegate/` is a different product lane: an
offline phone-call delegation lab (mission packets, fixtures, slot engine).
It stays archived in place. Conn inherits its discipline (traces, policy
gates, cost as part of the benchmark, the GPT-Realtime-2 notes in its
provider scorecard) but shares no code.
