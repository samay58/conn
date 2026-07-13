# Verified action engine wargame

**Question**: Should Conn replace its current computer executors with the full verified action engine described in the July 9 spec, and what is the smallest safe first delivery?

**Date**: 2026-07-09

Implementation note, 2026-07-12: this document preserves the July 9 debate.
Its `NEXT-SESSION.md` excerpts describe the handoff as it existed that day.
Implementation later removed the production legacy switch, bound app launches
to bundle and signer identity, and kept visual control deferred. Current status
lives in `docs/STATE-OF-PLAY.md`.

**Scope**: Computer observation, action dispatch, verification, retries, native control ownership, visual fallback, and proof gates. Voice capture quality, island motion, sound, MCP, and unrelated tools are outside this judgment.

## Source Packet

Hard cap: six evidence items. Each item contributes no more than three load-bearing excerpts.

### Proposed design

`docs/2026-07-09-verified-action-engine-spec.md`

- Completion requires evidence that intended effect occurred.
- All macOS control moves into Conn.app; Python retains policy and orchestration.
- Visual action remains disabled until semantic gate passes.

### Live handoff

`docs/NEXT-SESSION.md`

- `app_menu` returned success while no visible action occurred.
- Model later repeated a prior Terminal menu action after user asked to open Safari.
- Samay's closing verdict: not usable against real apps.

### Capability contract

`docs/2026-07-06-capability-spec.md`

- Grounded refs and execution-time revalidation are only allowed path to element actions.
- Config cannot unblock code-level safety blocks.
- Continuation withholding and pointer-only approval remain inviolable.

### Current semantic and input lane

`src/conn/tools/ax.py` and `src/conn/tools/ax_input.py`

- Snapshot resolution already checks live app, window, path fingerprints, ambiguity, secure state, and frame drift.
- Mutation results usually report mechanism used, not observed effect.
- App and Python posting lanes implement different subsets of control.

### Current state and native lane

`src/conn/state.py` and `macos/Sources/Conn/AxActionEngine.swift`

- State machine waits for tool result but treats executor `ok` as completion.
- Multiple automatic actions may run while sharing one mutable UI state.
- Native menu engine trusts `AXUIElementPerformAction == .success`.

### Platform contracts

Apple AX headers plus official OpenAI docs

- Apple: action API requests an action; `kAXErrorCannotComplete` can still mean action happened. AX offers supported actions and notifications, but notification support varies.
- Apple: ScreenCaptureKit captures selected windows; Vision returns OCR text, confidence, and bounding boxes.
- OpenAI: Realtime accepts image conversation parts. Official computer-use loop returns an updated screenshot after actions and recommends human control for high-impact actions.

## Issue Ledger

| Issue | Decision pressure |
|---|---|
| Contract clarity | Does `verified` have one defensible meaning? |
| Failure modes | Can retries, stale calls, or unrelated UI changes create false success or duplicate action? |
| Complexity creep | Is unified native engine necessary, or architecture enthusiasm? |
| UX cost | Does verification make voice slower or annoyingly uncertain? |
| Rollback cost | Can migration fail safely without two permanent control systems? |
| Testability | Can macOS behavior be proven beyond mocks? |

## Round 1

### Contract clarity

Builder claim: `verified`, `dispatch_only`, and `not_dispatched` fix current semantic confusion. `ok` becomes narrow: intended effect proved.

Evidence: live false success came from equating AX return with user-visible completion. Spec separates dispatch certainty from effect evidence.

Skeptic counter: arbitrary effects are not universally observable. “Button caused meaningful change” can be read broadly enough to recreate false success.

User Advocate counter: user needs simple truth, not an evidence taxonomy in island UI.

Builder concession: broad layout or pixel change cannot prove semantic success. Generic actions without a bounded predicate return `dispatch_only`.

Current state: contract holds if effect predicates stay bounded and user-facing copy collapses taxonomy to Done, Not confirmed, and Failed.

### Failure modes

Builder claim: dispatch certainty prevents duplicate retries. Turn and response epochs prevent stale calls. Serial mutation prevents state races.

Evidence: Apple explicitly warns that an AX timeout can occur after action effect. Current generic retry language is unsafe.

Skeptic counter: event timing is not causality. Background updates can satisfy a loose predicate inside verification window.

User Advocate counter: false failure is acceptable more often than false success, but repeated “not confirmed” will make product feel broken.

Builder concession: notifications are hints unless they bind to target or approved effect. Unrelated window or pixel change is insufficient.

Current state: sound. Product may initially under-report success. That is preferable during proof phase.

### Complexity creep

Builder claim: native unification is required. Split TCC identity and runloop behavior already caused real failures.

Evidence: Python frontmost state froze; app and Python grants diverged; hotkey/menu moved to app while grounded lane stayed Python.

Skeptic counter: moving full snapshot engine, verifier, capture, OCR, auth, and fixture into Swift is a broad rewrite. Reliability can regress while architecture looks cleaner.

User Advocate counter: user asked for flexible action, not a multi-month platform rewrite.

Builder concession: visual dispatch and OCR do not belong in first delivery. Native semantic control plus verified result contract is first system boundary.

Current state: full end-state architecture is justified. First implementation must be smaller.

### UX cost

