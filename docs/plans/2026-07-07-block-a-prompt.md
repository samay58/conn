You are executing Block A of the Conn roadmap: finishing the notch island. You are working in ~/conn, a standalone git repo (remote github.com/samay58/conn, branch main). Samay is driving alongside you; two of the six steps are his hand gates and you stop there. Work packet by packet, one commit per packet, and do not start a packet until the previous one's gates are green.

## Read first, in this order

1. ~/phoenix/.agents/skills/fable-judgment/SKILL.md and ~/phoenix/.agents/skills/fable-execution/SKILL.md, and operate under them for the whole session. Before shipping any conclusion or claiming any packet done, apply ~/phoenix/.agents/skills/fable-verification/SKILL.md.
2. ~/phoenix/.agents/skills/design-engineering-craft/SKILL.md. This is motion and interface work; that skill sets the taste bar.
3. ~/conn/docs/2026-07-07-roadmap.md, the Block A section. It explains why I8 runs first.
4. ~/conn/docs/plans/2026-07-05-ux-craft-plan.md, packets I7, I8, I9, I12 and STOP 2 and STOP 3. Every packet has a "Cold-start notes (2026-07-07)" paragraph written specifically for this session; those notes override the older packet text where they conflict.
5. ~/conn/docs/2026-07-05-ux-craft-spec.md, sections "The island", "State vocabulary inside the island", "Personality", "Motion", "Typography inside the island". The tables there are the source of truth for every value.
6. ~/conn/docs/STATE-OF-PLAY.md for current state, then the code: macos/Sources/Conn/DesignTokens.swift, IslandView.swift, IslandController.swift, IslandGeometry.swift, AppState.swift, PreviewWindow.swift, and tests/test_design_tokens.py (the magic-number guard you must stay green against).

## Environment contract

- Python: ~/conn/.venv only. Never the phoenix venv.
- Swift: every swift build/test needs DEVELOPER_DIR=/Applications/Xcode-beta.app/Contents/Developer.
- Full gate set, run all of these before calling any packet done:
  - cd ~/conn/macos && DEVELOPER_DIR=/Applications/Xcode-beta.app/Contents/Developer swift test
  - cd ~/conn && PYTHONPATH=src .venv/bin/python -m pytest tests -q
  - cd ~/conn && PYTHONPATH=src .venv/bin/python -m conn --eval
- Install and restart: cd ~/conn/macos && DEVELOPER_DIR=... ./make-app.sh install, then pkill -x Conn; open /Applications/Conn.app. The app adopts a healthy running daemon. If healthz (curl http://127.0.0.1:8787/healthz) shows upstream_connected false or a stale phase, kill the daemon too (pkill -f "[-]m conn") and let the app respawn it.
- Drive the daemon for testing over ws://127.0.0.1:8787/ws: send {"type": "ptt_down", "client_ts_ms": <now>}, hold, then {"type": "ptt_up", ...} or {"type": "stop", ...}. A sub-300ms down/up pair is a zero-spend smoke test.
- Commits: lowercase subject, no em dashes anywhere (subject, body, code, comments, docs), end body with Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>. Run python3 ~/.claude/scripts/slopcheck.py on every commit message file and touched doc before committing. Push main after each packet lands green.

## Safety invariants, non-negotiable in every packet

The island panel never takes keyboard focus: IslandPanel keeps canBecomeKey and canBecomeMain false, style stays [.borderless, .nonactivatingPanel], orderFrontRegardless never becomes makeKey. Approvals are pointer-only: no keyboard shortcut, no focusable control, no default-button styling, no path where Return reaches an approval. No osascript anywhere. Every motion, palette, and geometry literal lives in DesignTokens.swift; tests/test_design_tokens.py enforces this and must stay green. Do not regress key-down-to-listening latency: no new timers outside what the motion policy allows (waveform timeline in active phases, breath timeline in listening only).

## Packet order and what each must deliver

### 1. I8: chip row and approve beat [ADV]

First because live use showed confirm-gated actions dying on the 30s approval timeout: the approve click still lives on the web console. Read the I8 cold-start notes; the essentials: IslandView already renders a non-interactive approvalRow when phase == "awaiting_approval" and state.pendingChip is set; IslandGeometry.expandedFrame(chipOpen:) and IslandController.apply already handle the taller chip frame. Build IslandChipView (new file), mount it from IslandView, replace the preview row. The approval message shape, verified against server/http.py and console/app.js: {"type": "approval", "call_id": <id>, "approved": true|false}; check AppState's Chip model for the field carrying call_id. Motion per the spec table: row opens in chipOpenDuration (160ms easeOut), buttons fade in at chipButtonsFadeDelay (+60ms), approve gives a 120ms confirm settle before the row closes; all values from DesignTokens (add tokens if any are missing, and mirror any new value into the spec's motion table in the same commit). Buttons at least 24pt tall. The collapse retract must keep working while a chip is open.

