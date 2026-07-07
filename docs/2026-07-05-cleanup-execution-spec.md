# Conn cleanup execution spec, 2026-07-05

## Goal

Tighten Conn before the next island build phase. The work should reduce live surfaces, make the primary UI honest, and keep machine-specific setup from becoming a quiet fork. Do not broaden capability. Do not redesign the product. Make the existing intent easier to maintain.

## Standard

The Fable bar for this pass is simple: fewer layers, clearer ownership, visible proof. Every change must delete ambiguity or block a real failure mode. If a change only makes the architecture look tidier, skip it.

Safety invariants stay fixed:

- The model proposes and the harness disposes.
- Tool continuations wait for real tool results.
- Budget hold stays hard unless explicitly overridden.
- Approvals stay pointer-only.
- The island and panel never take keyboard focus.

## Current truth

Conn now has a safe daemon spine, a clean shared event vocabulary, a tested reconnect cleanup path, and an island shell that summons, chip-expands, and self-dismisses. The weak spots are all surface ownership and execution ergonomics:

- The fallback panel still subscribes to phase changes even when the island is primary.
- `Conn --preview` still previews the panel, while the notch island is now the product surface.
- `DaemonLauncher.swift` hardcodes this machine's Phoenix path and venv.
- `events.py` is correct now, but it will become a junk drawer unless the boundary is named.

## Packet C1: Make the active surface explicit

### Problem

`AppDelegate` always builds `PanelController`, then optionally builds `IslandController`. On notch displays, the panel is not ordered front by the hotkey, but it still exists, subscribes, and can be shown through the menu. This is not dangerous yet. It is still an extra live surface at the exact moment the app is trying to make the island primary.

### Change

Introduce a small surface boundary:

```swift
protocol ConnSurface: AnyObject {
    func show()
    func hide()
}
```

- `IslandController` conforms through `show()` and `hide()` wrappers around `summon()` and `collapse()`.
- `PanelController` conforms through its existing `show()` and `hide()`.
- `AppDelegate` picks one `primarySurface` at launch.
- Hotkey down calls `primarySurface.show()`.
- `StatusItemController` keeps a `Show Panel` debug action, but the panel is constructed lazily only when that action is used or when no island geometry exists.

### Do not

- Do not remove the fallback panel.
- Do not rewrite `PanelView`.
- Do not add a surface manager object unless the protocol becomes too small to express the call sites. It probably will not.

### Acceptance

- On notch path: `PanelController` is not constructed during launch.
- On forced panel path: behavior is unchanged with `CONN_FORCE_PANEL=1`.
- Menu `Show Panel` still works as a debug fallback.
- No keyboard focus regression: `.nonactivatingPanel`, `canBecomeKey == false`, and `canBecomeMain == false` remain true for the island.

### Tests

- Add `SurfaceSelectionTests` if the launch logic can be factored into a pure helper.
- If not, keep this as Swift build plus manual smoke for now. Do not build a giant testing seam just to test one launch branch.

## Packet C2: Preview the island, not the old panel

### Problem

The preview command is supposed to be the tuning surface. It currently renders panel states. That means motion, typography, and state-language decisions can drift before Samay ever sees the island.

### Change

Rewrite `PreviewWindow.swift` around the island surface:

- Create sample `AppState` values for all nine phases.
- Render them in island frames, not panel cards.
- Include toast and chip variants.
- Keep a light preview background, but the island itself stays black.
- Add a simple state cycler: previous, next, and replay.
- Add `--shoot <dir>` support only if it can be done without a large screenshot framework. Otherwise land the visual preview first and leave screenshot automation for the planned I9 packet.

### Taste rules

- No character yet.
- No ornamental glow.
- No monospace on the island except tabular digits through `.monospacedDigit()`.
- State words are sentence case.
- The first read should be calm: state, one content line, cost, and the chip when needed.

### Acceptance

- `Conn --preview` no longer uses `PanelView` for the main preview states.
- All nine phases are visually distinct.
- Approval uses chip-open geometry.
- Done and failed states visibly settle before collapse in replay.
- The preview is useful before Phase 3 motion work begins.

