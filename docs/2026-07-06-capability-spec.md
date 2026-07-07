# Conn capability round: grounded control, connections, context

Written 2026-07-06 on Fable; revision 2 after two adversarial review passes
(codebase-refutation and design-blindspot, both Opus, findings adjudicated by
Fable). This document is both the design spec and the execution plan for the
capability round: it makes every design decision, and builders execute packets
without judgment calls. Where a builder might guess, this document decides. A
packet an agent cannot complete comes back as a question, not a guess.

Relation to prior documents: `docs/gpt-realtime-2-computer-agent-spec.md` (v0)
remains the reference for architecture, safety, and cost; this spec renegotiates
its per-app-profile plan (R1 below). The UX-craft round
(`docs/2026-07-05-ux-craft-spec.md`, Phases 2-5) is untouched and shares zero
files with this round: this round is Python/daemon/config/docs only, no Swift.
Either round may run first or interleave.

## Thesis

Conn becomes a general computer tool by grounding actions in what is actually
on screen, not by memorizing a taxonomy of commands. Three moves:

1. **Grounded UI control.** The model reads a live accessibility snapshot of
   the frontmost window (ephemeral element refs), then acts on a ref. The
   harness re-resolves every ref against the live tree before acting; any
   drift becomes a structured refusal, never a wrong click. No selectors, no
   memorized element names, no per-app command vocabulary. Scroll and
   menu-bar verbs make the everyday commands ("close this," "scroll down,"
   "new tab") executable on a fresh install.
2. **Connections via MCP.** The daemon becomes an MCP client. Any capability
   that exists as an MCP server (calendar, mail, home, vault tooling) plugs in
   through config, inherits Conn's gate system, and appears to the model as an
   ordinary tool. Conn never grows bespoke integrations again.
3. **Context injection.** At PTT-down the daemon captures the frontmost app
   and window title locally and injects them as a system item before the turn's
   `response.create`. "Close this," "switch to the PR tab" resolve without a
   tool round trip. Selected text is opt-in, never default (D12).

The three safety invariants (harness owns permissions; continuations withheld
until tool results are real; budget cap is a hard stop) are unchanged and
inviolable. Approvals stay pointer-only. The loop never lies about being alive.

## Decisions of record

**D1. Blocked v0 tools graduate by code, not config.** `computer_click`,
`computer_type_text`, `computer_hotkey` graduate from BLOCKED to real risk
levels in this round; `computer_ax_tree` is deleted and replaced by
`computer_ax_snapshot`; `computer_scroll` and `app_menu` are new. The invariant
"config can never unblock a blocked tool" is untouched: graduation is a
spec-level code change with tests, the sanctioned path.

**D2. Snapshot grounding is the only path to element actions, and resolution
has two modes.** `computer_click`, `computer_type_text`, `computer_scroll`
take `(snapshot_id, ref)`, never coordinates, never free-text selectors.
Resolution re-walks the element's recorded tree path and requires ALL of:
role unchanged, label unchanged, sibling count at every path level unchanged,
and resolved frame center within 40px of the recorded center. Any miss is
`stale_ref: take a new snapshot`; the refusal teaches the model the re-read
loop. Two modes:

- *Gate-time* (`for_execution=False`): also enforces
  `snapshot age <= ax.snapshot_ttl_s` (`snapshot_expired`), guarding the
  freshness of the model's read.