Adversarial gate: after your implementation passes the mechanical gates, run a genuine adversarial pass against the approve beat before committing: attack focus-stealing (type in another app while the chip is up, zero keystroke loss), Return reachability from every state, mis-click geometry, and approval after the chip's call already timed out server-side. If you can dispatch a subagent reviewer, use one (opus tier, prompted to refute); otherwise do the pass yourself in a separate explicit step and record what you attacked in the commit body. Verify live: drive a real confirm-gated command (say, a menu action) and approve it on the island with a click.

Commit: conn: chip row and approve beat inside the island

### 2. I7: island waveform promotion

Read the I7 cold-start notes; this is a promotion, not a rewrite. IslandView.swift carries a private IslandWaveform whose current motion (traveling wave, constants 5.2 temporal, 0.55 spatial, 1.7/0.22 swell, level*1.4 with floor 0.16) Samay approved live for fluidity; preserve the felt motion exactly. Move it into WaveformView.swift as the canonical island waveform, keep the fallback panel working (PanelView still uses the old rendering; do not restyle the frozen panel), remove "WaveformView.swift" from EXCLUDED_FILES in tests/test_design_tokens.py, make the file guard-clean, and add the tickCount XCTest asserting no timeline ticks in phase "awaiting_approval". The waveform must flatten while a chip is open (I8 consumes this).

Commit: conn: waveform promoted, state-gated, under the guard

### 3. I9: preview cycler and screenshot rig

Read the I9 cold-start notes. First delete the PreviewWindow island fork (IslandPreviewSurface, left by cleanup C2) and render the canonical IslandView with a fake AppState per phase; drive summon/collapse replay by bumping reveal.token and reveal.collapseToken. Then the rig: Conn --preview cycles the nine phases plus toast and chip via on-screen buttons; Conn --preview --shoot <dir> writes <dir>/<phase>.png for all 11 states headlessly, plus a center-crosshair overlay toggle for the optical-alignment check. Run --shoot /tmp/conn-states and verify 11 PNGs exist and look right before committing.

Commit: conn: preview state cycler and screenshot rig

### STOP 2: hand to Samay, do not proceed

Stop. Post the 11 screenshots' path and ask Samay to review the set and drive the cycler. The gate question: does the typography and state vocabulary feel calm and non-AI. Do not start I12 until he says pass. If he orders changes, they are part of Phase 2, not new scope.

### 4. I12: tuning playground with write-back

Read the I12 cold-start notes. DesignTokens gains a runtime story: a DesignTokens.current instance behind the same static names so the inspector can write live values. The inspector (InspectorView.swift, new) lists every motion, personality, and palette token as a slider or color well beside the previewed island, with a Replay button re-running summon and collapse. Raw tokens only; the derived values (squashWidthLead, summonWidthSpring, summonHeightSpring, computed via springOvershooting) recompute live and display read-only. Write Back regenerates DesignTokens.swift from a template (raw literals plus the derived block verbatim) and prints the spec-table diff to stdout for manual paste-back. IslandMotionTests pins the derived math and must stay green after a write-back round-trip; the token guard must stay green on the regenerated file. Acceptance demo: the aliveness slider at 0 renders a fully static island live.

Commit: conn: tuning playground with write-back

### STOP 3: hand to Samay, session ends here

Stop. Samay drives the playground and the live hotkey until summon, breath, exhale, chip, and belay feel right. Two review debts land in this gate and you should surface them to him: the 12-principles adversarial pass on the morph (use the 12-principles-of-animation skill if available) and a taste pass on a fresh screen recording (screencapture -v /tmp/conn-island-motion-2.mov, ctrl-c to stop; record summon, 5s of listening breath, a chip approve, tap-abort retract, done exhale plus collapse). Tuned values get written back to DesignTokens.swift and the spec tables in one commit. The phase closes only when Samay says the motion is award-grade.

## Working rules

- One packet at a time; exclusive file ownership per packet as listed. If a packet needs a file another packet owns, finish that packet first.
- Tests first where the packet specs failing tests; watch them fail, then pass.
- If anything in the specs contradicts the code you find, or a decision exceeds a packet's scope, stop and come back with a decision brief (question, constraints, evidence, options, recommendation). Do not guess on one-way doors.
- After every packet: full gate set green, app rebuilt and installed, one zero-spend smoke test over the websocket, commit, push.
- Update docs/STATE-OF-PLAY.md once at the end of your run (not per packet) with what landed and what remains, and add one line to docs/orchestration-ledger.md naming the session, packets landed, and gate results. Slopcheck both.
- Report honestly: what was done, how it was verified, what was skipped, open questions. End your final report with exactly what Samay should check by hand, in ten seconds per item.
