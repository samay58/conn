# Next session: STOP 2 refinements, then packet I12

You are continuing work on ~/conn, a standalone git repo (remote
github.com/samay58/conn, branch main). STOP 2 ran on 2026-07-07 and passed
with four refinements ordered by Samay; his exact words on the summon
animation were "absolutely gorgeous", and the bar for everything below is
that level of polish. This session lands the four refinements as one commit
(Part 1), then executes packet I12, the tuning playground (Part 2). There is
no re-review round for Part 1: verification is the mechanical gates plus a
fresh screenshot set, so get each change right against the spec below.

## Load first, operate under them all session

- ~/phoenix/.agents/skills/fable-judgment/SKILL.md and fable-execution/SKILL.md
  at task start
- ~/phoenix/.agents/skills/fable-verification/SKILL.md before shipping any
  conclusion or claiming done
- ~/phoenix/.agents/skills/design-engineering-craft/SKILL.md (motion and
  interface code)

## Reload context before touching anything

- docs/STATE-OF-PLAY.md (current state; STOP 2 verdict recorded under Open
  items)
- docs/2026-07-07-roadmap.md, Block A
- docs/plans/2026-07-05-ux-craft-plan.md, packet I12 with its 2026-07-07
  cold-start notes
- docs/2026-07-05-ux-craft-spec.md: the Palette, State vocabulary, Personality,
  Motion, and Typography tables. Part 1 changes several of their rows; the
  table updates land in the same commit as the code.

Ground-truth files for Part 1, read before editing:
macos/Sources/Conn/IslandView.swift (caption, primaryText, primaryColor,
runningTool), macos/Sources/Conn/IslandChipView.swift,
macos/Sources/Conn/DesignTokens.swift, macos/Sources/Conn/WaveformView.swift,
src/conn/tools/registry.py (the preview lambdas), src/conn/tools/harness.py
(_safe_preview), and the Chip model in AppState plus the daemon's chip
broadcast (check whether the tool name travels with the preview; change 2
needs it).

## Environment contract

- Python: ~/conn/.venv only, never the phoenix venv. Run as:
  cd ~/conn && PYTHONPATH=src .venv/bin/python -m pytest tests -q
- Swift: every build and test needs
  DEVELOPER_DIR=/Applications/Xcode-beta.app/Contents/Developer.
  Run as: cd ~/conn/macos && DEVELOPER_DIR=... swift test
- Evals: cd ~/conn && PYTHONPATH=src .venv/bin/python -m conn --eval
- Full gate set is all three (256 Python, 19 Swift, 12/12 evals as the
  baseline; re-verify, do not trust these numbers). All green before each
  commit and again after.
- Rebuild and install after Swift changes: cd ~/conn/macos &&
  DEVELOPER_DIR=... ./make-app.sh install, then pkill -x Conn;
  open /Applications/Conn.app
- Screenshot rig: cd ~/conn/macos && DEVELOPER_DIR=... swift build &&
  ./.build/debug/Conn --preview --shoot /tmp/conn-states (expect 11 PNGs).

## Part 1: the four STOP 2 refinements (one commit, Phase 2 scope)

### Change 1: lilac is the signature color; thinking gets its own beat

- `DesignTokens.islandAccent` becomes lilac #C3B1E1, that is
  Color(red: 0.765, green: 0.694, blue: 0.882), replacing the blue at
  DesignTokens.swift:52. The listening waveform and the perimeter ring
  inherit it with no further change since both consume islandAccent. It
  clears 4.5:1 on black by a wide margin (roughly 9:1); state that check ran.
- The thinking caption becomes the word "thinking" plus three trailing dots,
  lowercase, SF Pro 11pt medium, in islandAccent. Today thinking falls
  through primaryText's default arm and renders the grey state label; give
  it its own arm.