- *Execution-time* (`for_execution=True`): NO TTL check (an approval may sit
  up to 30s and an approved action must not expire under the user's cursor),
  but re-verifies identity, frontmost window, and visibility at the moment of
  action.

Coordinate clicking and screenshot-guided clicking stay out (idea-ledger #9
unchanged).

**D3. Click risk: confirm by default, per-app role trust as the speed lane.**
`computer_click` is ACT_CONFIRM. Config table `[interactions.trusted]` maps a
bundle id to a list of AX roles that downgrade to AUTO in that app (e.g. tabs
and buttons in a browser's tab strip). Ships empty. This is the surviving form
of "per-app profiles": a permission speed layer over generic grounding, not a
capability taxonomy.

**D4. Typing is confirm-gated and secure-field-blocked, with browser-aware
detection.** `computer_type_text` is ACT_CONFIRM always (no trust downgrade
this round). An element is *secure* when ANY of: role or subrole is
`AXSecureTextField` (self or ancestor); its value renders as bullets/masking
characters; in Chromium/WebKit trees, DOM-derived attributes (e.g.
`AXDOMClassList`, `AXRoleDescription`) indicate a password input. Secure →
BLOCKED with `secure_field: Conn never types into password fields`. In a
browser bundle, a field whose secure status cannot be determined types only
WITHOUT `submit` (the Return press is refused with `submit_uncertain_field`).
Text cap 2000 chars. `submit: true` presses Return after typing, under the
same single approval.

**D5. Hotkeys are config-enumerated, everything else blocked.** Two lists:
`hotkeys.auto` and `hotkeys.confirm`, both shipped empty, combos normalized
lowercase `cmd+shift+t` form. A combo in neither list blocks with
`hotkey_not_allowlisted`. Everyday app commands do not depend on this tool:
`app_menu` (D17) covers them grounded.

**D6. Tab switching gets a dedicated fast path.** `app_focus_tab(title, app?)`
fuzzy-matches tab-like elements (role `AXTab`, `AXRadioButton` inside
`AXTabGroup`, Chromium tab-strip buttons, and any element whose role or
subrole contains "tab") in the target app's front window and presses the best
match. One tool round trip instead of snapshot+click. Risk ACT_LOW: it only
moves focus. Ambiguity (no match ≥ threshold, or 2+ within 0.1 of each other)
returns the candidate list in the result envelope so the model can ask; it
never guesses. The app allowlist guard applies ONLY when `app` is given
(a dedicated guard variant; the existing `_guard_app_allowlist` blocks empty
strings and must not be reused verbatim). Omitted `app` = frontmost app,
always permitted.

**D7. Chromium AX enablement is the daemon's job, and it cleans up.** Chromium
apps render a full AX tree only when assistive tech is detected. Before
snapshotting or tab-scanning a Chromium app, the backend sets
`AXEnhancedUserInterface=true` (and `AXManualAccessibility` where honored) on
the app's AX element, once per app per daemon lifetime, recording the prior
value. On daemon shutdown, recorded prior values are restored (best-effort;
crash leaves the flag set, documented in README as a known interaction:
Chromium window-management quirks while the flag is up). Zero osascript
remains true.

**D8. Snapshot privacy rails.** Snapshots are model-visible by design, so:
element values truncate at 80 chars, secure-field values (per D4 detection)
always render `[redacted]`, and `ax.deny_bundles` (shipped default: 1Password,
Keychain Access) refuses snapshots of sensitive apps entirely with
`bundle_denied`. Snapshots live only in the daemon's in-memory store and the
trace (local, gitignored).

**D9. MCP servers are explicit-allowlist only.** `[[mcp.servers]]` config
entries name a server (stdio `command` + optional `env` map, or HTTP `url`)
and a required `expose` list of tool names. No wildcard exposure. Secrets live
in the config `env` map (config.toml is local and gitignored per the v0
contract; values never appear in logs, traces, or tool payloads). Total
exposed MCP tools capped at `mcp.max_tools` (default 12); over-cap is a
startup config error, not a silent truncation. Per-server connect timeout
`mcp.connect_timeout_s` (default 3.0): a slow server is skipped exactly like a
dead one and never delays daemon readiness. Tool schemas are frozen at
`start()` for the daemon lifetime; server-side drift requires a daemon
restart.

**D10. MCP risk mapping and description hygiene.** Per exposed tool:
`readOnlyHint=true` → READ; otherwise ACT_CONFIRM. Config `risk_overrides` may
move a non-read MCP tool to `auto` only if its `destructiveHint` is not true;
destructive-hinted tools floor at CONFIRM regardless of config. Tool names
normalize to `mcp_<server>_<tool>` (realtime name charset `[a-zA-Z0-9_-]`, max
64 chars; on overflow truncate and suffix a 4-char hash). Server-authored tool
descriptions are DATA, not instructions: they pass to the model length-capped
at 200 chars, and approval chips always show Conn's own generated preview
(`<server>: <tool> <compact args>`), never server-authored text. This is the
prompt-injection rail for compromised servers; the deeper rail remains that
the harness, not the model, owns every gate.

**D11. The harness learns async executors.** `ToolSpec.executor` may be a
coroutine function; `ToolHarness.run` awaits it directly under the same
timeout, else falls back to `asyncio.to_thread` as today. This is how MCP
calls execute without a thread-to-loop bridge. Existing sync executors are
untouched. Continuation-withholding (invariant 2) must hold across the full
30s MCP timeout: the ledger resolves only on real results (M3 tests this by
name).

**D12. Context injection is app+window only by default, best-effort, and
never delays speech.** On PTT-down the daemon captures frontmost app and
window title (existing `mac.get_context` path) in a thread with an 80ms
budget; on success it sends one `conversation.item.create` with role `system`,
text `[local context] app=<name> window=<title>`, routed through the existing
`_send_or_disconnect` path so a mid-send socket failure lands in the
disconnect path, not an unhandled task. The item must land before that turn's
`response.create` (PTT-up); commit ordering is irrelevant. Selected text is
injected ONLY when `context.include_selection = true` (default false), capped
at 200 chars, and never when the frontmost bundle is in `ax.deny_bundles` or
the focused element is secure per D4. Budget exceeded, AX untrusted, capture
error, or reconnect racing the send → skip silently, trace `context_skipped`
with reason; success traces `context_injected`. Config `context.inject`
(default true). Capture timing is verified from the raw trace event, not
`--latency-report` (span table unchanged this round). This is not ambient
watching: capture happens only at the moment the user takes the conn.

**D13. Gate previews may be enriched at resolution time.** The approval chip
must state exactly what will happen, so for grounded calls the gate resolves
the ref first and the chip reads e.g. `Click "Send" (AXButton) in Mail` rather
than `Click element: e12`. Mechanically: `risk.gate_for` returns a third
element `preview_override`; `ToolHarness.gate` folds it into the existing
`ToolCall.preview` field (`preview_override or spec.preview(args)`).
`events.py` is not touched.

**D14. Session tool payload stays bounded.** A guard test asserts
`len(json.dumps(export_openai(registry)))` < 20,000 bytes with the default
config plus a max-size fake MCP config. Growth past that is a design decision,
not drift.

**D15. The daemon's TCC identity is decided, provable, and documented.**
CGEvent posting and AX control require Accessibility trust attributed to the
*posting* process, and macOS attributes an app-spawned daemon to the app but a
terminal-spawned one to the terminal. Decisions: (a) the canonical grant
targets are exactly two and are named in README and DEPLOYMENT: Conn.app (for
app-autolaunched daemons; the C3 path resolver keeps the launch path stable so
the TCC identity is stable) and the user's terminal (for hand-run daemons).
(b) `--doctor` gains a *posting capability* check: `AXIsProcessTrusted` plus a
harmless self-targeted CGEvent post, reporting pass/fail for the process it
runs in, with output stating that the check is only valid when run the same
way the daemon runs. (c) The daemon performs the same check at startup and
reports `input_control: true|false` in `/healthz`; grounded action tools refuse
with `accessibility_untrusted` when false rather than failing opaquely.
(d) DEPLOYMENT documents that TCC grants do not transfer to a second Mac and
must be re-granted per launch identity.

**D16. Snapshots are pruned from the session.** Each snapshot result enters
the conversation as a `function_call_output` whose item id the daemon supplies
(client-generated, tracked per session). When a new snapshot is taken, the
daemon issues `conversation.item.delete` for the previous snapshot's item:
at most ONE snapshot lives in session history at a time. This bounds the
compounding input-token cost of multi-action sequences (a 6-action chain must
not carry six stale UI trees). A guard test in the fake-adapter path asserts
the delete is sent and at most one snapshot item is live after N snapshots.

**D17. Scroll and menu verbs complete the grounded set.**
`computer_scroll(snapshot_id, ref)` performs `AXScrollToVisible` on the
resolved element (fallback: scroll-wheel CGEvent over the element's scroll
area only if AXScrollToVisible is unsupported AND the scroll area is visible
and frontmost). Risk ACT_LOW: it changes viewport, not state. This is the
recovery path for offscreen elements. `app_menu(path)` walks the frontmost
app's AX menu bar matching each path segment fuzzily (same 0.6 threshold as
D6), and presses the terminal item. Risk ACT_CONFIRM, downgradable per-app via
`interactions.trusted` role `AXMenuItem`. No-match returns the available
segment titles at the failing level in the result envelope; it never guesses.
This makes "close this window," "new tab," "quit" executable, grounded, with
zero hotkey config.

## Renegotiations of record

**R1.** v0's "blocked tools open behind per-app profiles with named, validated
targets" is superseded. Named-target profiles were the brittle taxonomy this
round exists to avoid. Grounding replaces validation-by-enumeration;
`[interactions.trusted]` is what remains of profiles.

**R2.** Idea-ledger #10 (arbitrary UI control) and #15 (general-tool breadth)
are taken up by this round on Samay's direct call of 2026-07-06, superseding
their recorded revisit triggers. #11 (MCP adapters) revisit trigger is met by
the same call. #13 (shell execution) stays deferred; #9 (screenshot-to-model)
stays deferred; #12 (Phoenix write lane) stays deferred.

**R3.** STOP 1 (the deferred Phase 0 reliability drill) folds into this round's
STOP-G drill rather than remaining a floating debt.

## Tool contract changes

New and changed tools (all others unchanged):

| Tool | Args | Risk | Notes |
|---|---|---|---|
| `computer_ax_snapshot` | `{query?: string}` | READ | Replaces `computer_ax_tree`. Returns `snapshot_id` + rendered tree of frontmost window. `query` filters elements by case-insensitive label/value substring (redacted values are never matchable). |
| `computer_click` | `{snapshot_id: string, ref: string}` | ACT_CONFIRM (AUTO via `interactions.trusted`) | AXPress when the element supports it (mandatory preference). CGEvent click at frame center ONLY when AXPress is unsupported AND the element's frame intersects the frontmost window's current frame on the active display at post time; otherwise refuse `element_not_visible: scroll it into view or re-snapshot`. |
| `computer_type_text` | `{snapshot_id: string, ref: string, text: string, submit?: boolean}` | ACT_CONFIRM | Clicks to focus (same visibility rules), re-verifies the focused element matches the ref before any keystroke, CGEvent unicode typing in ≤20-char chunks. See D4. |
| `computer_scroll` | `{snapshot_id: string, ref: string}` | ACT_LOW | See D17. |
| `computer_hotkey` | `{combo: string}` | per D5 | CGEvent key chord. |
| `app_focus_tab` | `{title: string, app?: string}` | ACT_LOW | See D6. |
| `app_menu` | `{path: array of string}` | ACT_CONFIRM (AUTO via trusted `AXMenuItem`) | See D17. Max path depth 4. |
| `mcp_<server>_<tool>` | server-declared schema (sanitized) | per D10 | Preview per D10, Conn-generated. |

Snapshot render format (exact, for tests and prompt): one element per line,
two-space indent per depth level, `<ref> <role> "<label>"` plus markers
` value="<truncated>"`, ` (disabled)`, ` (focused)`; header line
`snapshot <id> app=<bundle_id> window="<title>" elements=<n>`. Interactive
roles (button, tab, link, field, checkbox, menu item, radio) are kept
preferentially when truncating to `ax.max_elements`; containers are kept only
as ancestors of kept elements.

## Interface contracts

**`src/conn/tools/ax.py`** (new, packet G1):

```python
@dataclass(frozen=True)
class AxElement:
    ref: str            # "e1", "e2", ... unique within snapshot
    role: str           # raw AX role, e.g. "AXButton"
    label: str          # title/description/help, best available, may be ""
    value: str | None   # truncated to 80 chars; None if absent; "[redacted]" if secure
    enabled: bool
    focused: bool
    secure: bool        # per D4 detection, self or ancestor
    frame: tuple[float, float, float, float]  # x, y, w, h screen coords
    path: tuple[int, ...]      # child-index walk from window element
    sibling_counts: tuple[int, ...]  # sibling count at each path level, for D2

@dataclass(frozen=True)
class AxSnapshot:
    snapshot_id: str    # 8 hex chars
    bundle_id: str
    window_title: str
    elements: tuple[AxElement, ...]
    taken_monotonic: float
    def render(self, query: str | None = None) -> str  # format above

class StaleRef(Exception): ...   # message is the block reason verbatim

class AxBackend(Protocol):
    def frontmost(self) -> tuple[str, int]                      # (bundle_id, pid)
    def window_element(self, pid: int) -> object                # opaque AXUIElement
    def walk(self, window: object, max_depth: int) -> Iterator[RawNode]
    def resolve_path(self, pid: int, path: tuple[int, ...]) -> RawNode | None
    def menu_bar(self, pid: int) -> RawNode | None               # for app_menu
    def enable_chromium_ax(self, pid: int) -> None               # records prior value
    def restore_chromium_ax(self) -> None                        # shutdown, best-effort

class SnapshotStore:
    def __init__(self, backend: AxBackend, cfg: Config): ...
    def take(self, query: str | None = None) -> AxSnapshot
        # raises ToolError("bundle_denied: ...") / ToolError on no AX trust
    def resolve(self, snapshot_id: str, ref: str, *, for_execution: bool
                ) -> tuple[AxElement, object]
        # D2 invariants: role, label, sibling counts, frame drift <= 40px,
        # frontmost window unchanged; TTL enforced only when not for_execution.
        # raises StaleRef("stale_ref: ..."), StaleRef("window_changed: ..."),
        # StaleRef("snapshot_expired: ...") accordingly
```

`RawNode` is a small dataclass (role, subrole, title, value, enabled, focused,
secure_hints, frame, children) produced by the backend so `MacAxBackend`
(pyobjc, ApplicationServices) and `FakeAxBackend` (test fixture built from
literal trees, mutable between calls to simulate UI change) are
interchangeable. All snapshot/resolve/secure-detection logic above the backend
is pure and fully unit-tested against the fake.

**`src/conn/tools/risk.py`** (changed, packet G2): `gate_for` returns
`tuple[Gate, str | None, str | None]`, meaning
`(gate, block_reason, preview_override)`. New module-level table
`RESOLUTION_GATES: dict[str, Callable]` for `computer_click` /
`computer_type_text` / `computer_scroll`: the callable receives
`(args, cfg, ctx)` where `ctx` is `ExecutionContext`, resolves via
`ctx.ax.resolve(..., for_execution=False)`, and returns the tuple. Any
exception inside gating (including `ctx.ax is None`) must yield a BLOCKED
`ToolCall`, never propagate: `ToolHarness.gate` wraps the `gate_for` call so a
gating bug degrades to a refusal instead of killing the event pump.
`ToolHarness.gate` folds `preview_override` into `ToolCall.preview` per D13.
`app_focus_tab`/`app_menu` get the new present-only allowlist guard variant
(D6). Existing `ARG_GUARDS` signature unchanged.

**`src/conn/tools/base.py`** (changed, packet G2): `ExecutionContext` gains
`ax: SnapshotStore | None = None` and `mcp: object | None = None`. G2 also
owns the construction sites: `src/conn/__main__.py`, `src/conn/evals.py`, and
`tests/conftest.py` build the store (`MacAxBackend` live, `FakeAxBackend` in
evals/tests) and pass `ax=` everywhere an `ExecutionContext` is created.

**`src/conn/tools/harness.py`** (changed G2 for gate-fold/gate-wrap, M3 for
async): in `run`, if `inspect.iscoroutinefunction(executor)`,
`await asyncio.wait_for(executor(call.arguments, self.ctx), timeout=spec.timeout_s)`;
else current `to_thread` path. Envelope contract unchanged.

**`src/conn/mcp_client.py`** (new, packet M1):

```python
class McpManager:
    def __init__(self, cfg: Config): ...
    async def start(self) -> list[McpToolInfo]
        # connects all servers with per-server timeout cfg.mcp.connect_timeout_s;
        # dead or slow server logs and skips, never crashes or delays the daemon;
        # raises ConfigError only for over-max_tools totals
    async def call(self, server: str, tool: str, args: dict) -> dict
        # raises ToolError on server error / isError result
    async def stop(self) -> None

@dataclass(frozen=True)
class McpToolInfo:
    server: str; tool: str; conn_name: str        # normalized per D10
    description: str                              # capped 200 chars
    parameters: dict                              # sanitized: object root enforced,
                                                  # $ref/$defs/root-anyOf stripped
    read_only: bool; destructive: bool
```

**`src/conn/tools/mcp_bridge.py`** (new, packet M2):
`register_mcp_tools(registry: dict[str, ToolSpec], infos: list[McpToolInfo], manager: McpManager) -> None`
appends `ToolSpec`s whose executor is an async closure over `manager.call`,
risk per D10, `timeout_s=30.0`, previews per D10 (Conn-generated).

**`src/conn/realtime/base.py` + `openai_ws.py` + `fake.py`** (changed, packets
X1/X2): adapter protocol gains `send_system(text: str) -> None`
(`conversation.item.create`, role `system`, no `response.create`) and
`send_tool_result_item(call_id: str, output: str, item_id: str) -> None` plus
`delete_item(item_id: str) -> None` for D16. Fake adapter records all three
for assertions.

**`src/conn/config.py`** (changed across G2/X1/M2, sequential phases):

```toml
[ax]
snapshot_ttl_s = 10
max_elements = 120
max_depth = 12
deny_bundles = ["com.1password.1password", "com.apple.keychainaccess"]

[interactions]
# trusted = { "com.google.Chrome" = ["AXTab", "AXRadioButton"] }
trusted = {}

[hotkeys]
auto = []
confirm = []

[context]
inject = true
include_selection = false
capture_budget_ms = 80

[mcp]
max_tools = 12
connect_timeout_s = 3.0
# [[mcp.servers]]
# name = "qmd"
# command = ["/path/to/server", "--stdio"]   # or url = "http://127.0.0.1:9000/mcp"
# env = {}                                    # secrets live here; never logged
# expose = ["search", "get"]
```

**Dependencies:** G1 adds `pyobjc-framework-Cocoa`,
`pyobjc-framework-ApplicationServices`, `pyobjc-framework-Quartz` to
`pyproject.toml` (verified importable in the conn `.venv` already; the
declaration closes a latent deploy bug). M1 adds `mcp>=1.2` to
`pyproject.toml` AND installs it into `/Users/samaydhawan/conn/.venv`
(verified absent as of 2026-07-06); M1 re-runs the full baseline after
install before writing any test.

## Latency and cost budgets

| Moment | Budget |
|---|---|
| `computer_ax_snapshot` execution (typical window, ≤120 elements) | ≤350ms p50, ≤900ms p95 |
| `computer_click` / `computer_type_text` / `computer_scroll` execution after approval | ≤150ms |
| `app_focus_tab` / `app_menu`, key-release to effect (tool turn) | within the existing ≤1200ms p50 tool-turn budget |
| Context capture at PTT-down | ≤80ms hard budget, else skipped (verified from trace events, not --latency-report) |
| MCP server connect at daemon start | ≤3s per server, then skipped |

Cost note: a 120-element snapshot renders ~2-4k text tokens ≈ $0.01-0.016 at
text-in pricing per turn it remains in history; D16 pruning holds live
snapshots to one, so multi-action chains stay near-flat instead of
compounding. The existing $1.00 hard stop is the backstop either way.

## Execution plan

Run per Fable doctrine (`~/.claude/FABLE-ORCHESTRATION.md`): a deputy
orchestrator dispatches packets; Fable returns only at gates. Every packet
prompt names its skills; every agent gets explicit model and effort. Packet
builders see only their own packet plus "Global constraints" and their
interface contracts above. Update `docs/orchestration-ledger.md` at each phase
boundary (output tokens by tier, gate results).

**Global constraints (include in every packet prompt):**
- Load skills: `fable-execution`, `fable-verification` (from `~/.agents/skills/`).
  Opus design packets also load `fable-judgment`.
- TDD order: failing test → run, expect FAIL → implement → full suite green →
  commit `conn: <lowercase imperative>` (no em-dashes anywhere, including commits).
- Baseline: 166 tests green via
  `PYTHONPATH=src /Users/samaydhawan/conn/.venv/bin/python -m pytest tests -q`.
  Never reduce the count; never edit a file outside your packet's ownership list.
- `events.py` stays wire/protocol dataclasses only. The state machine stays
  pure. No osascript. The three safety invariants are inviolable.
- Demo mode (`--demo --simulate-tools`) must remain zero-credential and
  zero-side-effect after every packet.
- If the packet requires a judgment call the spec does not decide, stop and
  return the question.

### Phase G: grounded UI control

Order: strictly G1 → G3 → G2 → G4. G2 imports executors from `ax_input.py`
(G3), so they are NOT parallel; the earlier "disjoint files" assumption was
refuted in review.

#### Packet G1: snapshot engine [opus, effort high] [ADV]

**Files:**
- Create: `src/conn/tools/ax.py`
- Modify: `pyproject.toml` (pyobjc frameworks)
- Test: `tests/test_ax_snapshot.py` (new)

**Interfaces (produces):** the `ax.py` contract above, exactly. `MacAxBackend`
and `FakeAxBackend` both live in this file; the fake takes a literal `RawNode`
tree in its constructor and supports mutation between calls (to simulate UI
change for stale-ref tests).

- [ ] Failing tests against `FakeAxBackend`: take → refs stable and unique;
      render format matches the spec string exactly (golden assertion);
      interactive-role-preferential truncation at `max_elements`; secure
      detection per D4 including a Chromium-shaped fake tree (subrole-based
      and DOM-hint-based password fields both detected); secure value renders
      `[redacted]` and is unmatchable via `query`; value truncation at 80;
      `query` filtering; deny_bundles raises `ToolError("bundle_denied: ...")`;
      resolve happy path both modes; label change → `stale_ref`; sibling
      insertion/reorder → `stale_ref`; frame drift > 40px → `stale_ref`;
      frontmost change → `window_changed`; TTL expiry →
      `snapshot_expired` when `for_execution=False` and NO error when
      `for_execution=True`; chromium enable records prior value and restore
      puts it back.
- [ ] Implement. `MacAxBackend` is thin (AX attribute reads, Chromium
      enablement per D7); everything testable sits above the protocol.
- [ ] Full suite green; commit `conn: ax snapshot engine with grounded ref resolution`.

**Done:** `pytest tests/test_ax_snapshot.py -q` green; full suite ≥ 166 + new;
adversarial reviewer (opus, effort high, loads fable-verification) attacks ref
stability across identical siblings, the two resolution modes, TTL boundary,
and redaction bypass via `query` matching on secure values.

#### Packet G3: input executors, fakes, doctor [sonnet, effort high] [ADV]

**Files:**
- Create: `src/conn/tools/ax_input.py`
- Modify: `src/conn/tools/fake_executors.py`, `src/conn/doctor.py`
- Test: `tests/test_ax_input.py` (new)

**Interfaces (consumes):** `SnapshotStore.resolve(..., for_execution=True)`
(G1); executors match the `Executor` signature `(args, ctx) -> dict`.
**Interfaces (produces):** `click`, `type_text`, `scroll`, `hotkey`,
`focus_tab`, `menu` executors; an `InputBackend` protocol (AXPress, CGEvent
click, unicode typing in ≤20-char chunks, key chord, scroll, frontmost-window
frame query, posting-capability probe) with `MacInputBackend` and a recording
`FakeInputBackend`; fake-executor entries for all seven new tools returning
canned envelopes; `--doctor` posting-capability check per D15.

- [ ] Failing tests against fakes: every executor calls
      `resolve(for_execution=True)` itself at execution time (gate-time
      resolution does not exempt it); click prefers AXPress and REFUSES
      (`element_not_visible`) when AXPress unsupported and the visibility
      guard fails, never falling back to a blind coordinate click; type
      clicks to focus, re-verifies the focused element matches the ref before
      keystrokes, types chunked, optional Return on `submit`, refuses
      `submit_uncertain_field` per D4; text cap 2000 raises `ToolError`;
      scroll uses AXScrollToVisible with the D17 fallback rules; hotkey
      parses `cmd+shift+t`; focus_tab unique fuzzy match ≥ 0.6 (difflib ratio,
      lowercased) presses and returns `{"focused": title}`, ambiguity/zero
      match return `{"candidates": [...]}` without acting; menu walks
      segments, presses terminal item, no-match returns available titles at
      the failing level; executors refuse `accessibility_untrusted` when the
      posting probe fails; fake executors cover all seven tools (demo-mode
      regression test).
- [ ] Implement, including the doctor check (D15b) and startup
      `input_control` health field plumbing if trivially reachable from
      doctor-owned code; if it requires `app.py` edits, return the question
      instead (app.py is X-phase owned).
- [ ] Full suite green; commit `conn: grounded input executors and posting-capability doctor check`.

**Done:** named tests pass; adversarial reviewer (opus, high) attacks:
keystrokes reaching the wrong app after a mid-approval focus change, chunked
typing dropping characters, the visibility guard on occluded/offscreen/other-
display elements, and focus_tab acting on an ambiguous match.

#### Packet G2: gates, registry, config, ctx wiring [sonnet, effort medium] [ADV]

**Files:**
- Modify: `src/conn/tools/registry.py`, `src/conn/tools/risk.py`,
  `src/conn/tools/base.py`, `src/conn/tools/harness.py`,
  `src/conn/config.py`, `src/conn/__main__.py`, `src/conn/evals.py`,
  `tests/conftest.py`
- Test: `tests/test_grounded_gates.py` (new), `tests/test_risk_gates.py`
  (update for new `gate_for` return arity)

**Interfaces (consumes):** G1 store, G3 executors (by import).
**Interfaces (produces):** `gate_for` 3-tuple; `RESOLUTION_GATES` with the
gate-exception-degrades-to-refusal wrapper; registry entries for the seven
tools per the contract table (delete `computer_ax_tree`); config models
`AxCfg`, `InteractionsCfg`, `HotkeysCfg` (context/mcp configs belong to
X1/M2, not here); enriched previews per D13; `ExecutionContext.ax` wired at
every construction site (live daemon, evals, test fixtures).

- [ ] Failing tests: click gates CONFIRM by default; AUTO when bundle+role in
      `interactions.trusted`; BLOCKED with `stale_ref` when gate-time
      resolution fails; a raising resolution gate yields BLOCKED, never an
      exception out of `harness.gate` (pump-safety test); type_text BLOCKED
      `secure_field` and never downgradable via trusted or `risk_overrides`;
      scroll ACT_LOW; menu CONFIRM with trusted `AXMenuItem` downgrade;
      hotkey auto/confirm/blocked per D5 including normalization
      (`CMD+Shift+T` == `cmd+shift+t`); `app_focus_tab`/`app_menu`
      present-only allowlist guard (omitted app always permitted, named
      non-allowlisted app blocked); export-size guard per D14;
      blocked-tool config-unblock still impossible; live `__main__` path
      constructs `SnapshotStore(MacAxBackend(), cfg)` (asserted via a
      construction-seam test, not a live AX call).
- [ ] Implement; update all `gate_for` call sites and existing tests.
- [ ] Full suite green; commit `conn: grounded tool gates with resolution-time previews`.

**Done:** named tests pass; full suite green; adversarial reviewer confirms no
path where a stale or secure-field call reaches an executor, that a gating
exception cannot kill the event pump, and that `_never_runs` semantics survive
for any remaining blocked tool.

#### Packet G4: prompt, evals, scenarios [sonnet, effort medium]

**Files:**
- Modify: `src/conn/prompt.py`, `src/conn/evals.py` (eval definitions only;
  ctx wiring landed in G2)
- Create: new scenario files under `src/conn/realtime/scenarios/`
- Test: `tests/test_executors.py` (extend with eval fixtures if the eval
  harness needs them)

**Interfaces (consumes):** final tool names and refusal strings from G1-G3.

- [ ] Rewrite the prompt's Tools section: the grounded-action protocol
      (snapshot → act on ref → on `stale_ref` re-snapshot once, then ask; on
      `element_not_visible` scroll then retry once), `app_focus_tab` preferred
      for tab switches, `app_menu` preferred for app commands like close/new,
      snapshots on demand only, never guess refs. Remove disabled-tool
      wording for graduated tools. Keep the section under 30 lines: the
      schemas carry the details.
- [ ] New harness evals with matching scenario files (extend the existing
      six): stale-ref refusal round trip, secure-field refusal,
      unlisted-hotkey refusal, focus_tab ambiguity returns candidates,
      app_menu no-match returns titles.
- [ ] Full suite + `python -m conn --eval` green; commit
      `conn: grounded-action prompt and refusal evals`.

**Done:** eval run green; demo mode with a grounded-tool scenario runs with
zero real AX/CGEvent calls (asserted via fake executors); Fable reviews the
prompt diff at Gate G.

#### Gate G

Mechanical: full suite green, evals green, export-size guard green, demo-mode
zero-side-effect regression green.
Adversarial: per-packet reviews above, findings verified before acting.
Taste (Fable): prompt diff, refusal message texts, snapshot render sample.

#### STOP-G: hands-on drill (Samay), folds in deferred STOP 1

Fresh build; grant Accessibility per D15 to the identity being tested; live
daemon. Script: (1) five real v0 commands; (2) wifi-kill mid-turn with
Reconnecting visible within 1s; (3) PTT during thinking, reject pulse in
trace; (4) `--latency-report` on the session; (5) "switch to the <name> tab in
Kaku" via `app_focus_tab` (fall back to Chrome if Kaku exposes no tab
elements; file the finding either way); (6) snapshot + click a real button
behind an approval chip, waiting >10s before approving to prove the D2
execution-mode rule, and verify the chip names the element; (7) type into a
text field with `submit`; (8) "close this window" via `app_menu`; (9) attempt
a non-allowlisted hotkey, expecting a clean spoken refusal; (10) change
windows after snapshot, attempt click, and watch the `stale_ref` recovery
loop; (11) `--doctor` shows the posting-capability check passing. Proceed to
Phase X only on Samay's explicit pass.

