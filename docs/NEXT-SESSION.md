# Next session: human acceptance of verified outcomes

Updated 2026-07-13. The reliability program and the verified-outcome follow-up
are mechanically green. Python, Swift, harness, live intent, reconnect, and
data-hygiene gates are recorded in `docs/STATE-OF-PLAY.md`.

## Outcome

Supply the human evidence automation cannot: compare two signed voice receipts
to the visible app result, check barge-in acoustically, complete the safe manual
drill, and begin the 30-command product gate.

## Steps

1. Launch the installed `/Applications/Conn.app`. If an older copy is already
   running, relaunch it by hand so the newly installed build is active. Do not
   stop a daemon or process unless its ownership is clear.

2. Run the two create commands against scratch content:
   - In Safari, say `Open a new tab`. Accept `Done.` only if the receipt is
     `verified` and a tab visibly appears.
   - In Notes, say `New note`. Accept `Done.` only if the receipt is `verified`
     and a blank note visibly appears.
   - Use `Report Last Command` after any mismatch and retain the artifact.

   Targeted native probes already returned `verified` from descendant-role
   witnesses. Their artifacts still say `visible_confirmation_required`, so
   these voice runs must supply the independent eye verdict.

3. Check barge-in acoustically. Ask a question, interrupt Conn mid-answer with
   a new command, and confirm the new transcript has no leading fragment of
   Conn's own speech.

4. Complete `docs/MANUAL-TESTING.md`, including the independent fixture truth
   checks. Record every receipt-to-eye mismatch, even when the action worked.

5. Start the 30-command gate in `docs/LIVE_EVAL_CHECKLIST.md` across three work
   sessions. Daily-driver acceptance still requires zero false completion
   language and at least 90 percent of supported actions faster than hands or
   useful while hands are occupied.

## Evidence already closed

- Safari native create probe: `verified`, dispatched by `ax_menu_action`, bound
  `AXRadioButton` descendants increased from 2 to 3
- Notes native create probe: `verified`, dispatched by `ax_menu_action`, bound
  note-table rows increased
- full live intent eval: 217 of 219, or 99.1 percent, in
  `data/intent-evals/2026-07-13/results-1783960836.json`
- destructive corpus: four of four produced no tool call and the exact
  one-sentence refusal
- full Python suite: 573 passed, 3 deselected, with no test-created change to
  real `data/`

## Hard gates

- zero false verified outcomes
- zero retries after possible dispatch
- no stale action reaches native execution
- no production Python AX or input fallback
- no model-authored effect predicate or raw strategy on ordinary actions
- no per-app command catalog
- no unacknowledged context item treated as live
- no arbitrary process killed or adopted during restart recovery