### Tests

- `PYTHONPATH=src /Users/samaydhawan/phoenix/.venv/bin/python -m pytest tests/test_design_tokens.py -q`
- `DEVELOPER_DIR=/Applications/Xcode-beta.app/Contents/Developer swift build`
- If screenshot mode lands: verify the expected PNG count and filenames in `/tmp/conn-island-preview`.

## Packet C3: Make daemon launch portable without adding settings

### Problem

`DaemonLauncher.swift` hardcodes the Phoenix venv and Conn project root. The deployment doc tells the truth, but a second machine still requires editing source. That is exactly the kind of small fork that becomes invisible tech debt.

### Change

Add a tiny resolver:

1. If `CONN_PROJECT_ROOT` and `CONN_PYTHON` are set, use them.
2. Else try `/Users/samaydhawan/phoenix/01-active/projects/conn` plus `/Users/samaydhawan/phoenix/.venv/bin/python`.
3. Else fail with a clear log line and do not launch a daemon.

Keep the constants as defaults, not as the only path.

### Do not

- Do not add a preferences UI.
- Do not scan the whole filesystem.
- Do not create or mutate a venv.
- Do not store API keys or paths in Phoenix beyond this source file and deployment doc.

### Acceptance

- Current Mac path still works without env vars.
- Env override path is covered by a pure Swift helper test if feasible.
- Failure mode writes a clear daemon log line and leaves the app alive.
- `docs/DEPLOYMENT.md` updates the machine-specific table to say source edits are no longer required for paths.

## Packet C4: Name the event boundary

### Problem

`events.py` is now the right home for shared machine protocol data. It will become the wrong home if future agents add behavior, timers, or policy there.

### Change

Add a short comment block at the top of `events.py`:

- Allowed: frozen dataclasses, enums, IDs, timestamp helpers, protocol unions.
- Not allowed: state transitions, tool policy, UI behavior, retry logic, timers.

Then add one lightweight test that imports every `MachineInput` and `Command` member used by `state.py`. The goal is drift visibility, not a complicated reflection framework.

### Acceptance

- The boundary is obvious to the next agent opening the file.
- `state.py` imports protocol types from `events.py`, but `events.py` imports nothing from `state.py`, `app.py`, tools, or UI code.

## Execution order

C1 first. It removes the extra live surface before more island code lands.

C2 second. It gives the project the correct visual tuning surface.

C3 third. It lowers deployment friction without touching product behavior.

C4 can ride with C1 or C3 if the diff is tiny. Do not let it become its own architecture exercise.

## Phase gate

Before calling the pass complete, run:

```bash
cd /Users/samaydhawan/phoenix/01-active/projects/conn
PYTHONPATH=src /Users/samaydhawan/phoenix/.venv/bin/python -m pytest tests -q
PYTHONPATH=src /Users/samaydhawan/phoenix/.venv/bin/python -m conn --eval
cd macos
DEVELOPER_DIR=/Applications/Xcode-beta.app/Contents/Developer swift test --filter IslandGeometryTests
./make-app.sh
```

Then run:

```bash
git diff --check -- 01-active/projects/conn
python3 ~/.claude/scripts/slopcheck.py docs/2026-07-05-cleanup-execution-spec.md docs/2026-07-05-adversarial-cleanup-review.md
```

If `Conn --preview --shoot` lands, capture the screenshot directory and review it before Phase 3 motion begins.

## Reviewer prompt

Use this after C1 and C2 land:

> Kill this diff. Look for any path where the panel still reacts on the island-primary path, the island or panel can become key, approval can happen by keyboard, preview is optimizing the wrong surface, or the fallback panel was accidentally removed as a debug path. Verify against source, not intent. Return only reproducible findings and the exact file lines.

## Stop condition

Stop after these four packets. The next product work is Phase 2 island content and typography. Do not drift into character, sound, per-app profiles, MCP, or arbitrary UI control.
