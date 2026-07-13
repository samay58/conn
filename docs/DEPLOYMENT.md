# Deployment: running Conn on another Mac

Updated 2026-07-12 for the verified semantic action engine.

Conn uses two local processes:

- the Python daemon for Realtime, policy, approvals, provenance, traces, and
  cost
- Conn.app for the primary UI and all production macOS observation, semantic
  action, and effect verification

The source repo travels. The Python environment, built app, code-signing
identity, macOS privacy grants, API key, and local evidence artifacts do not.

## Prerequisites

- macOS 14 or newer
- full Xcode or Command Line Tools that include `SwiftUIMacros`
- Python supported by the project dependencies
- Accessibility permission for the installed Conn.app
- Microphone permission for voice
- a machine-local `Conn Dev Signing` identity for stable privacy grants
- OpenAI API key for live mode
- qmd and the Phoenix vault only when vault search is wanted

Screen Recording is not required for semantic control. The visual action lane
is not implemented.

## Clone and bootstrap

```bash
git clone https://github.com/samay58/conn.git ~/conn
~/conn/bootstrap.sh
```

`bootstrap.sh` creates the project environment, checks configuration, runs the
Python tests, evals, and doctor, then builds and installs the app. It prints the
machine-local steps it cannot perform. Rerun it after `git pull`.

Use `--no-app` only for daemon development. A daemon-only install cannot run
production semantic computer actions because there is no silent Python AX or
input fallback.

## Manual setup

```bash
cd ~/conn
python3 -m venv .venv
.venv/bin/pip install -e '.[dev]'
```

Set machine-specific values in `config.toml`:

| Value | What to set |
|---|---|
| `phoenix.vault_root` | Absolute vault path on this Mac |
| `phoenix.qmd_bin` | Absolute qmd path if it is not on the app child's PATH |
| `OPENAI_API_KEY` or `~/.config/openai/key` | Provision locally, never commit |
| `CONN_PROJECT_ROOT` and `CONN_PYTHON` | Set only when repo or venv is outside the default `~/conn` layout |

When path overrides are needed:

```bash
CONN_PROJECT_ROOT="$HOME/conn" \
CONN_PYTHON="$HOME/conn/.venv/bin/python" \
open /Applications/Conn.app
```

## Create stable signing on this Mac

Each Mac needs its own persistent development identity unless the private key
is deliberately transferred through a secure process.

In Keychain Access:

1. Open Certificate Assistant, then Create a Certificate.
2. Name it `Conn Dev Signing`.
3. Choose Self-Signed Root and Code Signing.
4. Override defaults and use 3650 days of validity.

Check it:

```bash
security find-identity -v -p codesigning
```

The result must list `Conn Dev Signing` as valid. If Keychain prompts during
the build, choose **Always Allow**. Do not rely on an ad-hoc build for a machine
that will be updated repeatedly. Ad-hoc signatures reset TCC identity.

## Verify the daemon and package

```bash
cd ~/conn
PYTHONPATH=src .venv/bin/python -m pytest tests -q
PYTHONPATH=src .venv/bin/python -m conn --eval
PYTHONPATH=src .venv/bin/python -m conn --doctor

cd ~/conn/macos
DEVELOPER_DIR=/Applications/Xcode-beta.app/Contents/Developer swift test
./make-app.sh install
codesign --verify --deep --strict --verbose=2 /Applications/Conn.app
```

`make-app.sh` probes the active toolchain, Xcode-beta, and Xcode. It refuses to
build when none can expand SwiftUI macros. Install full Xcode or newer Command
Line Tools instead of editing around the macro requirement.

Current reference results on the primary Mac are 461 Python tests passed with
2 existing dependency warnings, 13 of 13 evals passed, and 109 Swift tests
passed. Counts may grow. Every test and eval must be green on the new Mac.

## Grant privacy permissions

Open `/Applications/Conn.app` after the persistent-signed install.

- **Microphone:** allow on the first live voice session.
- **Accessibility:** enable Conn.app in System Settings, Privacy and Security,
  Accessibility. This powers the global hotkey and the production semantic
  observation/action lane.
- **Screen Recording:** optional for the local screenshot tool only. It is not
  used by semantic actions.

Python Accessibility permission is not required for production semantic
control. The daemon asks Conn.app to observe and act.

## Run installation smoke probes on the new Mac

Keep the desktop unlocked. First confirm it is not console-locked:

```bash
ioreg -n Root -d1 | rg IOConsoleLocked
```

Then run:

```bash
cd ~/conn
PYTHONPATH=src .venv/bin/python -m conn --action-probe fixture
PYTHONPATH=src .venv/bin/python -m conn --action-probe terminal
PYTHONPATH=src .venv/bin/python -m conn --action-probe safari
PYTHONPATH=src .venv/bin/python -m conn --action-probe chrome
PYTHONPATH=src .venv/bin/python -m conn --action-probe notes
PYTHONPATH=src .venv/bin/python -m conn --action-probe obsidian
```

The fixture smoke passes when the engine reports `no_effect` and agrees with
the independent fixture truth log. Each installed real-app smoke passes when
the engine reports `verified` and WindowServer sees that app's window in front.
Missing apps and unproven signing identities are blockers, not passes.

These probes do not satisfy the operation-level fixture and live acceptance
matrix in `docs/2026-07-07-roadmap.md`.

Artifacts are local under `data/action-probes/`.

## Smoke a live session

```bash
open /Applications/Conn.app
```

Hold the configured push-to-talk keys and ask a read-only question first. New
installs default to left-side Control + Option. Change it from the Conn menu
under Push-to-Talk Key if needed. Then try one harmless
state-changing action. Confirm that the model continues only after a native
receipt and that the island says:

- `Done.` only for verified
- `Sent, not confirmed.` for dispatch-only
- `Did not run.` for other unsuccessful outcomes

Run the 30-command product checklist in `docs/LIVE_EVAL_CHECKLIST.md` before
calling the new machine accepted for daily use.

## Deployment checklist

- [ ] Full Python suite green
- [ ] 13 of 13 harness evals green
- [ ] Doctor reviewed with no substantive failure
- [ ] 109 Swift tests or the current larger suite green
- [ ] Release app builds with a macro-capable toolchain
- [ ] `Conn Dev Signing` is valid
- [ ] Installed app passes strict signature verification
- [ ] Conn.app has Accessibility and Microphone permissions
- [ ] Fixture smoke probe agrees with independent truth
- [ ] Installed app-switch smokes pass or blockers are named
- [ ] Live read-only turn works
- [ ] Live harmless mutation uses evidence before completion language
- [ ] Budget cap and Stop are verified once

## Known portability constraints

- The launcher uses explicit environment overrides or the default `~/conn`
  layout. There is no preferences UI or filesystem scan.
- Code-signing identity and TCC grants are machine-local.
- Live AX probes require an unlocked desktop session.
- External app probes depend on the app being installed and exposing the
  expected native state.
- The current build may need
  `DEVELOPER_DIR=/Applications/Xcode-beta.app/Contents/Developer` for raw Swift
  commands. `make-app.sh` performs the same toolchain selection itself.