### Phase X: context injection and session hygiene

Order: X1 → X2 (same files, sequential).

#### Packet X1: PTT-down context capture [sonnet, effort medium]

**Files:**
- Modify: `src/conn/app.py`, `src/conn/realtime/base.py`,
  `src/conn/realtime/openai_ws.py`, `src/conn/realtime/fake.py`,
  `src/conn/config.py` (ContextCfg only)
- Test: `tests/test_context_inject.py` (new)

**Interfaces (produces):** `send_system` on the adapter protocol; injection
per D12 implemented in `app.py::on_ptt_down` (capture in a thread,
`asyncio.wait_for` at `capture_budget_ms`, send routed through
`_send_or_disconnect`, trace `context_injected` / `context_skipped` with
reason). The state machine is not touched: injection is an app.py side effect
alongside the existing dispatch, never a machine event.

- [ ] Failing tests with the fake adapter and a stubbed capture fn: injected
      text format exact per D12 (app+window only by default); selection
      appears only with `include_selection = true` and never for deny_bundles
      or secure focus; slow capture (> budget) skips and traces;
      `context.inject = false` skips; capture exception skips (never breaks
      PTT); send failure lands in the disconnect path, not an unhandled task;
      the system item precedes `response.create` in the fake's recorded
      order for both slow-hold and instant-tap PTT patterns.
