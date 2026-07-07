# Conn adversarial cleanup review, 2026-07-05

## Call

The recent work is directionally strong. The safety spine is sound, the test surface is much better than it was, and the island work is still early enough that cleanup is cheap. The best move was not another broad refactor. It was three narrow corrections that reduce lying contracts and close known reliability edges without changing product intent.

## Fixed in this pass

| Target | Problem | Change | Why it matters |
|---|---|---|---|
| Event vocabulary | `RejectInput` and `WatchdogTick` lived in `state.py`, while every other machine input and command lived in `events.py`. The app imported state-machine internals to execute a command. | Moved both dataclasses into `events.py` and added them to the `MachineInput` and `Command` unions. Updated tests to import them from the shared vocabulary. | The state machine is pure again: it consumes and returns shared protocol data, not private side-channel types. |
| Reconnect reliability | A failed adapter send entered reconnect without first closing the old adapter. A stale socket or old pump could survive longer than intended. | `_handle_disconnect()` now closes any connected adapter before retrying, and logs `adapter_close_failed` if cleanup itself fails. Added a regression test that proves stale adapters are closed before reconnect attempts. | Reconnect now has a single clean boundary: fail, close old transport, then dial a fresh session. |
| Island settle behavior | Phase 1 left the verified minor finding open: `done` and `failed` summoned the island but never self-dismissed. `awaiting_approval` also did not use the chip-open geometry. | `IslandController` now schedules collapse after the tokenized done and failed delays, cancels stale timers when a new phase arrives, and uses chip-open geometry for approval. Added `failedCollapseDelay` to `DesignTokens.swift`. | The island shell now follows the spec without adding a new surface or special case. Timing remains token-owned. |

## Not patched yet, but worth keeping on the board

| Priority | Target | Specific risk | Recommendation |
|---|---|---|---|
| High | Panel subscription on island path | `PanelController` is still constructed and subscribed even when the island is the primary surface. The ledger calls it harmless, but it is a live extra surface reacting to phase changes. | In the next island-content packet, make the active surface explicit: `primarySurface = island ?? panel`, keep `Show Panel` as a manual debug action, and stop phase subscriptions on the fallback panel unless it is active. |
| High | Preview surface drift | `Conn --preview` still renders the old panel states, while the island is now the primary target on notch displays. | Build the island preview before tuning motion. Otherwise the tuning loop optimizes the wrong surface. |
| Medium | Deployment machine constants | `DaemonLauncher.swift` still hardcodes the Phoenix venv and project root. The deployment doc is honest, but code plus doc still require manual per-machine edits. | Add one small resolver: environment override first, known Phoenix path second, clear failure third. Do not add a full settings system. |
| Medium | `events.py` size creep | Moving protocol types into `events.py` was correct, but the file is now the natural dumping ground for every future machine concept. | Keep only wire/protocol dataclasses there. Behavior, timers, and policies stay in `state.py` or `app.py`. |

## Verification

- `PYTHONPATH=src /Users/samaydhawan/phoenix/.venv/bin/python -m pytest tests -q`: 163 passed, 2 warnings.
- `DEVELOPER_DIR=/Applications/Xcode-beta.app/Contents/Developer swift test --filter IslandGeometryTests`: 4 passed.
- `./make-app.sh`: built `macos/Conn.app` successfully.
- `PYTHONPATH=src /Users/samaydhawan/phoenix/.venv/bin/python -m conn --eval`: 7/7 passed.
- `git diff --check -- 01-active/projects/conn`: clean.
- Diff em dash sweep: clean.

## Intent preserved

No safety boundary changed. The model still proposes and the harness disposes. Continuations still wait on real tool results. Budget hold is untouched. Approvals remain pointer-only. The island remains primary on notch displays and the panel remains the fallback/debug surface.