Builder claim: most direct semantic verifiers fit under 800ms. User hears certainty instead of fast fiction.

Evidence: tab selected state, text value, clipboard hash, frontmost app, and window changes are cheap targeted reads.

Skeptic counter: one mutation per response plus model continuation adds network round trips to compound commands.

User Advocate counter: voice loses if every three-step request becomes several seconds and repeated approval.

Builder concession: reads can parallel. Mutations serialize. Sequence batching waits until single-action reliability and traces prove latency pain.

Current state: acceptable for reliability round. Product gate must measure faster-than-hands, not only correctness.

### Rollback cost

Builder claim: no persistent data migration. Legacy flag allows rollout comparison.

Evidence: engine operates on ephemeral state and local traces.

Skeptic counter: permanent legacy fallback recreates split implementations and hides native failures.

Builder concession: legacy is development-only and deleted after parity. Production native bridge fails closed.

Current state: low rollback cost if removal date is gate-bound, not calendar-bound.

### Testability

Builder claim: native fixture with independent truth log converts live AX behavior into repeatable integration evidence.

Evidence: idealized test trees missed untitled menu interposer. Fixture can reproduce lazy menus, delays, no-effect success, duplicate labels, and custom canvas.

Skeptic counter: fixture proves controlled AppKit behavior, not Chrome, Safari, Terminal, or Obsidian quirks.

User Advocate counter: six-app live matrix and real work sessions are still required.

Builder concession: fixture is necessary, never sufficient. Live matrix closes semantic engine; Samay closes product gate.

Current state: strongest part of proposal.

## Round 2

### Builder revision

Deliver first slice as verified semantic kernel only:

- Turn and response provenance.
- Typed action outcomes.
- Mutation serialization.
- Authenticated native bridge.
- Native observation and action ownership.
- Effect predicates and action receipts.
- Fixture plus Terminal and Safari menu probes.

Do not implement ScreenCaptureKit, Vision, Realtime image injection, or visual dispatch in first slice.

### Skeptic attack

Native rewrite still risks replacing proven Python snapshot logic before outcome contract proves useful. Reverse order: first add result taxonomy and verification to current lanes, then migrate.

Builder counter: verification spread across two lanes becomes throwaway work and cannot fix TCC or runloop mismatch. Build fixture and result contract first, then native engine behind flag. Do not retrofit full verifier into legacy lane.

Skeptic concession: accepted. One narrow legacy menu probe may establish baseline; production verification belongs native.

### User Advocate attack

Spec exposes internal statuses that can make island noisy. User should not learn dispatch theory.

Builder counter: UI has three messages only:

- Done.
- Sent, not confirmed.
- Did not run.

Detailed evidence stays console and trace.

User Advocate concession: accepted if approval preview remains effect-first and no technical terms reach speech.

### Judge pressure

Question: Does visual fallback belong in same approved spec if it is not first delivery?

Builder answer: yes as architectural boundary. Otherwise semantic engine may hardcode assumptions that block later visual observation.

Skeptic answer: yes for interfaces and safety limits, no for implementation commitment.

User Advocate answer: user wants eventual flexibility. Keeping visual lane explicitly gated prevents quiet scope loss.

Current state: retain visual end-state design. Approval authorizes semantic implementation only unless user later explicitly starts visual round.

## Concessions

- Full end-state is too large for one implementation round.
- Visual observation and action wait behind semantic gate.
- Notifications are opportunistic evidence, never sole universal verifier.
- Broad semantic or pixel change cannot prove generic action success.
- Legacy lane gets baseline probes and rollout flag, not a parallel verification framework.
- Island exposes three plain outcomes, not internal taxonomy.
- Compound mutation batching waits for measured latency pain.

## Unresolved Questions

No architecture blocker remains.

Two empirical questions are assigned to gates:

- Which AX notifications are reliable per operation and app? Owner: native fixture plus six-app probe. Decision rule: targeted reread remains mandatory fallback.
- Can Realtime visual targeting meet 95% static fixture accuracy? Owner: later visual observation round. Decision rule: visual dispatch stays disabled until it passes.

## Judge Summary

Proposal changes right layer. Current bug is not menu traversal alone. System equates dispatch with effect and spreads macOS control across two identities. Transaction outcomes, native ownership, strict retry safety, and real fixture proof address observed failures directly.

Biggest risk is scope. Building semantic kernel, native migration, visual perception, visual action, security hardening, and full app matrix together would create a long rewrite with no early product proof.

What changed through debate:

- Visual lane moved from implementation round to later gated phase.
- Legacy lane receives only baseline probes and rollout switch.
- User-facing outcomes collapse to three phrases.
- Notification evidence requires targeted reread or predicate corroboration.
- Spec approval does not authorize visual implementation.

## Best Current Call

Proceed with smaller shape: contract, fixture, authenticated native semantic control plane, transaction verifier, and live Terminal/Safari proof. Keep visual architecture in spec but do not implement it yet.

Pause island tuning, sound, MCP, and broad capability work. Real-app semantic truth is product-critical path.

## Fastest Uncertainty-Reducing Move

Build current-lane probe against Terminal and Safari before production rewrite. Record menu tree before/after open, supported actions, AX return, notifications, window/tab delta, and human-visible result. Then encode same false-success case in `ConnActionFixture.app` as first native integration test.
