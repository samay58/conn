# Gate G Fable brief

Purpose: taste review for the grounded-action lane before STOP-G

## Review ask

Decide whether the prompt, refusal language, and snapshot rendering feel calm,
literal, and non-AI enough for the hands-on drill

## Prompt diff

The Tools section changed from disabled-tool language to the grounded-action
loop:

```diff
- computer_click, computer_type_text, computer_hotkey, and computer_ax_tree are disabled and will be refused
+ For grounded UI work: snapshot first, then act only on refs from that snapshot
+ If a grounded action returns stale_ref or snapshot_expired, take one new snapshot and retry once
+ If a grounded action returns element_not_visible, scroll it into view and retry once
+ Use app_focus_tab before hotkeys for tab switches when the title is known
+ Use app_menu before hotkeys for app commands like close, new tab, or preferences
+ Keep snapshots on demand only, and screenshots on demand only, for the current step
+ Never guess refs, paths, or hidden UI state
```

Reviewer checks:

- The section stays under 30 lines
- It does not teach the model to browse the UI constantly
- The retry rule is clear, but not chatty
- The command-preference rules are specific enough to matter

## Refusal and block texts

- `stale_ref: take a new snapshot`
- `snapshot_expired: take a new snapshot`
- `secure_field: Conn never types into password fields`
- `element_not_visible: scroll it into view or re-snapshot`
- `hotkey_not_allowlisted`
- `app_not_frontmost: <app>`
- `submit_uncertain_field`

Taste question: keep these literal for traceability, or soften only the spoken
paraphrase while preserving exact tool errors

## Snapshot render sample

```text
snapshot 72591c26 app=com.apple.mail window="Mail Draft" elements=4
e1 AXWindow "Mail Draft"
  e2 AXTextField "To" value="samay@example.com" (focused)
  e3 AXButton "Send"
  e4 AXSecureTextField "Password" value="[redacted]"
```

Reviewer checks:

- Refs are readable enough for model grounding
- Secure text is visibly redacted
- The tree is sparse rather than noisy
- The sample feels like a tool surface, not user-facing prose

## Mechanical status

- Full suite: 247 passed, 2 warnings
- Eval run: 12/12 passed
- Export-size guard and G4 prompt tests: 19 passed
- Demo grounded tools use fake executors in simulated mode

## Pending gate

Do not proceed past Gate G until this taste review is complete and Samay passes
STOP-G
