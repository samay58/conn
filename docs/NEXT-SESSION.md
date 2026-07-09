# Next session: P0 reliability round, the frontmost spine

Written 2026-07-07 after Samay's live drive of the refinement build. Four
bugs registered below with trace evidence; they compound into "it feels
buggy" because three of them share one root. This round pulls S2, S3, and
R5 forward, ahead of STOP 3: tuning polish means nothing while context
reads lie. STOP 3 (hand tuning) runs after this round.

Amended 2026-07-08: the first drive of this menu died on TCC identity,
so the identity and audio round
(`docs/2026-07-08-identity-audio-spec.md`) ran and landed. Both rounds
now close together: run the acceptance list below FIRST (it makes the
grants stable and visible), then the quick-test menu. This file is
deleted when both are green.

## Identity and audio acceptance (run first, in this order)

0. One-time: create the signing certificate. Keychain Access >
   Certificate Assistant > Create a Certificate, name `Conn Dev
   Signing`, Identity Type Self-Signed Root, Certificate Type Code
   Signing, override defaults with validity 3650 days. Then
   `cd macos && ./make-app.sh install`, relaunch Conn, and grant
   Accessibility to Conn.app once (the current /Applications build is
   ad hoc, so this one regrant is expected). If doctor's python lane
   warns, add what it names (the Python.app bundle) in the same pane.
1. Rebuild and reinstall again (`./make-app.sh install`), zero Settings
   visits this time: a context read returns a real window title with
   accessibility granted (T3 plus the app lane).
2. "Open a new tab" via app_menu and cmd+t behind the chip both execute
   with Conn.app attached; kill the app and confirm the python fallback
   either works (if the Python.app grant is on) or refuses naming
   exactly what to grant (T1, T4).
3. Kill a lane's grant on purpose (toggle Conn off in Accessibility):
   the island warns within a second of the next session start or app
   attach, the console shows the banner, and the refusal names the fix
   (T2).
4. Ten whispered-then-normal utterances at desk distance: no clipped
   first words, no non-English fragments, the "barely heard you" hint
   on the too-quiet ones (A1 to A3).
5. Then the standing quick-test menu below, which closes both rounds.

Evidence: data/traces/2026-07-07/session_d3708bd6a7.jsonl (21:24-21:34,
the live drive). Read it before touching anything.

## Bug 1 (P0): frontmost app reads Kaku, always, for everything

Every computer_get_context in the session returned Kaku
(fun.tw93.kaku) with window_title null, across a session where Chrome
was activated three times (activated: true each time) and Safari once.
The reading NEVER changed. Two candidate causes, both plausible, run the
discriminating test first:

- Staleness: NSWorkspace.sharedWorkspace().frontmostApplication()
  (mac.py:20 and ax.py:214, the two call sites) can serve stale state in
  a long-lived daemon that never pumps an AppKit runloop. The
  never-changes-across-ten-minutes pattern smells like this.
- Imposter class: Kaku is an accessory/overlay app; the roadmap's S3
  packet ("regular-activation-policy apps only, the Kaku class") already
  names it. This explains a wrong reading, not a frozen one.

Discriminating test: in the app-spawned daemon, log frontmostApplication
against NSWorkspace runningApplications filtered by isActive and against
the CGWindowList front window owner while switching apps by hand. Fix
direction: replace frontmostApplication with a per-call fresh source
(active running application, or CGWindowList owner), THEN apply the S3
activation-policy filter on top so accessory apps never win. Acceptance:
a trace shows get_context tracking Chrome -> Safari -> Terminal switches
live, Kaku never reported while a regular app is frontmost.

## Bug 2 (P0): daemon claims no Accessibility when the app has it

get_context returned accessibility not_granted and computer_ax_snapshot
died with ax_untrusted: Accessibility permission required, while
Conn.app holds the grant. TCC grants bind to the binary: the grant is on
Conn.app, the daemon is .venv/bin/python spawned by it, a different TCC
identity. AXIsProcessTrusted() (mac.py:41) answers for the python
process. This kills selected-text, window titles, and the whole
grounded lane (snapshot, click, type) in live use.

Fix lanes, in order of durability:
- S2 (the specced fix, pulled forward): route context reads through the
  app's AX grant (app-side read, daemon asks the app over the existing
  websocket), python fallback stays for the console-only path.
- Stopgap acceptable this round: --doctor names the exact python binary
  path and the System Settings pane to grant it; verify the grant
  sticks across daemon relaunch.

Acceptance: live trace shows accessibility granted, a real window
title, selected text readback working, and one grounded snapshot
succeeding under the app-spawned daemon.

## Bug 3 (P0, downstream of 1): app_menu gate blocks the app you are in

"Open a new tab in Chrome" with Chrome visibly frontmost -> app_menu
blocked app_not_frontmost: Google Chrome, repeatedly. The gate
(_guard_present_app_frontmost, risk.py:55) reads
ctx.ax.backend.frontmost() -> the same stale NSWorkspace source. Fixing
bug 1 fixes this; the acceptance for this bug is its own trace: switch
to Chrome by voice, then "open a new tab" completes via app_menu with
zero blocks. Add a regression eval to evals/tasks.json for the
switch-then-menu chain.

## Bug 4 (P1): "meta+t" rejected by the hotkey normalizer

