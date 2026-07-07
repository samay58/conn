# Deployment: running Conn on another Mac (Mac Mini path)

Written 2026-07-02. Conn travels with the Phoenix vault (`01-active/projects/conn/`),
so a vault sync brings all source, docs, scenarios, and evals. Build artifacts,
traces, receipts, and screenshots are gitignored and stay local to each machine.
What does NOT travel automatically: Python binary wheels, the built app bundle,
TCC grants, and the API key. This doc is the complete path from vault checkout
to a working install.

## What Conn is on a second machine

The daemon plus the menu-bar app, identical to the MacBook install. On the Mini
the likely uses are voice control of the recording desk and vault search on the
always-on machine. Conn is not a background job: it does nothing until a human
holds the talk key, which fits the Mini's prepare-by-default doctrine. Do not
run it as a launchd service; launch the app when wanted.

## Machine-specific values (the honest list)

| Where | Value | Change needed on a new machine |
|---|---|---|
| `config.toml` `phoenix.vault_root` | `/Users/samaydhawan/phoenix` | Match the vault path on that machine |
| `config.toml` `phoenix.qmd_bin` | nvm path to `qmd` | Run `which qmd` there and pin the absolute path |
| App daemon launch | `CONN_PROJECT_ROOT` and `CONN_PYTHON`, or the default Phoenix paths if they exist | Set both env vars before launching Conn when the vault or venv path differs. Source edits are no longer required |
| `~/.config/openai/key` or `OPENAI_API_KEY` | key material | Provision manually; never synced, never in git |

Everything else is relative to the project or resolved at runtime.

## Setup steps

1. Sync the vault (existing Mini flow; vault path step is done per the Mini
   canonical guide).

2. Python deps into that machine's venv (wheels are per-machine):

   ```bash
   cd ~/phoenix && source .venv/bin/activate
   pip install sounddevice pynput websockets starlette uvicorn pydantic pytest
   ```

3. Adjust the machine-specific values from the table above. If the vault or
   venv does not live at the default Phoenix paths, launch the app with both
   daemon path overrides:

   ```bash
   CONN_PROJECT_ROOT="$HOME/phoenix/01-active/projects/conn" \
   CONN_PYTHON="$HOME/phoenix/.venv/bin/python" \
   open /Applications/Conn.app
   ```

4. Verify the daemon before touching the app:

   ```bash
   cd ~/phoenix/01-active/projects/conn
   PYTHONPATH=src ../../../.venv/bin/python -m pytest tests -q     # expect 162 passed
   PYTHONPATH=src ../../../.venv/bin/python -m conn --eval          # expect 6/6
   PYTHONPATH=src ../../../.venv/bin/python -m conn --doctor        # read every line
   ```

5. Build and install the app (`make-app.sh` probes for a working Swift
   toolchain and falls back to Xcode-beta when Command Line Tools cannot
   compile the package manifest):

   ```bash
   cd macos && ./make-app.sh install
   open /Applications/Conn.app
   ```

   The app probes `127.0.0.1:8787` and autolaunches the daemon if none is
   running: live when a key resolves, demo otherwise. The menu bar shows a
   waveform icon; the panel appears on activity only.

6. TCC grants, attached to `/Applications/Conn.app` (stable identity; the
   daemon is a child process so prompts appear as Conn):
   - Microphone: auto-prompts on first live session.
   - Accessibility: menu item "Enable Global Hotkey" prompts; needed for
     Right Option hold-to-talk and for window titles plus selected text in
     `computer_get_context`. Without it, panel and console PTT still work.
   - Screen Recording: only if `computer_screenshot` should see other apps.

7. Smoke it: hold Right Option (or hold Space in the console at
   `http://127.0.0.1:8787`), say "what app am I in right now," watch the
   trace and the cost line. One turn costs about a cent at reasoning effort
   low; the session cap is $1.00 with a hard stop.

## Verification checklist (copy into the Mini session when migrating)

- [ ] 166 tests pass on the Mini's venv
- [ ] `conn --eval` 7/7 with artifacts under `data/evals/`
- [ ] `conn --doctor` reviewed; mic RMS is live, qmd path pinned, vault registered in Obsidian
- [ ] App builds, installs to /Applications, menu bar icon up
- [ ] Demo turn end to end in the panel (no credentials needed)
- [ ] Live turn with one tool call, trace shows tool_result before continuation
- [ ] Budget cap and Stop verified once each

## Known portability debts (documented, deliberate)

- `DaemonLauncher.swift` only resolves two path lanes: both env vars, or the
  default Phoenix path pair if both exist. There is no preferences UI and no
  filesystem scan by design.
- The app is ad-hoc signed. Fine for personal installs; TCC grants survive
  rebuilds because the bundle path and identifier stay stable.
- `sounddevice` bundles PortAudio and `pynput` rides pyobjc; both installed
  clean on Python 3.14.6 on the MacBook. If a future Python bumps and wheels
  break, the fallback is a project-local venv on the last known-good Python,
  documented in the spec's dependency-gate note.
