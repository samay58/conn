# Conn orchestration ledger

Doctrine: `~/.claude/FABLE-ORCHESTRATION.md`. Success bar: Fable at or below 20 percent of output tokens across the project once execution runs, all gates green, result rated excellent by the user. This spec-and-plan session (2026-07-05) is legitimately Fable-heavy; decomposition and taste are what Fable tokens are for. The 20 percent target is a project-level number, not a per-session one.

## Measurement

Two numbers per session. The orchestrator's own output is a jq pass over the session transcript; workflow subagents run out of process and do NOT land in that transcript, so the jq returns the orchestrator alone:

```bash
jq -rs '[ .[] | select(.type=="assistant" and .message.usage.output_tokens != null)
  | {model: .message.model, out: .message.usage.output_tokens} ]
  | group_by(.model)
  | map({model: .[0].model, output_tokens: (map(.out) | add)}) | .[]' \
  ~/.claude/projects/-Users-samaydhawan-phoenix/<session-id>.jsonl
```

Subagent output comes from each Workflow run's `budget.spent()`, which is cumulative across the session's runs, so one run's spend is the delta from the prior run's figure. Per-tier splits inside a workflow are not exposed, so record the aggregate. Session ID for 2026-07-05: `955b6504-17d8-48f0-afb0-0b855c321e06`.

### Model note (2026-07-05, frozen)

From Phase 1 on, the orchestrator runs on Opus 4.8, not Fable; the Fable budget is exhausted. The doctrine's model-routing and context-discipline strategy holds unchanged: the top model routes work down-ladder and keeps its own output share small, and that economics is the same whether Fable or Opus sits at the top (Opus at the top only strengthens it, since Opus output is cheaper than Fable). The Fable-share pilot numbers in the Sessions table are frozen as the completed proof across the spec, the plan, and Phase 0. The 20 percent bar was a Fable-specific pilot target and is not re-litigated against Opus. New phases still record the orchestrator versus subagent output split for the same context-economics reason, without the Fable-percentage framing.

## Sessions

| Date | Session | Phase | Fable out | Subagent out (aggregate) | Fable share | Notes |
|---|---|---|---|---|---|---|
| 2026-07-05 | 955b6504 | Teardown, spec, plan | 333,448 | 84,366 | 80% (by design) | Teardown workflow wf_7214cbe4: 5 sonnet readers, effort low; all 5 completed, 0 errors; spot-checks confirmed findings. Spec and decomposition are what Fable tokens are for. |
| 2026-07-05 | 955b6504 | Plan Phase 0 execution | 164,105 | 375,718 | 30% | Build workflow wf_64ca02bc: 9 agents (4 sonnet builders, 2 sonnet wave-2 builders, 3 opus reviewers), 305,421 out. Remediation workflow wf_d488b223: sonnet fixer + opus re-reviewer, 70,297 out. Fable overhead was gate work: two workflow scripts, finding verification, six-diff taste pass. |
| 2026-07-05 | 955b6504 | Plan Phase 1 execution | Opus orch (frozen, not computed) | 552,745 | n/a (Opus orch) | Build workflow wf_35e7042c: 5 sonnet builders (I1 97,577; I2 91,528; I3 84,013; I4 92,758; I5 94,670) plus 1 opus adversarial reviewer (92,199), 552,745 out aggregate, 0 errors. Orchestrator now Opus per the freeze note; overhead was grounding, the gate, one inline one-line remediation, and this entry. |
| 2026-07-07 | 0a5d02fd | Personality motion (I10/I11 substance) + doc stock-take | 186,885 (session total) | 0 | 100% (solo, by directive) | Samay-directed solo Fable round on the design-sensitive motion core; no subagents dispatched. Within the doctrine's solo carve-out (serially dependent, taste-critical, one tightly specced packet), but a doctrine deviation worth the flag: implementation ran on Fable rather than down-ladder. Friction note: the earlier refine round (`conn: refine notch island`, separate session) was never token-logged; measurement gap. |

## Session log 2026-07-05

(Session stages below are the spec-and-plan session's own workflow, not the plan's Phase 0 to 5.)