Model proposed computer_hotkey {"combo": "meta+t"} -> invalid_hotkey:
expected exactly one primary key. _normalize_combo (ax_input.py:551) has
no alias for meta/super/win, so meta lands as a second primary key.
Fix: alias meta and super to cmd; add the canonical combo grammar to
the tool description in registry.py so the model proposes cmd+t in the
first place; test both. Check the hotkey allowlist covers the obvious
tab/window verbs (cmd+t, cmd+w, cmd+n) or that the refusal names the
allowlist so the model reroutes to app_menu.

## Bug 5 (P2, observed in daemon log): shutdown hygiene

data/logs/daemon-2026-07-07.log shows repeated "Task was destroyed but
it is pending" for Broadcaster._writer (server/http.py:48) and one
PaMacCore err -50 on teardown. Cosmetic until it isn't; fold into the
round if cheap, otherwise register in the ledger.

## Session discipline

Load fable-judgment, fable-execution first; fable-verification before
any "fixed" claim. Environment contract unchanged (repo venv,
DEVELOPER_DIR for Swift, full gate set green before and after each
commit). Reproduce each bug from the trace BEFORE fixing; watch it fail,
fix, watch the same probe flip. One commit per bug or tight cluster,
lowercase subjects, slopcheck everything. Rebuild and install the app
after Swift changes; leave a fresh Conn.app in /Applications at session
end (standing practice now). Update STATE-OF-PLAY, the roadmap Block
order note, and the ledger. STOP 3 stays parked until this round is
green in a live drive.

## After the bugs: the quick-test menu (creative control loops)

Run these as live probes once the spine is honest. Each is a real loop
Samay can drive in under a minute; together they map where voice beats
keyboard. Log verdicts per loop (faster / same / worse than hands).

1. App gymnastics: "switch to Chrome", "back to Terminal", "open Notes
   and come back". The thesis loop; should feel instant now.
2. Tab jockey: "focus the tab with the pull request", "open a new tab
   and search conn repo" (app_focus_tab fuzzy match + menu/hotkey).
3. Context read-back: "what app am I in", "what is this window", "read
   me what I have selected". The S2 payoff; zero-risk reads.
4. Clipboard pipelines: "copy this selection, then search the vault for
   it", "put the window title on my clipboard". Chains read -> act_low.
5. Vault reflexes: "find the transformer paper notes and open them",
   "search the vault for budget hold". Search-then-open chains, the
   second target loop.
6. Menu diving without hands: "use File, New Private Window", "toggle
   the sidebar". app_menu as the universal verb where hotkeys are not
   allowlisted.
7. Grounded pointing: "take a snapshot, click Send", "type hello into
   the search field and submit" (confirm-gated; tests the whole
   propose-approve-act spine end to end).
8. Screenshot sanity: "take a screenshot" mid-task; verify it lands
   local and dies at session end.
9. Compound intents: "switch to Chrome, open a new tab, search for
   openai realtime pricing" in ONE utterance. Tests the pending-call
   ledger under a three-tool chain.
10. Refusal feel: ask for something blocked ("quit all my apps", "type
    my password") and judge whether the refusal is crisp and the model
    reroutes sensibly. The safety model as UX, not just guardrail.
11. Barge-in and belay under load: interrupt mid-chain, "belay that"
    mid-tool; the island should retract clean, no zombie continuations.
12. Latency perception: alternate voice vs hands for loops 1 and 5 five
    times each; note which you reach for without thinking by the end.

Ideas past the current tool surface (register in the idea ledger only
if a loop above earns it): window tiling by voice ("left half, right
half"), a "read the room" digest (frontmost plus recent notifications),
voice marks ("remember this spot, come back to it"), and dictate-to-
selection replace. None are Block B; they wait for triggers.

Delete this file when the P0 round closes and STOP 3 is scheduled.

## 2026-07-09 late-drive findings (for the next session)

Identity plumbing verified live: grants green both lanes after a
cert-signed reinstall with zero Settings visits (trace
session_de08ed53a2). Three open findings, in priority order:

1. app_menu reports success but does not perform: the trace says
   pressed Shell > New Tab ok in 84ms, Samay's eyes say the Shell menu
   opened and nothing else happened. AXPress on the leaf item returned
   success without invoking it. Suspects: lazy menu population (the
   AXMenu's children may need the menu opened before the real items
   exist, so the walk may press a stale or proxy element) and blind
   trust in the AXPress return code. First step is observability: tag
   the menu result with the lane that pressed (menu has no lane field;
   hotkey already does) and verify post-press that the menu actually
   closed or the action occurred. Then probe AXPress semantics live
   against Terminal and Safari from both lanes.
2. Transcription garbled but English ("goes resale for around the
   Tatton terminal"): the language pin holds; recognition quality does
   not. Check input device choice (BOYA mini is the default in use) and
   whether pre-roll plus device selection improves it.
3. Model repeated its previous tool call: "Open Safari" re-proposed
   app_menu Shell > New Tab in Terminal and executed after approval.
   Prompt tightening, reasoning effort, and the specced X2 context
   pruning are the candidates.

Samay's verdict at close: still not usable against real apps; the
menu-action lane needs real work, not patchwork. Plan the session
around finding 1 with a live probe harness before writing any fix.
