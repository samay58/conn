# Conn

Conn is a push-to-talk voice command surface for the Mac, built on the OpenAI
Realtime API. Hold a key, speak, and release. Python handles the model session,
policy, approvals, traces, and cost. Conn.app performs macOS observation and
actions through a verified semantic transaction.

The name comes from the naval handoff of steering authority: spoken, bounded,
and revocable. The Stop control is `belay that`.

Current architecture and measured status:
[docs/STATE-OF-PLAY.md](docs/STATE-OF-PLAY.md). Approved verified-action spec:
[docs/2026-07-09-verified-action-engine-spec.md](docs/2026-07-09-verified-action-engine-spec.md).

## Native app

```bash
cd /Users/samaydhawan/conn/macos
./make-app.sh install
open /Applications/Conn.app
```

The Swift menu-bar app owns the notch island, configurable global
push-to-talk, production Accessibility observations, semantic target
resolution, dispatch, and effect verification. On non-notch displays it uses
the floating panel fallback. No Conn surface takes keyboard focus. Approval is
a deliberate pointer click.

The Python daemon owns the Realtime connection, pure state machine, tool
policy, approval decision, provenance, mutation scheduling, traces, and cost.
It does not silently fall back to Python AX or input execution in production.

The local web console is a read-only engineering surface.
It is disabled unless started with its own local console capability. It cannot
claim the Conn.app control role, answer native RPC, initiate actions, or approve
plans. Approvals live only in the signed Conn app.

Push-to-talk defaults to **Control + Option** using the normal left-side keys.
Either press order works; releasing either key ends recording. Change it from
the Conn menu under **Push-to-Talk Key**. Single-key choices include Right
Command, Left Control, Left Option, Right Control, Right Option, and F13. The
selection persists across relaunches and signed rebuilds.

## What verified means

For every state-changing computer action, Conn:

1. observes the current app, window, target, and baseline
2. resolves the target against current native state
3. prepares a bounded plan with effect predicates and allowed strategies
4. applies Python risk policy and pointer approval to that exact plan
5. revalidates and dispatches through Conn.app
6. observes again and classifies the result from evidence

Native API success is only a dispatch fact. It is not proof of the intended
effect.

Only `verified` produces `ok: true` for a mutation and the user-facing word
`Done.` A dispatch that cannot be confirmed says `Sent, not confirmed.` Every
other unsuccessful outcome says `Did not run.` A possibly-dispatched action is
never retried automatically.

Current semantic operations cover app open/switch, clipboard write, tab focus,
scroll, non-secure text entry, element press, lazy menu action, and allowlisted
key chords. Menu actions, raw key chords, and submit report dispatch-only when
no target-bound effect survives. Secure fields and denied bundles remain
blocked. Visual coordinate control is not implemented.

## Stable signing

macOS privacy grants bind to code identity. `make-app.sh` uses the persistent
`Conn Dev Signing` identity when it is available so Accessibility grants
survive rebuilds.

Check the identity:

```bash
security find-identity -v -p codesigning
```

If this machine does not have it, create it once in Keychain Access:

1. Open Keychain Access, then Certificate Assistant, then Create a Certificate.
2. Name it `Conn Dev Signing`.
3. Choose Self-Signed Root and Code Signing.
4. Override defaults and set validity to 3650 days.
5. Run `./make-app.sh install` and grant Accessibility to Conn.app once.

If Keychain asks whether `codesign` may use the identity, choose **Always
Allow**. Do not treat an ad-hoc build as proof that TCC grants will survive.

Verify the installed app:

```bash
codesign --verify --deep --strict --verbose=2 /Applications/Conn.app
```

## Quickstart without credentials

```bash
cd /Users/samaydhawan/conn
PYTHONPATH=src .venv/bin/python -m conn --demo --simulate-tools
```

This runs the real state machine, policy, trace, and receipt paths against
scripted model events and simulated evidence-backed tool receipts, with no side
effects. `--demo` without `--simulate-tools` uses real executors and may open
apps.

## Live mode

```bash
cd /Users/samaydhawan/conn
export OPENAI_API_KEY=...
PYTHONPATH=src .venv/bin/python -m conn
```