- The signature move: the three dots render as separate Text elements whose
  opacity sweeps in sequence (a quiet wave, one dot leading the next), driven
  by a TimelineView that is paused unless phase == thinking and aliveness > 0.
  New token `thinkingEllipsisPeriod` (start at 1.2s) plus the dot opacity
  floor in DesignTokens. Aliveness 0 renders the dots static at full opacity.
  No italics: color plus motion is the signature; three treatments on one
  word would be noise.
- The thinking waveform stays textSecondary low-amplitude breath, so
  listening (lilac waveform) and thinking (grey waveform, lilac word) stay
  distinct at a glance.
- Motion policy note: this adds a third gated timeline to the policy
  (waveform in active phases, breath in listening, ellipsis in thinking).
  Update the spec's motion policy sentence, extend the tick-count test
  pattern in IslandWaveformTests to pin the ellipsis timeline paused outside
  thinking, and name the new timer in the commit message per the roadmap's
  standing constraint.
- Spec table updates: Palette row for island.accent (value and note that
  lilac is the signature), State vocabulary rows for listening and thinking.

### Change 2: the running tool renders as a quiet capsule

- While acting, the tool indication moves out of the plain caption line into
  a small capsule: Capsule fill white at 0.10 opacity, text SF Pro 10.5pt
  medium in islandText, height 20pt, horizontal padding 8pt. New tokens:
  `toolChipHeight`, `toolChipPaddingH`, `toolChipBgOpacity`. It sits where
  the acting caption renders today, under the waveform.
- The label is humanized, present progressive: a Swift map from tool name to
  display label ("phoenix_search" to "Searching the vault", "app_open" to
  "Opening app", "clipboard_set" to "Copying to clipboard", cover every
  executable tool in registry.py). Fallback for unmapped names: underscores
  to spaces. This needs the tool name on the client; today runningTool reads
  chip.preview. Check the daemon's chip broadcast payload; if the name is
  not already in it, add a name field daemon-side and thread it through the
  Chip model. The string map is copy, not geometry, so it may live beside
  IslandView rather than in DesignTokens; the token guard scans motion,
  palette, and geometry literals only.
- Spec table update: State vocabulary row for acting.

### Change 3: chip previews fit the space, whole

"Copy 2...lipboard" is the named defect: mid-word middle truncation reads as
slop. The island does not grow to fit text; the text is composed to fit the
island.

- Daemon side, the real fix: rewrite the preview lambdas in registry.py whose
  output length is unbounded. `clipboard_set` becomes "Copy to clipboard"
  (the character count moves to the trace, where detail belongs).
  `computer_type_text` becomes "Type text". Previews that embed short args
  (app names, key combos) keep them.
- Harness safety net: `_safe_preview` clamps every preview to a hard budget
  (32 characters) truncating at a word boundary with a trailing ellipsis,
  never mid-word. Python tests: a 500-character query yields a clamped
  preview with no mid-word cut; clipboard_set's preview is exactly
  "Copy to clipboard".
- Swift safety net: IslandChipView's preview switches truncationMode(.middle)
  to .tail; with the daemon budget in place it should never fire.
- Acceptance: the chip PNG in the fresh screenshot set shows a complete
  phrase.

### Change 4: budget hold gets its own identity

