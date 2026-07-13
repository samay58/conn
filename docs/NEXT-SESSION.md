# Next session: prove semantic operations

Updated 2026-07-12.

## Start here

Current build is signed, installed, and mechanically green. Do not spend the
next session on visual control, island polish, sound, MCP, or more architecture.
The next missing proof is a real fixture-backed semantic matrix.

Installed app uses left-side Control + Option for push-to-talk by default.
Change it from Conn menu, Push-to-Talk Key, if another binding is preferable.

Before running it, unlock the desktop and rerun the fixture probe. If it still
receives no Accessibility tree, open System Settings, Privacy and Security,
Accessibility. Toggle Conn off and on, then quit and reopen Conn. The newest
signed build could not recheck the grant because the console locked.

The matrix must also close one known product gap. Menu commands, raw key
chords, and submit currently return dispatch-only when their effect leaves the
original target. Build a causal native witness for those cases. Broad window
changes and target absence remain insufficient evidence.

Read:

1. `docs/STATE-OF-PLAY.md`
2. `docs/2026-07-09-verified-action-engine-spec.md`, acceptance bars
3. `src/conn/action_probe.py`
4. `macos/Sources/ConnActionFixture/`
5. `macos/Sources/Conn/NativeActionProbeRunner.swift`

## Build the real fixture matrix

Expand `conn --action-probe fixture` from one no-effect press into repeatable
cases for:

- immediate and delayed press effects
- no-effect press
- toggle and tab selection
- scroll-to-visible
- non-secure text entry
- secure-field refusal
- duplicate-label ambiguity
- sibling reorder
- lazy menu action
- window create, close, and title change
- raw key chord with and without a verifiable predicate

Each case must run through the production native transaction engine. Compare
its receipt with `ConnActionFixture` truth after the action. The engine must not
read the truth log.

## Turn the matrix into acceptance evidence

Run 1,000 real fixture transactions. Save aggregate counts and latency under
`data/action-probes/`. Fail the run on any wrong target or false verified
outcome. Keep the existing in-memory 1,000-loop test as a fast unit stress test.

## Run the live app matrix

After fixture acceptance passes, test supported semantic operations in
Terminal, Safari, Notes, and Obsidian. Human-visible verdict must be recorded
separately from engine evidence.

Chrome remains blocked until it is installed and its signing team is proven
locally. Do not guess the team ID.

## Mechanical gate

```bash
cd /Users/samaydhawan/conn
PYTHONPATH=src .venv/bin/python -m pytest tests -q
PYTHONPATH=src .venv/bin/python -m conn --eval
PYTHONPATH=src .venv/bin/python -m conn --doctor

cd /Users/samaydhawan/conn/macos
DEVELOPER_DIR=/Applications/Xcode-beta.app/Contents/Developer swift test
./make-app.sh install
codesign --verify --deep --strict --verbose=2 /Applications/Conn.app

cd /Users/samaydhawan/conn
git diff --check
```

## Stop condition

End the session when fixture acceptance and live matrix results are recorded.
Do not start the 30-command product gate until the semantic bar passes. Do not
start visual work until the product gate passes.
