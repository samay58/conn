# Identity and audio round: stable grants, honest capture

Written 2026-07-08 after the first quick-test drive of the P0 reliability
build (trace `data/traces/2026-07-08/session_ad8480c2d0.jsonl`). The drive
surfaced a theme, not a bug list: every hard failure this week is a TCC
identity boundary, and the platform identity layer under Conn is neither
stable nor observable. This round makes identity boring and capture honest.
The P0 quick-test menu in `docs/NEXT-SESSION.md` stays the closing script;
this round unblocks it.

## Evidence from the drive

1. `computer_get_context` answered through the app lane (`source: app`)
   but reported `accessibility: not_granted`, `window_title: null`. The
   app lane is honest: that is Conn.app's own `AXIsProcessTrusted()`.
   The 15:32 rebuild and reinstall re-signed the app ad hoc, macOS
   invalidated the existing Accessibility grant, and the Settings toggle
   still shows on. Every future reinstall silently kills the grant again.
2. `app_menu` (File > New Tab) and `computer_hotkey` (cmd+t) both died
   `accessibility_untrusted` after the user granted the binary doctor
   named. Doctor resolved `.venv/bin/python` to
   `Python.framework/.../bin/python3.14`, but the daemon's actual process
   image is `Python.framework/.../Resources/Python.app/Contents/MacOS/Python`
   (framework python is a launcher that execs Python.app). The grant went
   to a binary that never runs, so the python-lane grant did nothing.
3. Voice transcripts came through as clipped fragments with hallucinated
   Spanish ("óperas serían" for what was almost certainly "open
   Obsidian"): leading audio is lost between PTT keydown and the daemon
   gate opening, and the transcription has no language pin, so tiny
   slivers decode as whatever language fits. The model often acted
   correctly anyway (audio and transcript are separate lanes), which made
   the failures look random.
4. Benign, ledgered, not chased: "Cancellation failed: no active
   response" churn and one PaMacCore -10863 line in the daemon log.

## Why this round exists (the judgment)

Fix-the-behavior rounds keep landing on green gates and then dying on the
machine because the failing layer is beneath the harness: grants bind to
code identity, and Conn churns two identities per rebuild (a fresh ad-hoc
app signature; a venv launcher exec chain). Nothing in the product
surfaces grant death, so it presents as random breakage mid-command.
The bar for this round is three properties: identities stay stable across
rebuilds, grant state is visible before the first command, and refusals
name the exact artifact to grant.

## Lane T: TCC identity

### T1: doctor names the true process image

`--doctor` (and the refusal text for `accessibility_untrusted`) must name
the artifact TCC actually checks: the current process image from
`proc_pidpath` (via ctypes libproc), not a `readlink` of `sys.executable`.
When the image sits inside `Python.framework/.../Resources/Python.app`,
name the `.app` bundle path, because that is what the Settings pane adds
cleanly. Done: a unit-tested resolver maps (executable path, image path)
to the grant target; doctor prints it; live doctor names Python.app on
this machine.

### T2: grant preflight, surfaced

The daemon publishes both lanes' Accessibility state at session start and
whenever the app attaches: `python_ax` (daemon-side
`AXIsProcessTrusted()`) and `app_ax` (already carried by the app's
context replies). Trace event `ax_grants`; console and island render a
warning state when a lane is dark; `accessibility_untrusted` errors name
the lane and the grant target from T1. Done: trace shows `ax_grants` on
session start; a dark lane is visible on the surface within one second of
session start; the refusal string carries the grant path.

### T3: stable app signing

`make-app.sh` signs with a persistent self-signed code-signing identity
(keychain name `Conn Dev Signing`) when present, falling back to ad hoc
with a loud stderr warning that TCC grants will reset on install. README
gains the one-time `Keychain Access > Certificate Assistant` recipe.
Done: rebuild, reinstall, relaunch; the app-lane grant survives with no
Settings visit (verified live once); the fallback warning prints when the
identity is absent.

## Lane A: audio capture

### A1: PTT pre-roll

The input stream already runs continuously; keep a ring of the last
`audio.preroll_ms` (default 400) and flush it ahead of live frames when
the gate opens, so the first syllable stops dying between keydown and
gate-open. Done: unit test proves ring content precedes live frames in
order after gate open, and the ring is cleared on gate close; config knob
documented in config.toml.

### A2: device choice and low-signal honesty

`[audio] input_device` (substring match against input device names, empty
means system default) selects the capture device at stream open; doctor
lists input devices and marks the selected one. When a listening window
closes with peak rms below a threshold, the daemon emits a `low_signal`
trace event and the surfaces show a "barely heard you" hint instead of
letting silence masquerade as a model failure. Done: unit-tested device
resolver (exact, substring, not-found fallback with warning); low-signal
event fires on a synthetic quiet capture; hint renders on the console.

### A3: transcription language pin

`[realtime] transcription_language` (default "en") rides the session
config's `input_audio_transcription`, ending Spanish-fragment
hallucination on short clips. Done: unit test pins the session.update
payload; a live fragment transcribes as English or empty, never another
language.

## Lane T4 (amendment, added and executed 2026-07-08 in session)

Scope decision made in session discussion: pull the AX-action migration
forward. What landed: `computer_hotkey` posting and `app_menu` (both the
menu tree read and the press) ride Conn.app's Accessibility grant over
the existing websocket when the app is attached, via the ax_action /
ax_action_result message pair and an AppLaneInputBackend; the python
lane stays the fallback when no app is attached; wire failures refuse
rather than fall back so a chord that may have posted is never posted
twice; refusals name the lane that refused.

What deliberately did not land, with the judgment recorded: the grounded
click/type lane stays python-side. Its safety semantics (snapshot
fingerprints, execution-time re-walks, secure-field redaction in
SnapshotStore.resolve) perform AX reads at execution time, so moving
only the action posting would not free the grant, and moving the reads
is a full remote AX backend (serialized trees, reworked window-identity
semantics, a Swift tree engine): a session-sized packet on its own,
registered in the idea ledger as T4b with a design sketch and a concrete
trigger. Consequence for the grant story: the Python.app grant is still
required for the grounded lane and app-less runs; doctor says exactly
that. The two failures from the drive (app_menu, computer_hotkey) no
longer need it.

## Order and gates

T1 and T2 first (they make every later failure diagnosable), then A1 to
A3, then T3 (touches the build script, verify last so reinstall churn
does not confuse the lane work). Full gate set green before and after
each commit (pytest, evals 13/13, swift, token guard). Safety invariants
untouched: the harness still owns permissions, approvals stay
pointer-only, continuations stay withheld, the budget cap stays hard.

## Round acceptance (live, Samay's hands)

1. Fresh rebuild and reinstall, zero Settings visits, then: context read
   returns a real window title with `accessibility: granted` (T3 + app
   lane).
2. `app_menu` File > New Tab and cmd+t behind the chip both execute after
   granting exactly what doctor names, once (T1, python lane).
3. Kill a lane's grant on purpose; the surface shows it within a second
   and the refusal names the fix (T2).
4. Ten whispered-then-normal utterances at desk distance: no clipped
   first words, no non-English fragments, low-signal hint on the
   too-quiet ones (A1 to A3).
5. Then the standing P0 quick-test menu in `docs/NEXT-SESSION.md`, which
   closes both rounds together.