- Teardown: 5 lanes complete, findings spot-verified in source.
- Interlude: live wedge debugged (daemon stuck in thinking since Jul 3; root cause chain verified; recovered). Produced the reliability defect ledger now in the craft spec.
- Scope decisions: island primary, black island exception, nothing at idle, pointer-only approvals reaffirmed, console frozen, onboarding subset, all four craft lanes in, summon morph signature.
- Spec written to docs/2026-07-05-ux-craft-spec.md, slopcheck clean. Approved by Samay same day after a plain-english walkthrough and ten feedback integrations (motion personality, tuning playground, latency to core lane, no monos, ASMR sound bar, idea ledger).
- Plan written to docs/plans/2026-07-05-ux-craft-plan.md. 19 packets across 6 phases; tier map: 2 haiku, 12 sonnet (5 at effort low), 5 opus design cores, 7 adversarial opus reviews, Fable writes zero implementation code.
- Plan Phase 0 executed (same session, post-compaction). Baseline correction: suite was 82 passed, not the recorded 81. Six packets landed as six commits (bd646917a, 48eff5526, fda444718, d9a6dc8a9, 5d1746aa7, 3eceae4aa), zero blocked, all TDD. Adversarial reviews: P0-B minor (GeneratorExit socket null), P0-C blocker plus major (watchdog false positive on healthy tool loops; repeated fire from FAILED), P0-D minor (non-atomic receipt writes). All four findings verified against source before rework. Remediation packet P0-F: three commits (a96a24d73, 7576968fa, 1867dbc0e), opus re-review verdict pass with zero findings. Suite closed at 150 passed, 0 failed.
- Known deferrals from Phase 0: receipt latency block reads first occurrences only (single-turn accurate; per-turn breakdown is packet V1's home); one Swift doc comment references a packet name (mechanical sweep later); evals.py is demo-mode only per its own docstring, so --eval never spends live API money (plan text assumed otherwise; harmless, noted).
- Interlude: app icon shipped (brass speaking trumpet, Samay's pick over three abstract options). Extracted the squircle from ChatGPT's flattened export, rebuilt at macOS Dock proportions, generated AppIcon.icns across ten sizes, wired into the bundle (Info.plist CFBundleIconFile plus a make-app.sh copy step), committed. Inline manual work, not an orchestration packet. App relaunched on the Phase 0 build and confirmed idle-healthy with the new healthz fields live.

## Gate results per phase

Filled during execution sessions. Format: phase, mechanical gate command and result, adversarial reviewer verdict and verification outcome, taste pass verdict.

### Phase 0 (2026-07-05)

- Mechanical: `pytest tests -q` 150 passed, 0 failed. `python -m conn --eval` 7/7 (new latency-v2-kinds case included). Bare `./make-app.sh` builds through the toolchain probe with no env var. `--latency-report` on a real demo trace prints all six spans without crashing (n/a values expected there; demo traces carry no PTT events; numeric paths covered by fixture tests).
- Adversarial: P0-B findings (1 minor), P0-C findings (1 blocker, 1 major), P0-D findings (1 minor); every finding reproduced against source before rework was ordered. Remediation re-review: pass, zero findings, after attacking seq coverage, re-arm starvation, tick jitter, stale-baseline race, purity, and the updated assertions.
- Taste: pass on all six diffs plus three remediation commits. Kill-list sweep clean across every diff and commit message. R4's probe deviation (adding a manifest-compile check) approved as necessary for the acceptance criterion.
- STOP 1 deferred by Samay's call 2026-07-05 (skip-and-proceed to Phase 1): wifi-kill drill, PTT-in-thinking pulse, zombie relaunch, latency report on a live trace. Phase 0 mechanical and adversarial gates are green; the hands-on gate is the one open item and returns before the project closes per the plan.

### Phase 1 (2026-07-05)

- Mechanical: `pytest tests -q` 162 passed (150 baseline + 12 guard cases). `swift test --filter IslandGeometryTests` 4 passed. `./make-app.sh` builds the full app bare (the R4 probe falls back to Xcode-beta silently; raw `swift build`/`swift test` need DEVELOPER_DIR, which the probe supplies). Five packet commits: 43007bfcd (I1 tokens + guard), a2cc95af9 (I2 geometry + XCTest target), a0abdd46e (I3 shell), b5fcc736d (I4 client acks), 8ae07383f (I5 routing); plus inline remediation 5cc45b63c. No em-dashes in any message.
- Adversarial (I3 is the only [ADV] packet this phase): opus reviewer verdict "findings", two findings, both verified against source. #1 MAJOR: `content.layer?.backgroundColor = DesignTokens.islandBg.cgColor` with `islandBg = Color.black`; SwiftUI `Color.cgColor` is Optional and can no-op to an invisible black island on a transparent panel. Confirmed at IslandController.swift:23; remediated inline to `NSColor(DesignTokens.islandBg).cgColor` (guaranteed non-nil, DesignTokens stays the single palette source), commit 5cc45b63c. #2 MINOR: `apply(phase:)` summons on done/failed with no self-dismiss timer; verified, but correctly out of I3's shell scope (spec done-settle and failed-collapse timing belong to packet I6), tracked to Phase 2. Reviewer confirmed the focus invariant held (canBecomeKey/canBecomeMain both false, .nonactivatingPanel, orderFrontRegardless not makeKey, no focusable subviews) and that the I1 guard actually scans IslandController.swift.
- Taste: pass on all five diffs plus the remediation. DesignTokens holds every motion and palette number; IslandController mirrors PanelController's window config; the island is black by design; no mono, tracking, or uppercased in island sources (guard green). Kill-list clean across diffs and messages.
- Orchestrator calls (deviations from the plan, all defensible): I1 tier raised haiku to sonnet effort-low, because the guard needed exclusion-scoping and a TimelineView false-positive carve-out (judgment, not a trivial grep). Sequential dispatch instead of the plan's parallel waves, because a shared git index and a shared Swift `.build` dir make true parallelism unsafe while sub-second builds make the wall-clock cost nil; per-packet context isolation and model routing (the actual token-savings levers) are untouched. I1 guard scope excludes PanelView.swift and WaveformView.swift (frozen panel-era surfaces carrying legacy style); WaveformView rejoins the guard when packet I7 island-reworks it.
- Builder adaptations accepted: `Spring(response:dampingFraction:)` became `Spring(response:dampingRatio:)` (the real macOS SDK label; names and numeric values preserved per the packet's adaptation clause). client_ts_ms is stamped inside DaemonClient.send synchronously with the key event rather than editing the out-of-scope HotkeyMonitor closure signatures. PanelController still subscribes to phase on the island path (harmless; it is never ordered front); full starvation of the unused controller is deferred.
- Carry-forward: (a) the spec typography tension ("retired everywhere" vs the frozen fallback panel) is still open for Samay's call; the panel retype is a small follow-on packet. (b) done/failed auto-dismiss timing lands in Phase 2 packet I6. (c) raw `swift build` needs DEVELOPER_DIR or `make-app.sh` (the probe is script-level only); the Phase 1 Global Constraints over-promised bare `swift build`, correct for Phase 2 packet prompts. (d) a repo-wide `*token*` gitignore rule catches token-named files; tracked files are safe, new token-named files need `git add -f`.
- STOP 1 (Phase 0 hands-on) remains deferred by Samay's skip; it returns before the project closes.

### Phase G capability round (2026-07-06)

- Packet commits: G1 `39895b1de` through `8edf2de93` for the snapshot lane, G3 `0c731ad01` plus cross-packet safety hardening in `2d1ba0e13`, G2 `05034aad8` through `085f8c17c`, and G4 `d9a449167`. The vault sync daemon added sync commits between packet commits; no checkout, stash, or branch switch was used.
- Mechanical: `PYTHONPATH=src /Users/samaydhawan/phoenix/.venv/bin/python -m pytest tests -q` closed at 247 passed, 2 warnings. `PYTHONPATH=src /Users/samaydhawan/phoenix/.venv/bin/python -m conn --eval` closed at 12/12 passed. `PYTHONPATH=src /Users/samaydhawan/phoenix/.venv/bin/python -m pytest tests/test_grounded_gates.py::test_export_payload_stays_under_20kb tests/test_executors.py -q` closed at 19 passed. A direct fake-executor probe confirmed every grounded tool name is present in `FAKE_EXECUTORS`, and a non-allowlisted hotkey stays blocked with `hotkey_not_allowlisted`.
- Adversarial: G1 passed after remediation for secure-label redaction, same-label sibling and ancestor reorder, frame drift, absent Chromium AX restoration, and secure-state changes. G3 passed after remediation for per-chunk focus checks, coordinate fallback fail-closed behavior, app-qualified focus and menu checks, and executor-local frontmost checks. G2 passed after remediation for blocked-call execution, stale ref re-gating, frontmost mismatch, invalid menu paths, item type validation, gate exception handling, and executor-local app checks. G4 had no ADV tag; the prompt/eval packet was verified mechanically.
- Taste: Gate G brief written at `docs/2026-07-06-gate-g-fable-brief.md` with the prompt diff, refusal texts, and snapshot render sample. Fable taste review remains pending, so STOP-G is the current stop.
- Token accounting by tier: unavailable from the Codex `multi_agent_v1` surface. The API returned agent final reports and commit evidence, but no per-agent usage object. Treat this as a measurement gap, not an efficiency proof. Friction note: the earlier truncated G4 spawn and the stopped outside agent both converged on the same G4 commit; the duplicate agent was closed and no duplicate files remained.
- Stop state: Gate G mechanical and adversarial checks are green. Do not start X1, M packets, P1, or the queued island merge lane until Samay completes STOP-G and the Fable taste review passes.

### Island refine and personality motion rounds (2026-07-07)

Two Samay-directed solo sessions outside the packet dispatch flow, landing between Phase 2's I6 and the I7-I9 remainder. They deliver the substance of Phase 3 packets I10 and I11; execution records live in the plan under those packets.

- Refine round (commit `conn: refine notch island`): island repaired to notch-flush geometry, synthetic menu-bar-inset adoption, breathe-open summon. Verified live by Samay. Session not token-logged (measurement gap noted in the Sessions table).
- Personality round (session 0a5d02fd, commit 7361b6c): mechanical gates all green: `swift test` 17/17 (also run green with aliveness temporarily 0, then restored), token guard 12/12, pytest 247/247, evals 12/12, app rebuilt and installed to /Applications. Live verification: websocket-driven session recorded at /tmp/conn-island-motion.mov, frame-level analysis confirmed the summon overshoot frames, the 3.2s breath period at the island's bottom edge, animated tap-abort and belay retracts, and the exhale dip at done entry; no dismissal path vanishes in one frame. Spec updated in the same commit (whimsy ceiling renegotiated per Samay's directive); the motion-table summon and collapse rows were reconciled to the shipped per-axis springs in the stock-take commit that followed.
- Deviations, both by Samay's direct instruction: solo Fable execution instead of down-ladder dispatch, and no adversarial review on the diff. The 12-principles adversarial pass and the Fable taste pass on a recording from I10's done-definition fold into STOP 3. Open taste gate: Samay's hand test, pending.

### Phase 2 remainder and consolidation (2026-07-07)

Three packets landed in a prior solo session, then reviewed and consolidated in a follow-up session before push. Packet commits: `084f25b` (I8, chip row and approve beat inside the island), `3b94e2c` (I7, waveform promoted, state-gated, under the guard), `601a857` (I9, preview state cycler and screenshot rig).

- Landed by I8: `IslandChipView` replaces the non-interactive preview row. Pointer-only by construction (the panel never becomes key or main, buttons are plain styles with no keyboard shortcut, focus, or default-button treatment), approve sends after a 120ms confirm settle via an unstructured Task that survives view unmount, deny sends at once, first click wins. `IslandController` animates the frame on the chip-open curve to match the SwiftUI row layout, and `IslandReveal.collapsedScale` now tracks the chip-open frame so a collapse from an open chip still maps back onto the notch. New Swift test `IslandPanelFocusTests` pins the focus invariant. The console approval buttons hardened in the same pass: `tabIndex = -1` and a `detail === 0` guard reject keyboard-synthesized clicks.
- Landed by I7: the island waveform promoted from a private `IslandView` struct into `WaveformView.swift` as the canonical `IslandWaveform`, removed from `EXCLUDED_FILES` in the token guard, with a `tickCount` hook and `IslandWaveformTests` asserting zero timeline ticks while a chip is open and positive ticks while listening. The traveling-wave shape constants stay inline by design (approved live for fluidity, not motion tokens).
- Landed by I9: `PreviewWindow` retargeted at the canonical `IslandView` (the C2-era fork deleted), an eleven-state cycler with a crosshair toggle, and `Conn --preview --shoot <dir>` writing one PNG per state headlessly from an offscreen window.
- Consolidation session: reviewed all three commits end to end (correctness, spec fidelity, safety invariants) and found no code defects to fix. Verified the two safety invariants hold (island never key or main; approvals pointer-only on both surfaces). Fixed `CLAUDE.md` prose before its first commit (ten em-dashes to colons or periods, plus three stale facts: 162 to 256 tests, 6 to 12 evals, and the "until I8 lands" console note). Added `.specstory/` to `.gitignore`. Updated STATE-OF-PLAY and this ledger.
- Mechanical gates (consolidation session): `PYTHONPATH=src .venv/bin/python -m pytest tests -q` 256 passed. `DEVELOPER_DIR=... swift test` 19 passed. `python -m conn --eval` 12/12. `Conn --preview --shoot /tmp/conn-states` wrote 11/11 PNGs; the chip and listening states were visually spot-checked. Kill-list clean across `CLAUDE.md`, both doc edits, and the consolidation commit message; no em-dashes anywhere.
- Deviations: I7 and I8 were plan-tagged opus and I9 sonnet; the packets were executed and reviewed on Opus 4.8 in solo sessions per Samay's standing directive for this round. No adversarial reviewer was dispatched for I8's [ADV] tag; the focus and pointer-only attack surface was checked inline against source and pinned by the new tests. Two findings recorded but not fixed by prior decision, both awaiting Samay's call: the localhost approval websocket is unauthenticated, and assistive-tech AXPress can activate the island buttons.

### STOP 2 refinements and I12 (2026-07-07)

One solo session landing the four STOP 2 refinements as `91b1460`, then packet I12 as its own commit, per the contract Samay left in `docs/NEXT-SESSION.md`.

- Refinements: lilac #C3B1E1 as the signature accent with the thinking ellipsis beat (a third gated timeline, pinned paused outside thinking by the extended waveform-tick test), the acting tool capsule with humanized labels (the daemon ledger already carried the tool name, so only the Swift Chip model grew a field), chip previews budgeted daemon-side (32-character word-boundary clamp in the harness covering both the registry lambdas and the risk.py resolution overrides, plus rewritten clipboard and type previews), and the gold #E0C060 budget-hold identity with a two-decimal cap figure and a real Override once outline button, pointer-only like Approve. Contrast checks ran: lilac 10.7:1 and gold 11.9:1 on black. One rendering finding: a stroked SwiftUI capsule draws seam ticks at its ends when the radius equals half the height, so the outline is a rounded rectangle at a 10pt token; recorded in the tokens file comment.
- I12: DesignTokenStore behind the unchanged static names, InspectorView beside the cycler, Write Back regenerating DesignTokens.swift from the template in the new guard-excluded TokenWriteback.swift, spec-table diff to stdout. Round-trip pinned by test: render of a default store equals the file on disk byte for byte.
- Mechanical gates, green before and after each commit: pytest 260 (4 new preview-budget tests), swift test 26 (1 waveform-tick extension, 6 write-back tests, motion suite untouched), evals 12/12, token guard green, fresh 11-PNG screenshot set eyeballed per state. App rebuilt and installed to /Applications.
- Deviations: both parts executed solo on Fable per the session contract Samay wrote (no re-review round for the refinements; I12 was plan-tagged sonnet). No adversarial reviewer dispatched; the refinements were verified against the contract's per-change acceptance and the screenshot set, I12 against its round-trip and live-statics tests. At that session close, unauthenticated localhost approval and blind trust in AXPress remained open. The July 10 verified-engine round closed both with bridge authentication, a capability-authenticated approval-only console, and evidence-classified native transactions.

### Session log 2026-07-08 (P0 reliability round)

The frontmost spine round from `docs/NEXT-SESSION.md`, run solo per the contract (serially dependent bug chain, live-machine probes required). One session worked bugs 1-2 to commit, landed bugs 3-5 in the working tree, and was interrupted by a harness outage before the gate set could run; a resume session verified the staged work from scratch and landed the rest.

- Discriminating test ran FIRST per the contract: three probes proved NSWorkspace (frontmostApplication AND isActive filtering) is KVO-frozen at spawn in a runloop-less daemon; a main-thread runloop pump fixes it, a worker-thread pump does not; CGWindowList is fresh from any thread. Probe 2 also caught WindowManager (accessory policy) transiently owning the front window: both contract hypotheses (staleness AND imposter class) were real, and the fix needed both layers.
- Bug 1: `tools/frontmost.py`, per-call window-server source plus activation-policy filter, both call sites (commit `38503b8`, 11 new tests).
- Bug 2: S2 pulled forward. client_hello/ax_read/ax_read_result over the existing websocket, AxBridge thread-safe round trip, AxContextReader app-side, doctor names the exact python binary (commit `dd6f732`, 12 python + 2 swift tests).
- Bug 3: gate fixed via the shared source; switch-then-menu regression eval added (eval 13); live gate probe flip confirmed on resume: blocked before the hand switch, confirm after, from a worker thread against the real MacAxBackend (commit `595c849`). Probe caveat, observation only: during a cold app launch the window server can show the previous app's window in front for a beat after activation, so the gate follows the visible window, not the activation event; a retry lands once the window draws.
- Bug 4: meta/super/win alias to cmd, combo grammar in the tool description, refusal names the allowlist and reroutes to app_menu, cmd+t/w/n at confirm tier in config.toml (commit `17da556`).
- Bug 5: Broadcaster writer tasks cancelled on detach (3 tests, commit `229e526`); PaMacCore -50 ledgered as cosmetic.
- Resume verification: two stale test expectations the interrupted session had not updated (the exact `hotkey_not_allowlisted` string in test_grounded_gates, the 7-case tasks.json count in test_latency_report) were fixed and committed with their owning bugs; everything else landed as staged.
- Gates at close: pytest 294 passed, evals 13/13, swift 28 passed, token guard green, fresh Conn.app installed to /Applications.
- Observation, no packet: the 2026-07-07 drive trace also shows benign reconnect churn (8x "Cancellation failed: no active response", 3x 60-minute session cap).
- Live acceptance (the trace-level checks in the contract) rides on Samay's quick-test-menu drive; `NEXT-SESSION.md` stays until it is green. STOP 3 stays parked behind it.

### Session log 2026-07-08 (identity and audio round)

The round from `docs/2026-07-08-identity-audio-spec.md`, run solo on Fable per the session contract (live-machine TCC probes required; serially dependent lane order). Six packets in five commits, T1 T2 T4 A1-A3 T3, plus this close-out.

- Live verification ran before building, per the contract: the running daemon's process image is `Python.framework/.../Resources/Python.app/Contents/MacOS/Python` (pid probe), confirming the T1 root cause with the machine's own state; doctor at session start still named the venv realpath.
- T1 (`a53389d`): identity module resolving the live image via proc_pidpath (ctypes libproc) and mapping it to the enclosing .app bundle; doctor accessibility and input_posting name the grant target; 9 tests; live doctor names Python.app on this machine.
- T2 (`9d1ee2a`): ax_grants trace and publish at session start and app attach (python_ax, app_ax, python grant target); console banner, island amber warning line with summon-then-collapse from idle; refusals name the lane and the artifact; 4 python + 5 swift tests.
- T4 (`2f43199`): the in-session scope amendment, executed as the severable half. computer_hotkey and app_menu (menu tree read plus press) through the app's grant via ax_action / ax_action_result and AppLaneInputBackend; python fallback when no app attached; wire failures refuse so a maybe-posted chord never posts twice. The grounded lane deliberately stayed python-side: its safety semantics run AX reads at execution time, so a full move is a remote AX backend, deferred as T4b in the idea ledger with a design sketch. Judged too large to land properly alongside the round; flagged for Samay's veto in the handoff. 12 python + 7 swift tests.
- A1-A3 (`a146876`): 400ms pre-roll ring flushed ahead of live frames at gate open, cleared on close; input_device substring resolver with doctor listing inputs and marking the one in use; low_signal trace event and hint on both surfaces for quiet windows (5-frame floor so tap discards stay silent); transcription language pin riding the second session.update. 16 tests.
- T3 (`58fff56`): make-app.sh signs with "Conn Dev Signing" when the keychain has it, ad hoc fallback with a loud warning (verified on a real build); README one-time recipe with ten-year validity. Grant survival across reinstall needs the certificate, which only Samay can create (GUI keychain step): step 0 on the acceptance list.
- Historical gates at that session close: pytest 334 passed, evals 13/13, swift 40 passed, token guard green, slopcheck clean on every commit message and doc edit, fresh Conn.app built and installed to /Applications with an ad-hoc signature. The certificate now exists and the current installed app has a valid persistent signature; current counts are in the July 12 entry below.
- Deviations: all packets executed solo on Fable (the round is TCC-identity-bound to this machine; no subagent can probe grants). The T4 scope split is the session's one judgment call against the discussed packet, recorded above and in the spec amendment.

### Session log 2026-07-10 (verified semantic action engine)

The approved semantic-first slice from
`docs/2026-07-09-verified-action-engine-spec.md` was implemented across packets
VA0 through VA8. The wargame's narrowing held: native semantic observation,
transaction outcomes, bridge authentication, strict retry safety, a fixture,
and live-probe tooling landed; visual control, sound, motion, MCP, broad app
profiles, and multi-action macros did not.

- VA0 added `ConnActionFixture.app`, deterministic semantic surfaces, and an
  independent truth log. The engine cannot read that log. The harness compares
  receipts to fixture truth and pins the original failure class where AX
  accepts a press but the intended state does not change.
- VA1 added typed outcomes, dispatch certainty, bounded evidence, retry safety,
  and receipt rendering. Mutation success is now equivalent to verified. The
  island and console cannot render dispatch-only, no-effect, ambiguous, or
  failed outcomes as green completion.
- VA2 bound calls to turn, response, observation, and execution identity;
  rejected stale response work; serialized mutations; preserved read-only
  concurrency; and stopped a response's mutation chain after any non-verified
  result.
- VA3 replaced unauthenticated app-role registration with a 256-bit launch
  secret, challenge-response authentication, one app control role, request
  identity, monotonic sequence checks, local console capability, and
  fail-closed disconnect behavior. The console cannot initiate actions or
  answer native RPC; its only control is nonce-bound pointer approval for the
  exact pending plan.
- VA4 and VA5 moved production snapshot ownership, target resolution, plan
  preparation, revalidation, dispatch, evidence predicates, and classification
  into Conn.app. Python remains policy and orchestration. Production
  composition cannot re-enable the legacy Python AX/input engine.
- VA6 migrated app open/switch, clipboard, tab focus, scroll, non-secure text,
  element press, lazy menu action, and allowlisted key chords to native
  transaction receipts. There is no silent production lane fallback.
- VA7 tightened model completion language, snapshot hygiene, traces, and Stop
  behavior. Raw native success cannot produce verified or `Done.`
- VA8 added `conn --action-probe` for the fixture, Terminal, Safari, Chrome,
  Notes, and Obsidian, plus the deterministic 1,000-transaction acceptance
  run.

Mechanical close-out evidence:

- `PYTHONPATH=src .venv/bin/python -m pytest tests -q`: 434 passed, 2 existing
  dependency deprecation warnings.
- `PYTHONPATH=src .venv/bin/python -m conn --eval`: 13 of 13 passed.
- `PYTHONPATH=src .venv/bin/python -m conn --doctor`: every substantive check
  passed; only the optional global-hotkey monitor warned in the noninteractive
  environment.
- Swift tests: 84 passed.
- Release Swift build: passed using the full Xcode-beta toolchain.
- Fixture acceptance: 1,000 transactions, 980 verified supported actions, 10
  intentional no-effect results, 10 ambiguity refusals, zero wrong targets,
  zero false verified outcomes, 100 percent ambiguity refusal, and no automatic
  retry after possible dispatch.
- Fixture latency assertions: p95 observation at or below 150ms and p95
  dispatch plus verification at or below 800ms.

Security review covered bridge role impersonation, console authorization,
Stop races, uncertain dispatch, late result binding, stale response adoption,
non-verified mutation chains, user-facing completion language, and missing
upstream response identity. Validated findings were fixed and pinned by tests.

Environment close-out:

- `Conn Dev Signing` is a valid identity.
- The installed `/Applications/Conn.app` has a valid persistent signature.
- The final fresh signed install and all external AX live probes were blocked
  because `IOConsoleLocked=true`. Locked-console artifacts record this as an
  environment block before dispatch.
- The fixture/native simulated acceptance is complete. External fixture and
  five-app live artifacts are pending an unlocked desktop.
- The product gate remains pending: 30 ordinary commands across at least three
  sessions, zero false completion language, and at least 90 percent of
  supported commands faster than hands or useful while hands are occupied.

This session did not close the product. Exact sign-in, signing, install, probe,
and human acceptance commands are in `docs/NEXT-SESSION.md`.

### Session log 2026-07-12 (consolidation and hardening)

The final diff review found gaps that the July 10 close-out missed. Work stopped
before commit and push. Each finding received a regression test and fix:

- pre-satisfied effects can no longer dispatch or verify
- notification hints cannot satisfy `all` or `any` verification
- generic AX failures become `possibly_dispatched`, preventing fallback
- scroll-to-visible verifies visibility instead of an unrelated value delta
- Conn.app rejects legacy native mutation operations
- `ToolSpec` owns mutation and semantic-operation metadata
- app launch requires an exact bundle ID and code-signing identity
- fixture readiness and nanosecond artifact IDs make live evidence causal and
  collision-free
- global predicates cannot borrow a decorative target ref
- verification stays bound to the original process and window
- target omission cannot prove disappearance or attribute change
- verified `any` receipts carry only supporting evidence
- text submit and every key post recheck the actual frontmost app
- bridge and console capabilities are removed before child processes run
- the fixed-origin browser console is read-only; it cannot approve plans
- secure state is rechecked after target resolution and before dispatch
- semantic resolution confirms parent path, ancestor context, and frame drift
- native receipt Boolean fields reject non-Boolean wire values
- model context excludes free-form app and window labels
- Realtime tool calls stay buffered until the response completes successfully
- per-client broadcast queues are bounded and disconnect stalled readers
- completed Realtime output is authoritative; omitted or conflicting buffered
  calls cannot execute
- path fallback preserves semantic identity, and native receipts must match the
  approved plan fingerprint
- schema bounds are enforced before policy, and qmd receives a non-secret
  environment allowlist
- installed-app push-to-talk now defaults to Control + Option, exposes seven
  persisted menu choices, and releases cleanly when either key or the binding
  changes
- the native event boundary no longer reads typing-only repeat state from
  modifier events; a real AppKit event regression test covers the failure
- bridge health challenges now use the URL-safe alphabet accepted by the
  daemon, so a fresh app and daemon can authenticate reliably

The final diff-scoped security scan reviewed 55 production and protocol files.
Fourteen valid intermediate candidates were fixed and retested. One
developer-fixture-only path was suppressed. Zero reportable findings remained.

Measured gates after hardening:

- Python: 461 passed, 2 existing dependency warnings
- evals: 13 of 13 passed
- Swift: 111 passed
- release build: passed
- doctor: every substantive check passed; optional global-hotkey probe warned
- persistent-signed Conn.app installed and verified on 2026-07-12

Live smoke evidence:

- fixture no-effect press: 3 of 3 agreed with independent truth
- first app transition to Terminal, Safari, Notes, and Obsidian: engine and
  WindowServer agreed
- repeated same-app requests refused as already satisfied before dispatch
- Chrome remained blocked because it is absent and its signer is unproven

Documentation now separates the in-memory 1,000-transaction stress test from
the still-open real fixture acceptance gate. App-switch smoke probes no longer
stand in for the required six-app semantic-operation matrix. Product acceptance
remains pending.

## Current report

`docs/STATE-OF-PLAY.md` is the canonical current status. This ledger preserves
historical packet records, including claims later corrected by measured live
evidence.
# 2026-07-12 voice-first reliability diagnosis

Live dogfooding overturned the prior execution order. The verified transaction
kernel remains mechanically sound, but the product control loop is not ready
for daily use. The latest session recorded 40 upstream errors, two verified
mutations out of seven proposals, and repeated failure on Notes navigation and
Safari New Tab.

Approved direction: repair evidence, Realtime item lifecycle, daemon
ownership, and voice-turn isolation first. Then move ordinary action mechanics
from the model into a small capability-compiled semantic intent layer. Preserve
all verified-action invariants. Do not add visual control, broad app command
catalogs, hidden macros, or repeated security scans.

Source of truth:
`docs/2026-07-12-voice-first-reliability-spec.md`.

# 2026-07-13 reliability spec adversarial review

Pre-implementation review re-verified the July 12 spec against the session
artifacts and current source. No material architecture flaw. All causal
diagnoses confirmed in code: 36-character `ctx_` item IDs with no server
acknowledgement, rejected creates remembered and later deleted, cancellation
sent without an active response binding, menu and key-chord schemas inviting
`desired_effect` that `desiredEffectTargetsAction` rejects for those
operations, the mutation chain closing on every non-verified outcome, the
duration-only tap discard, the playback-contaminated pre-roll path, and the
fixed 2s bridge timeout against native budgets up to 4s.

Corrections folded into the spec, anchored to the first upstream session's
window because the orphaned daemon kept growing the trace file overnight: 16
PTT cycles, 41 upstream errors (17 create, of which 2 from the snapshot
tool-result path, 16 delete, 7 unbound cancels, 1 duration close), and five
sub-300ms discarded holds. Scope rulings: R4 counterfactual scoring is trace recording only, and
the support envelope records evidence without runtime suppression until
failures justify it. Mechanical baseline before first change: 461 Python
tests, 13 of 13 harness evals, 111 Swift tests, release build and persistent
signing green.

# 2026-07-13 voice-first reliability implementation

Implemented packets R0 through R8 of the reliability spec in one session
under TDD, after the adversarial review found no material architecture flaw.

Landed, each with pinned tests: exact assistant transcripts, runtime and app
build identity, gesture-bound PTT provenance and turn acks, receipts that
separate user turns, model responses, proposals, blocked proposals, and
action outcomes, per-turn latency distributions, linked full tool-result
artifacts, outcome-derived probe filenames, Report Last Command with a
pipeline-stage classifier, the July 12 replay cassette, an acknowledged
Realtime item ledger with legal IDs and response-bound cancellation, a strict
protocol fake (1,000 turns plus the cassette replay, zero errors), a daemon
ownership lease with graceful shutdown and bounded orphan exit (50 quit, 20
crash, 3 orphan cycles against real processes), playback-tail pre-roll
suppression with a synthetic watermark proof, signal-aware short-hold
acceptance, idempotent duplicate edges, stale-line clearing, the semantic
intent boundary (desired_effect removed everywhere, raw menu and hotkey tools
hidden as diagnostics, `computer_create` and `computer_select_relative`
lowering onto live affordances in the engine), descriptive capability
reports, ranked-candidate and support-envelope recording, collection and
window-count witnesses for create, adaptive verification backoff with
notification hints, bridge deadlines aligned to native budgets, bounded
recovery (one replan after proven not_dispatched, two compile failures per
turn, no repeated plan shapes) with safe user messages, a harness-only label
on the old evals, and an opt-in live intent eval over a 215-item reviewed
corpus (24 of 25 on the first live sample).

Final counts: 551 Python tests, 138 Swift tests, 13 of 13 harness evals,
three 100-turn soak sessions clean. Open: live signed-build voice runs, the
acoustic barge-in check, the real fixture matrix, the full-corpus intent bar,
menu mark-state witnesses, ref-targeted partial rereads, and the human
product gate.

# 2026-07-13 verified outcomes and release audit

The first live session on the reliability build exposed two false negatives
and one native target bug. Safari opened a tab while its receipt said
`no_effect`; Notes created a note with no witness; empty element titles blocked
the grounded click fallback.

The follow-up bound Safari verification to tab descendants and Notes
verification to the unique note table. Target preparation now skips empty
fallback strings. Live native receipts returned `verified` for Safari and
Notes, but their independent eye verdicts remain open. Safari caps the first
tab at `dispatch_only` when no tab collection exists in the baseline.

Destructive requests now stop at the model boundary. The full live intent
corpus passed 217 of 219 cases. Reconnect recovery runs for five minutes with
capped exponential spacing, shares one task across disconnect and push-to-talk
paths, and gives a usable relaunch instruction if it exhausts. Tests use a
temporary data directory. The debris sweep removed only artifacts tied to
traces that never reached `session_start`.

Release checks passed: 573 Python tests, 144 Swift tests, 14 of 14 harness
evals, 50 graceful quit cycles, 20 crash relaunches, 3 orphan exits, release
build, persistent signature, and unchanged real-data manifest across the full
Python suite. Human acceptance remains the Safari and Notes eye check, acoustic
barge-in, the manual drill, and the 30-command product gate.