- New token `islandGold` #E0C060, that is
  Color(red: 0.878, green: 0.753, blue: 0.376), used by budget_hold
  everywhere it currently borrows islandRed (primaryColor, the cost figure,
  the override affordance). Failed keeps islandRed. Gold is money and
  caution without failure; it reads distinct from the amber approval dot
  (#E8A13D) because it is lighter and yellower. Verify contrast on black.
- The state word becomes "Cap reached" (sentence case per the typography
  rules; the current lowercase "cap reached" violates them).
- The cost figure renders "$%.2f" in budget_hold only. Two decimals, not
  one: "$1.0" reads as a typo, "$1.00" reads as money. The live cost meter
  in other phases keeps three decimals; sub-cent spend is real information
  while it counts.
- Override becomes a real button, visually distinct from Approve by
  construction (outline versus fill): label "Override once" (it says exactly
  what will happen, matching the approval chip's explicitness), SF Pro 12pt
  medium in islandGold, transparent fill, 1pt islandGold strokeBorder
  capsule, horizontal padding 10pt, minHeight chipButtonMinHeight,
  .buttonStyle(.plain), .contentShape on the capsule, no keyboard shortcut,
  no focusable state. Verify the row fits inside the island's 280pt content
  width; if it is tight, the cost figure and the button win and the state
  word may drop.
- Spec table updates: Palette (new gold row), State vocabulary row for
  budget_hold.

### Part 1 gates and commit

- Full gate set green, including the token guard
  (tests/test_design_tokens.py) with the new tokens in DesignTokens.swift.
- Fresh screenshot set: thinking shows the lilac word, listening shows the
  lilac waveform and ring, acting shows the capsule, chip shows a complete
  phrase, budget_hold shows gold with the outline button. Eyeball each
  before committing.
- Spec tables updated in the same commit. Slopcheck every prose surface you
  touch plus the commit message file:
  python3 ~/.claude/scripts/slopcheck.py <file>. No em dashes anywhere.
- One commit, lowercase subject, suggested: "conn: stop 2 refinements, lilac
  signature and state clarity". Trailer: Co-Authored-By line for the model
  you are running as.

## Part 2: packet I12, tuning playground with write-back

Execute I12 exactly per its cold-start notes in the plan (sonnet-tier work
per the plan's routing; Fable decides, cheaper models generate). In short:
DesignTokens becomes a mutable runtime store behind the same static names
(`DesignTokens.current` instance, statics forward to it) so the inspector
can write live values; InspectorView lists every raw motion, personality,
and palette token as a slider or color well beside the preview, with derived
values (squashWidthLead, summonWidthSpring, summonHeightSpring) shown
read-only; Replay drives IslandReveal.token and collapseToken exactly as
IslandController does; Write Back regenerates a compilable DesignTokens.swift
(raw literals plus the derived block from a template, never from slider
state) and prints the spec-table diff to stdout. The inspector must also
expose the new Part 1 tokens (thinkingEllipsisPeriod, toolChip*, islandGold).
Aliveness at 0 must render the fully static island live, which doubles as
the acceptance demo. IslandMotionTests pins the derived math; a write-back
that breaks those tests is wrong.

Done for I12: the write-back file round-trips (compiles, matches the
controls), the token guard stays green after a write-back, and moving the
summonSpring response slider changes the replay without a rebuild. Own
commit: "conn: tuning playground with write-back", same trailer discipline.

## Safety invariants, non-negotiable, verify after any change

- The island panel never takes keyboard focus: IslandPanel keeps canBecomeKey
  and canBecomeMain false, style stays [.borderless, .nonactivatingPanel],
  orderFrontRegardless never becomes makeKey. IslandPanelFocusTests pins
  this. The new Override button is subject to the same pointer-only rules as
  Approve: no keyboard shortcut, no focusable control, no default-button
  styling, no path where Return reaches it.
- Every motion, palette, and geometry literal lives in DesignTokens.swift;
  tests/test_design_tokens.py enforces it.
- No timers outside the motion policy as amended by change 1 (waveform in
  active phases, breath in listening, ellipsis in thinking); the tick tests
  pin it.
- No osascript anywhere. The shell allowlist ships empty. The budget cap is
  a hard stop.

## Known findings, recorded not fixed, by prior decision. Leave them.

The localhost approval websocket is unauthenticated, and assistive-tech
AXPress can activate the island buttons. Both await Samay's call; do not
silently fix or expand scope.

## Standing constraints

- Do not rebase or rewrite existing commits.
- Check the working tree for a parallel session before you push; confirm
  your edits survived by grepping the actual change; verify the push with
  git ls-remote.
- Do not start Block B (STOP-G, R5, X1) or anything past I12 without
  Samay's word. STOP 3 (hand tuning) follows I12 and is Samay-driven.

Delete this file when Block A closes at STOP 3.
