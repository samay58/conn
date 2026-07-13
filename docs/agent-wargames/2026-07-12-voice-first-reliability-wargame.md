# Wargame: Conn voice-first reliability architecture

Date: 2026-07-12

Decision question:

> What is the smallest architecture that makes Conn flexible enough for
> ordinary voice-first Mac work and reliable enough to trust, without
> weakening the verified-action invariants?

## Source packet

The wargame used six bounded sources:

1. Latest live trace, receipt, and daemon log:
   `data/traces/2026-07-12/session_a4f5c83703.jsonl`,
   `data/receipts/2026-07-12/session_a4f5c83703.json`, and
   `data/logs/daemon-2026-07-12.log`.
2. `docs/2026-07-09-verified-action-engine-spec.md` and its existing safety
   boundaries.
3. Model-facing prompt and tools:
   `src/conn/prompt.py`, `src/conn/tools/registry.py`,
   `src/conn/tools/native_actions.py`, and `src/conn/tools/harness.py`.
4. Turn, protocol, and audio control:
   `src/conn/state.py`, `src/conn/app.py`,
   `src/conn/realtime/openai_ws.py`, and `src/conn/audio.py`.
5. Native planner and current proof:
   `macos/Sources/Conn/NativeSemanticActionEngine.swift`, current Swift tests,
   `src/conn/evals.py`, `evals/tasks.json`, and `data/action-probes/`.
6. Current claims and priorities:
   `docs/STATE-OF-PLAY.md`, `docs/2026-07-07-roadmap.md`, and
   `docs/NEXT-SESSION.md`.

## Baseline

The safety kernel is substantive:

- mutations serialize
- stale provenance is checked
- native dispatch is not completion evidence
- uncertain dispatch does not retry
- secure and ambiguous targets refuse
- the bridge is authenticated

The live product loop is not integrated (counts verified 2026-07-13 against
the first upstream session's window; the trace file itself kept growing
because the daemon outlived the app):

- 41 upstream errors occurred in 16 PTT cycles
- context injection failed every turn
- seven state-changing proposals produced only two verified app opens
- five ordinary in-app proposals were blocked before dispatch
- New Tab failed repeatedly
- exact assistant speech and UI acknowledgement timing are absent from traces
- scripted green gates do not test live model behavior

## Candidate strategies

| Candidate | Strongest case | Failure mode | Initial verdict |
|---|---|---|---|
| Patch bugs and strengthen prompt examples | Small diff and quick relief | Model still chooses mechanism, target, predicate, and recovery | Necessary but insufficient |
| Large deterministic recipe catalog | High reliability for known phrases | Brittle by app and version; finite coverage; hides semantic failures | Reject |
| Vision-first computer use | Broadest target coverage | Slow, harder to verify, higher wrong-target risk | Defer |
| Direct API, App Intents, and MCP first | Strong truth in structured domains | Fragmented coverage and current scope expansion | Later execution planes |
| Capability-compiled semantic intents | Flexible language, live native grounding, deterministic proof | Can become a disguised catalog or giant tool | Preferred if kept small |

## Round one

### Builder

The core mistake is placing too much execution knowledge in the model. An
audio model should express `create a tab`, not invent `cmd+t`, `File > New
Tab`, or `window_title_changes`.

A small semantic intent algebra can preserve flexibility:

- create
- select
- select relative
- activate
- invoke command
- set text
- scroll
- open or switch app

Conn.app already owns native state. It can report current affordances and
compile one bounded transaction. The existing policy plane still decides risk
and approval. The existing action engine still proves effects.

### Skeptic

Capability reports describe mechanisms, not what the user meant. A compiler
that recognizes New Tab, Next Note, Show Sidebar, and hundreds of other
phrases could quietly become the rejected app command catalog.

Shadow candidate ranking creates another confidence system that may be
mistaken for evidence. Generic button effects remain unknowable. Recovery may
duplicate actions if dispatch certainty is wrong.

The fastest fix may be smaller: remove the impossible `desired_effect` field,
repair context injection, and let menus return dispatch-only.

### User advocate

The user's problem is not lack of theoretical coverage. It is unpredictability
and repetition. A basic command must either work or produce one intelligible
next step.

The current phrase `Did not run.` is honest but insufficient. It does not say
whether Conn heard the command, found two targets, lost its app connection, or
sent something uncertainly.

The user should not need to know menu paths, shortcuts, AX roles, verifier
syntax, or why the local schema rejects its own advertised field.

### Judge

The skeptic is right that a broad compiler would recreate a catalog. The
builder is right that prompt tuning cannot remove mechanism variance.