- [ ] Full suite green; commit `conn: local context injection at ptt-down`.

**Done:** named tests pass; a live trace shows `context_injected` and a
resolved "switch to <app>"-class command without a `computer_get_context`
round trip (verified at Gate X by trace inspection, not vibes).

#### Packet X2: snapshot pruning [sonnet, effort medium]

**Files:**
- Modify: `src/conn/app.py`, `src/conn/realtime/base.py`,
  `src/conn/realtime/openai_ws.py`, `src/conn/realtime/fake.py`
- Test: `tests/test_snapshot_pruning.py` (new)

**Interfaces (consumes):** X1's adapter shape. **Produces:** D16:
`send_tool_result_item` (client-supplied item id) used for
`computer_ax_snapshot` results, `delete_item` issued for the superseded
snapshot when a new one lands; tracking lives in app.py session state and
resets on `new_session`.

- [ ] Failing tests: after N snapshots the fake adapter records N-1 deletes
      and exactly one live snapshot item; non-snapshot tool results are never
      deleted; delete failure is non-fatal (logged, traced, loop unaffected);
      `new_session` clears tracking.
- [ ] Full suite green; commit `conn: prune superseded snapshots from session history`.

**Done:** named tests pass; guard test asserting bounded live snapshots is
green.

#### Gate X