Defaults are model `gpt-realtime-2`, voice `marin`, low reasoning effort, a
$1.00 session hard cap, warning at $0.50, and five-minute idle disconnect.
`--no-audio` runs typed-input mode. `--no-hotkey` skips the global key.

The API key stays daemon-side. It never enters config, the app bridge, the web
console, or traces.

## Permissions

Grant permissions to `/Applications/Conn.app` after the persistent install:

1. **Microphone** for voice.
2. **Accessibility** for global push-to-talk and all production semantic
   observation and action.
3. **Screen Recording** only for the old local screenshot tool. It is not
   needed by the semantic action engine and no visual action lane is enabled.

Production semantic control does not require an Accessibility grant for the
Python interpreter.

Check the environment:

```bash
cd /Users/samaydhawan/conn
PYTHONPATH=src .venv/bin/python -m conn --doctor
```

## Tests, evals, and build

```bash
cd /Users/samaydhawan/conn
PYTHONPATH=src .venv/bin/python -m pytest tests -q
PYTHONPATH=src .venv/bin/python -m conn --eval
PYTHONPATH=src .venv/bin/python -m conn --doctor

cd /Users/samaydhawan/conn/macos
DEVELOPER_DIR=/Applications/Xcode-beta.app/Contents/Developer swift test
./make-app.sh
```

Latest measured results: 461 Python tests passed with 2 existing dependency
warnings, 13 of 13 harness evals passed, 111 Swift tests passed, and the release
Swift build passed. A 1,000-transaction in-memory native-engine stress test
recorded zero wrong targets and zero false verified outcomes. It is not the
real fixture acceptance gate. See
[docs/STATE-OF-PLAY.md](docs/STATE-OF-PLAY.md) for the full measured bars.

## Installation smoke probes

The Mac must be unlocked and the current persistent-signed app installed.

```bash
cd /Users/samaydhawan/conn
PYTHONPATH=src .venv/bin/python -m conn --action-probe fixture
PYTHONPATH=src .venv/bin/python -m conn --action-probe terminal
PYTHONPATH=src .venv/bin/python -m conn --action-probe safari
PYTHONPATH=src .venv/bin/python -m conn --action-probe chrome
PYTHONPATH=src .venv/bin/python -m conn --action-probe notes
PYTHONPATH=src .venv/bin/python -m conn --action-probe obsidian
```

Artifacts go to `data/action-probes/`. The fixture probe checks one accepted
press with no visible effect against its independent truth log. Real-app probes
compare the engine result with WindowServer's top visible window. Missing apps
or unproven signing identities block before dispatch.

These commands test installation and app switching. They do not satisfy the
real fixture matrix or six-app semantic-action acceptance bar.

The remaining human product gate is 30 ordinary commands across three work
sessions. Start with the safe confidence drill in
[docs/MANUAL-TESTING.md](docs/MANUAL-TESTING.md). Use
[docs/LIVE_EVAL_CHECKLIST.md](docs/LIVE_EVAL_CHECKLIST.md) only after semantic
acceptance passes.

## Second Mac

```bash
git clone https://github.com/samay58/conn.git ~/conn
~/conn/bootstrap.sh
```

Full setup and portability notes:
[docs/DEPLOYMENT.md](docs/DEPLOYMENT.md).

## Environment contract

| Variable or path | Purpose |
|---|---|
| `OPENAI_API_KEY` or `~/.config/openai/key` | Live Realtime session secret |
| `config.toml` | Model, voice, budget, allowlists, vault paths, pricing, semantic timeouts |
| `CONN_PROJECT_ROOT`, `CONN_PYTHON` | App-to-daemon path overrides |
| `CONN_CONSOLE_CAPABILITY` | Optional local read-only console capability |
| `data/` | Gitignored traces, receipts, evals, screenshots, and action probes |

## Project layout

```text
src/conn/                         Python daemon and policy plane
src/conn/tools/native_actions.py Python semantic request compiler
macos/Sources/Conn/              Native UI, observation, dispatch, verification
macos/Sources/ConnActionFixture/ Independent native test fixture
console/                         Read-only engineering surface
evals/tasks.json                 Harness eval cases
docs/                            Specs, state, roadmap, and live checklist
data/                            Local evidence artifacts, gitignored
```

The neighboring `phoenix-voice-delegate` project shares safety discipline but
no code.