Continue with a narrower design:

- fix deterministic transport, audio, and schema defects first
- add a small generic intent algebra
- require a corresponding live affordance before compilation
- keep raw menu and hotkey tools as hidden diagnostic escape hatches
- let no-witness actions become truthful dispatch-only when policy permits
- never use candidate confidence as proof or permission

Open issues after round one:

| ID | Issue | Severity | Status |
|---|---|---|---|
| W1 | Intent compiler could become a per-app catalog | Critical | Open |
| W2 | One safe repair could duplicate an effect | Critical | Open |
| W3 | Capability ranking could weaken ambiguity refusal | High | Open |
| W4 | Audio contamination is inferred, not yet proven | High | Open |
| W5 | Product gates may still reward mechanics over goals | Critical | Open |
| W6 | Restart ownership could distract from action usefulness | Medium | Open |

## Round two

### Builder revision

The compiler gets three hard constraints:

1. Intent verbs are app-agnostic. A new family must cover two apps or one
   direct OS primitive.
2. Compilation needs a matching live native affordance in the current app.
   No bundle-specific command table can authorize it.
3. Every candidate declares its outcome ceiling before risk approval:
   verified, dispatch-only, or blocked.

The first vertical slices are deliberately small:

- `create(kind=tab)`
- `select_relative(relation=next, kind=document)`

They directly address the failed live commands and test whether the boundary
works.

Repair is split from dispatch. A compiler failure or stale observation is
predispatch work. It may re-observe and compile once. After dispatch or any
uncertainty, repair stops.

### Skeptic revision

The raw-model approach cannot reach daily-driver reliability with more prompt
examples. The live trace already shows the model ignoring an explicit New Tab
example and inventing an impossible predicate.

The remaining concern is scope. The program should not build the entire
intent system before proving one end-to-end command. It needs a strict replay
and a vertical slice first.

Verification also needs a read-set budget. Otherwise the new compiler may
improve selection while current full-tree polling creates slow timeouts.

### User advocate revision

The sequence should begin with felt failures:

1. clean restart
2. context reaches the model
3. short PTT commands are not lost or contaminated
4. Open New Tab works without knowing the shortcut
5. Next Note works or asks one clear question

Only then should broader fixture coverage expand.

Failure reporting needs one-click capture. The user should be able to mark the
last command bad without collecting filenames or writing a bug report.

### Judge

Proceed.

The approved architecture is a capability-compiled semantic control loop with
a small app-agnostic intent algebra, live affordance requirement, compiler-
owned witnesses, and one predispatch repair.

Implementation order matters:

1. Make traces tell the full user story.
2. Repair Realtime item lifecycle and daemon ownership.
3. Prove or eliminate audio contamination and silent short-turn loss.
4. Remove model-authored predicates and raw strategy choice.
5. Ship New Tab and next-item vertical slices.
6. Expand capability and targeted witness compilation.
7. Add bounded recovery and realistic evaluation.
8. Run the daily-driver gate.

## Final issue ledger

| ID | Resolution | Evidence required |
|---|---|---|
| W1 | Intent families stay app-agnostic; live affordance required; bundle-specific command tables banned | Schema review plus source scan |
| W2 | One replan only after proven `not_dispatched`; any dispatch or uncertainty stops | State-machine and bridge-loss tests |
| W3 | Ranking cannot break semantic ties; ambiguity still clarifies or refuses | Duplicate-label and candidate-order tests |
| W4 | Treat audio contamination as a hypothesis until recorded PCM watermark and live barge-in probes confirm it | Audio fixture plus live trace |
| W5 | Add intent, recorded voice, end-to-end fixture, and daily-use goal-completion gates | Acceptance artifacts |
| W6 | Fix lifecycle early because repeated manual cleanup blocks every later dogfood session | 50 restart cycles |

## Rejected shortcuts

- More prompt rules without changing the tool boundary.
- A giant `computer_act` tool.
- Broad per-app command profiles.
- Automatic retry after uncertain dispatch.
- Visual fallback to rescue semantic failures.
- Treating a shadow plan as effect evidence.
- Treating historical success as permission.
- Calling scripted harness evals product proof.

## Fastest uncertainty-reducing proof

Replay the July 12 failure trace against a strict fake Realtime server, then
implement `create(kind=tab)` through live menu discovery with a compiler-owned
outcome ceiling. Run the same short recorded voice command through the signed
app.

If that vertical slice cannot complete without raw strategy or predicate input
from the model, the architecture needs revision before it expands.