Mechanical only (suite + one live trace). No adversarial pass: both packets
are small and their failure mode (skip / non-fatal) is the safe state. Fable
reviews the injected-text format against transcript cost only if trace shows
> 300 tokens.

### Phase M: MCP connections

Order: M1 → M2 → M3 (each consumes the previous packet's interface).

#### Packet M1: MCP client manager [sonnet, effort high]

**Files:**
- Create: `src/conn/mcp_client.py`
- Modify: `pyproject.toml` (`mcp>=1.2`) + install into the Phoenix `.venv`
- Test: `tests/test_mcp_client.py` (new)

**Interfaces (produces):** the `McpManager` / `McpToolInfo` contract above.
Schema sanitization: force `{"type":"object"}` root, drop `$ref`/`$defs`/
root-`anyOf` (replace with permissive object + description note), keep
`properties`/`required`. Description cap 200 chars. Name normalization per
D10 with collision hashing. Stdio servers launched with the config `env` map
merged over a minimal environment; env values never logged.

- [ ] Install `mcp>=1.2` into `/Users/samaydhawan/conn/.venv`; re-run the
      full baseline green BEFORE writing tests.
- [ ] Failing tests against an in-process fake MCP server (the `mcp` SDK's
      memory transport): start lists and filters to `expose`; non-exposed
      tools absent; dead server logged and skipped; slow server (exceeds
      `connect_timeout_s`) skipped identically; others still connect;
      over-`max_tools` total raises at start with a clear message; `call`
      returns text content joined as `{"content": ...}` and raises `ToolError`
      on `isError`; name normalization and 64-char hashing; description cap.
- [ ] Full suite green; commit `conn: mcp client manager`.

**Done:** named tests pass; no network use in tests.

#### Packet M2: bridge and risk mapping [sonnet, effort medium]

**Files:**
- Create: `src/conn/tools/mcp_bridge.py`
- Modify: `src/conn/config.py` (McpCfg + servers model incl. `env`)
- Test: `tests/test_mcp_bridge.py` (new)

**Interfaces (consumes):** `McpToolInfo`. **Produces:** `register_mcp_tools`
per the contract; risk per D10 including the destructive floor; Conn-generated
previews.

- [ ] Failing tests: readOnly → READ gate AUTO; default → CONFIRM;
      `risk_overrides` to auto works for non-destructive, is ignored (stays
      CONFIRM) for destructive with a log line; previews are Conn-generated
      (`<server>: <tool> <compact args>`), never server description text;
      executor is a coroutine function; config round-trips `env` without it
      appearing in any log/repr.
- [ ] Full suite green; commit `conn: mcp tools enter the registry under conn gates`.

**Done:** named tests pass.

#### Packet M3: async harness + lifecycle [opus, effort medium] [ADV]

**Files:**
- Modify: `src/conn/tools/harness.py`, `src/conn/__main__.py`,
  `src/conn/app.py` (startup/shutdown hooks only)
- Test: `tests/test_harness_async.py` (new)

**Interfaces (consumes):** M1/M2. **Produces:** D11 async-executor support;
`__main__` builds `McpManager` when `cfg.mcp.servers` non-empty, awaits
`start()` (bounded by per-server timeouts, so worst-case startup delay is
known) before the session tools export, registers bridge tools, and stops it
on daemon shutdown after adapter close; demo mode (`--demo`) never starts MCP.

- [ ] Failing tests: async executor runs and times out under `wait_for` with
      the standard envelope; sync executors unchanged; a hung MCP call times
      out at `timeout_s` without stalling the dispatch loop (assert via a
      concurrent tool completing); continuation-withholding holds across a
      slow MCP call (ledger resolves only on the real result, named test
      `test_continuation_withheld_during_slow_mcp_call`).
- [ ] Full suite green; commit `conn: async executors and mcp lifecycle`.

**Done:** named tests pass; adversarial reviewer (opus, high) attacks: MCP
call blocking the event loop, shutdown ordering (MCP stop vs adapter close),
and any window where the model could speak about an MCP outcome before the
result lands.

#### Gate M + STOP-M

Mechanical: full suite, evals. Taste (Fable): none unless friction. STOP-M
(Samay): one real MCP server of Samay's choice in config with 1-2 exposed
tools; one live voice command exercises a read tool end-to-end; one
confirm-gated MCP tool shows a chip with a Conn-generated preview.

### Phase P: docs and closure [sonnet, effort low]

#### Packet P1: documentation sweep

**Files:**
- Modify: `README.md` (env contract: new config sections, pyobjc/mcp deps,
  TCC grant identities per D15, Chromium AX flag note per D7),
  `docs/DEPLOYMENT.md` (second-Mac TCC re-grant story),
  `docs/LIVE_EVAL_CHECKLIST.md` (STOP-G items 5-11 as permanent checklist
  tasks), `docs/idea-ledger.md` (#10/#11/#15 marked taken up with pointer
  here; R1 recorded), `docs/STATE-OF-PLAY.md` (round summary),
  `docs/orchestration-ledger.md` (final token report)

- [ ] All docs updated; `python3 ~/.claude/scripts/slopcheck.py` clean on every
      touched doc; commit `conn: capability round docs`.

**Done:** slopcheck clean; STATE-OF-PLAY names this round's shipped surface and
the next deliberate deferrals.

## Out of scope, reaffirmed

Always-on listening; ambient screen watching; coordinate/screenshot clicking;
shell execution (allowlist still ships empty); Phoenix write lane; osascript in
any form; voice or keyboard approvals (pointer-only stands); iOS/companion
surfaces; full window-management verbs beyond `app_menu` reach (revisit only
on trace evidence); dictation as a separate flow (`computer_type_text` covers
it); the standalone-repo extraction (separate dedicated session, ledger #17);
Swift/island changes (UX round owns them).

## Success criteria for the round

All gates green; STOP-G and STOP-M passed by Samay live; Fable output share ≤
20% per the ledger; and the felt test: "switch to the <x> tab," "click <the
thing on screen>," "close this window," and one MCP-backed command each work
by voice, first try, inside the latency budgets, with every risky action
behind a truthful chip and zero surprise text ever leaving the machine.
