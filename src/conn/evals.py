"""Demo-mode eval runner: drives the real composition root with the scripted
adapter and canned executors, measures the loop, and writes artifacts under
data/evals/. These prove harness behavior; live model quality has its own
manual checklist in docs/.
"""

from __future__ import annotations

import asyncio
import copy
import json
import time
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from .app import ConnApp
from .config import Config
from .events import new_id
from .realtime.fake import FakeRealtimeAdapter, load_scenarios
from .state import Phase
from .tools.ax import FakeAxBackend, RawNode, SnapshotStore
from .tools.ax_input import FakeInputBackend
from .tools.base import ExecutionContext
from .tools.fake_executors import FAKE_EXECUTORS
from .tools.harness import ToolHarness
from .tools.registry import build_registry

EVAL_TASKS = Path(__file__).resolve().parents[2] / "evals" / "tasks.json"
SCENARIO_DIR = Path(__file__).resolve().parent / "realtime" / "scenarios"
FIXED_SNAPSHOT_ID = "demo1234"

_EXTRA_CASES = [
    {
        "id": "stale-ref-round-trip",
        "scenario_id": "stale-ref-round-trip",
        "input": "re-snapshot and click the Search field in this window",
        "runtime": {
            "tree": {
                "role": "AXWindow",
                "title": "Eval Window",
                "children": [
                    {"role": "AXTextField", "title": "Search", "frame": [20, 20, 240, 28]},
                    {"role": "AXButton", "title": "Send", "frame": [270, 20, 80, 28]},
                ],
            },
            "trusted": {"com.apple.TextEdit": ["AXTextField"]},
            "real_tools": ["computer_ax_snapshot", "computer_click"],
            "after_snapshot": "stale_search_ref",
        },
        "expect": {
            "tools": ["computer_ax_snapshot", "computer_click", "computer_ax_snapshot"],
            "gates": {"computer_ax_snapshot": "auto", "computer_click": "blocked"},
            "end_phase": ["done", "idle"],
            "approvals_asked": 0,
            "tool_ok": {"computer_ax_snapshot": True, "computer_click": False},
            "errors": {"computer_click": ["stale_ref: take a new snapshot"]},
        },
    },
    {
        "id": "secure-field-refusal",
        "scenario_id": "secure-field-refusal",
        "input": "type hunter2 into the password field",
        "runtime": {
            "tree": {
                "role": "AXWindow",
                "title": "Eval Window",
                "children": [
                    {"role": "AXSecureTextField", "title": "Password", "frame": [20, 20, 240, 28]},
                ],
            },
            "real_tools": ["computer_ax_snapshot"],
        },
        "expect": {
            "tools": ["computer_ax_snapshot", "computer_type_text"],
            "gates": {"computer_ax_snapshot": "auto", "computer_type_text": "blocked"},
            "end_phase": ["done", "idle"],
            "approvals_asked": 0,
            "tool_ok": {"computer_ax_snapshot": True, "computer_type_text": False},
            "errors": {"computer_type_text": ["secure_field: Conn never types into password fields"]},
        },
    },
    {
        "id": "hotkey-not-allowlisted",
        "scenario_id": "hotkey-not-allowlisted",
        "input": "press command shift p",
        "expect": {
            "tools": ["computer_hotkey"],
            "gates": {"computer_hotkey": "blocked"},
            "end_phase": ["done", "idle"],
            "approvals_asked": 0,
            "tool_ok": {"computer_hotkey": False},
            "errors": {"computer_hotkey": ["hotkey_not_allowlisted"]},
        },
    },
    {
        "id": "focus-tab-ambiguity",
        "scenario_id": "focus-tab-ambiguity",
        "input": "switch to the Alpha tab",
        "runtime": {
            "tree": {
                "role": "AXWindow",
                "title": "Tabs",
                "children": [
                    {"role": "AXTab", "title": "Alpha", "frame": [20, 20, 120, 28]},
                    {"role": "AXTab", "title": "Alphas", "frame": [150, 20, 120, 28]},
                ],
            },
            "real_tools": ["app_focus_tab"],
        },
        "expect": {
            "tools": ["app_focus_tab"],
            "gates": {"app_focus_tab": "auto"},
            "end_phase": ["done", "idle"],
            "approvals_asked": 0,
            "tool_ok": {"app_focus_tab": True},
            "data_contains": {"app_focus_tab": [{"candidates": ["Alpha", "Alphas"]}]},
        },
    },
    {
        "id": "app-menu-no-match",
        "scenario_id": "app-menu-no-match",
        "input": "use the Preferences menu",
        "runtime": {
            "tree": {"role": "AXWindow", "title": "Menus"},
            "menu_root": {
                "role": "AXMenuBar",
                "title": "Menu",
                "children": [
                    {"role": "AXMenu", "title": "File"},
                    {"role": "AXMenu", "title": "Edit"},
                    {"role": "AXMenu", "title": "View"},
                ],
            },
            "trusted": {"com.apple.TextEdit": ["AXMenuItem"]},
            "real_tools": ["app_menu"],
        },
        "expect": {
            "tools": ["app_menu"],
            "gates": {"app_menu": "auto"},
            "end_phase": ["done", "idle"],
            "approvals_asked": 0,
            "tool_ok": {"app_menu": True},
            "data_contains": {"app_menu": [{"candidates": ["File", "Edit", "View"]}]},
        },
    },
]


def _raw(spec: dict | None = None) -> RawNode:
    spec = spec or {}
    return RawNode(
        role=spec.get("role", "AXWindow"),
        subrole=spec.get("subrole", ""),
        title=spec.get("title", ""),
        value=spec.get("value"),
        enabled=spec.get("enabled", True),
        focused=spec.get("focused", False),
        secure_hints=tuple(spec.get("secure_hints", ())),
        frame=tuple(float(part) for part in spec.get("frame", (0.0, 0.0, 0.0, 0.0))),
        children=tuple(_raw(child) for child in spec.get("children", [])),
    )


def _eval_store(cfg: Config, tree: RawNode | None = None, *, bundle_id: str = "com.apple.TextEdit", pid: int = 42) -> SnapshotStore:
    default_tree = RawNode(
        role="AXWindow",
        title="Eval Window",
        children=(
            RawNode(role="AXButton", title="Send"),
            RawNode(role="AXTextField", title="Body"),
            RawNode(role="AXScrollArea", title="Results", children=(RawNode(role="AXStaticText", title="Target"),)),
        ),
    )
    return SnapshotStore(FakeAxBackend(bundle_id, pid, tree or default_tree), cfg)


def load_eval_cases() -> list[dict]:
    spec = json.loads(EVAL_TASKS.read_text())
    return [*spec["cases"], *copy.deepcopy(_EXTRA_CASES)]


def _load_scenario(case: dict) -> dict:
    scenario_id = case.get("scenario_id")
    scenarios = load_scenarios(SCENARIO_DIR)
    if scenario_id:
        for scenario in scenarios:
            if scenario.get("id") == scenario_id:
                return _replace_placeholders(copy.deepcopy(scenario))
        raise KeyError(f"unknown scenario: {scenario_id}")
    for scenario in scenarios:
        if scenario.get("spoken") == case["input"]:
            return _replace_placeholders(copy.deepcopy(scenario))
    lowered = case["input"].lower()
    for scenario in scenarios:
        spoken = str(scenario.get("spoken", "")).lower()
        if spoken and spoken == lowered:
            return _replace_placeholders(copy.deepcopy(scenario))
    raise KeyError(f"no scenario for input: {case['input']}")


def _replace_placeholders(value):
    if isinstance(value, dict):
        return {key: _replace_placeholders(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_replace_placeholders(item) for item in value]
    if value == "__SNAPSHOT_ID__":
        return FIXED_SNAPSHOT_ID
    return value


def _fixed_snapshot_executor(after_snapshot=None):
    def run(args: dict, ctx: ExecutionContext) -> dict:
        with patch("conn.tools.ax.secrets.token_hex", return_value=FIXED_SNAPSHOT_ID):
            snapshot = ctx.ax.take(args.get("query"))
        if after_snapshot is not None:
            after_snapshot(ctx)
        return {"snapshot_id": snapshot.snapshot_id, "render": snapshot.render(args.get("query"))}

    return run


def _apply_post_snapshot(name: str, ctx: ExecutionContext) -> None:
    backend = ctx.ax.backend
    if name == "stale_search_ref":
        backend.root.children = (
            RawNode(role="AXButton", title="Send", frame=(270.0, 20.0, 80.0, 28.0)),
            RawNode(role="AXTextField", title="Search", frame=(20.0, 20.0, 240.0, 28.0)),
        )
        backend.window_title = backend.root.title


def _build_runtime(case: dict, cfg: Config) -> tuple[ExecutionContext, dict[str, object]]:
    runtime = case.get("runtime", {})
    cfg.interactions.trusted = runtime.get("trusted", {})
    tree = _raw(runtime.get("tree")) if runtime.get("tree") else None
    bundle_id = runtime.get("bundle_id", "com.apple.TextEdit")
    store = _eval_store(cfg, tree, bundle_id=bundle_id, pid=runtime.get("pid", 42))
    backend = store.backend
    if runtime.get("menu_root"):
        backend.menu_root = _raw(runtime["menu_root"])
    ctx = ExecutionContext(cfg=cfg, screenshot_dir=cfg.data_dir / "screenshots" / new_id("eval"), ax=store)
    ctx.input_backend = FakeInputBackend()

    executors = dict(FAKE_EXECUTORS)
    registry = build_registry()
    real_tools = set(runtime.get("real_tools", []))
    for tool_name in real_tools:
        executors[tool_name] = registry[tool_name].executor
    if "computer_ax_snapshot" in real_tools:
        hook_name = runtime.get("after_snapshot")
        after_snapshot = (lambda live_ctx: _apply_post_snapshot(hook_name, live_ctx)) if hook_name else None
        executors["computer_ax_snapshot"] = _fixed_snapshot_executor(after_snapshot)
    return ctx, executors


def _contains(actual, expected) -> bool:
    if isinstance(expected, dict):
        if not isinstance(actual, dict):
            return False
        return all(key in actual and _contains(actual[key], value) for key, value in expected.items())
    if isinstance(expected, list):
        if not isinstance(actual, list):
            return False
        return all(item in actual for item in expected)
    return actual == expected


async def _run_case(case: dict, cfg: Config) -> dict:
    cfg = cfg.model_copy(deep=True)
    cfg.risk_overrides.update(case.get("risk_overrides", {}))
    ctx, executors = _build_runtime(case, cfg)
    harness = ToolHarness(build_registry(), cfg, ctx, executors=executors)
    app = ConnApp(cfg, FakeRealtimeAdapter([_load_scenario(case)], pace_s=0.005), harness)

    first_feedback_ms: list[float] = []
    t_input = 0.0

    def watch(msg: dict) -> None:
        if not first_feedback_ms and msg.get("type") in ("transcript_delta", "state") and t_input and msg.get("phase") != "idle":
            first_feedback_ms.append((time.monotonic() - t_input) * 1000)

    app.publisher = watch
    await app.start()

    t_start = time.monotonic()
    t_input = time.monotonic()
    await app.on_text(case["input"])

    async def settle():
        while app.machine.phase not in (Phase.DONE, Phase.IDLE, Phase.BUDGET_HOLD):
            if app.machine.phase is Phase.AWAITING_APPROVAL and "approve" in case:
                call_id = next(iter(app.approvals.pending), None)
                if call_id:
                    await app.on_approval(call_id, approved=case["approve"])
            await asyncio.sleep(0.01)

    try:
        await asyncio.wait_for(settle(), timeout=5.0)
        timed_out = False
    except TimeoutError:
        timed_out = True
    e2e_ms = (time.monotonic() - t_start) * 1000
    await app.stop()

    trace = app.trace.read()
    proposed = [event for event in trace if event["kind"] == "tool_proposed"]
    result_events = {event["call_id"]: event for event in trace if event["kind"] == "tool_result"}
    results = {}
    for call_id, event in result_events.items():
        try:
            results[call_id] = json.loads(event["output"])
        except json.JSONDecodeError:
            continue
    sent_results = {event["call_id"]: event for event in trace if event["kind"] == "tool_result_sent"}
    approvals = [event for event in trace if event["kind"] == "approval_asked"]

    expect = case["expect"]
    failures: list[str] = []
    got_tools = [proposal["name"] for proposal in proposed]
    if got_tools != expect.get("tools", got_tools):
        failures.append(f"tools {got_tools} != {expect['tools']}")
    for name, want_gate in expect.get("gates", {}).items():
        gates = [proposal["gate"] for proposal in proposed if proposal["name"] == name]
        if want_gate not in gates:
            failures.append(f"{name} gate {gates} != {want_gate}")
    if len(approvals) != expect.get("approvals_asked", len(approvals)):
        failures.append(f"approvals {len(approvals)} != {expect['approvals_asked']}")
    for name, want_ok in expect.get("tool_ok", {}).items():
        call_ids = [proposal["call_id"] for proposal in proposed if proposal["name"] == name]
        oks = [sent_results[call_id]["ok"] for call_id in call_ids if call_id in sent_results]
        if want_ok not in oks:
            failures.append(f"{name} ok {oks} != {want_ok}")
    for name, want_errors in expect.get("errors", {}).items():
        call_ids = [proposal["call_id"] for proposal in proposed if proposal["name"] == name]
        got_errors = []
        for call_id in call_ids:
            if call_id in results and not results[call_id].get("ok"):
                got_errors.append(results[call_id].get("error"))
                continue
            proposal = next((item for item in proposed if item["call_id"] == call_id), None)
            if proposal and proposal.get("gate") == "blocked":
                got_errors.append(proposal.get("block_reason"))
        for want_error in want_errors:
            if want_error not in got_errors:
                failures.append(f"{name} errors {got_errors} missing {want_error}")
    for name, wanted_items in expect.get("data_contains", {}).items():
        call_ids = [proposal["call_id"] for proposal in proposed if proposal["name"] == name]
        actual_payloads = [results[call_id].get("data") for call_id in call_ids if call_id in results and results[call_id].get("ok")]
        for wanted in wanted_items:
            if not any(_contains(payload, wanted) for payload in actual_payloads):
                failures.append(f"{name} data {actual_payloads} missing {wanted}")
    want_kinds = expect.get("trace_kinds")
    if want_kinds:
        got_kinds = {event["kind"] for event in trace}
        missing = [kind for kind in want_kinds if kind not in got_kinds]
        if missing:
            failures.append(f"missing trace kinds {missing}")
    if app.machine.phase.value not in expect.get("end_phase", [app.machine.phase.value]):
        failures.append(f"end phase {app.machine.phase.value} not in {expect['end_phase']}")
    if timed_out:
        failures.append("timed out before settling")

    return {
        "id": case["id"],
        "input": case["input"],
        "passed": not failures,
        "failures": failures,
        "tools": got_tools,
        "tool_data": {
            proposal["name"]: [
                results[call_id]["data"]
                for call_id in [item["call_id"] for item in proposed if item["name"] == proposal["name"]]
                if call_id in results and results[call_id].get("ok")
            ]
            for proposal in proposed
        },
        "approvals_asked": len(approvals),
        "first_feedback_ms": round(first_feedback_ms[0], 1) if first_feedback_ms else None,
        "e2e_ms": round(e2e_ms, 1),
        "estimated_usd": app.cost.receipt()["estimated_usd"],
        "trace_path": str(app.trace.path),
    }


def run_evals(cfg: Config) -> int:
    async def run_all():
        out = []
        for case in load_eval_cases():
            out.append(await _run_case(case, cfg))
        return out

    results = asyncio.run(run_all())

    day = datetime.now().strftime("%Y-%m-%d")
    out_dir = cfg.data_dir / "evals" / day
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"results-{int(time.time())}.json"
    out_path.write_text(json.dumps({"mode": "demo", "results": results}, indent=2))

    width = max(len(result["id"]) for result in results)
    print(f"conn evals (demo mode) -> {out_path}")
    for result in results:
        status = "pass" if result["passed"] else "FAIL"
        ff = f"{result['first_feedback_ms']}ms" if result["first_feedback_ms"] is not None else "n/a"
        print(f"  {status:>4}  {result['id']:<{width}}  first-feedback {ff:>8}  e2e {result['e2e_ms']:>7.1f}ms  tools {len(result['tools'])}  ~${result['estimated_usd']:.4f}")
        for failure in result["failures"]:
            print(f"        {failure}")
    failed = [result for result in results if not result["passed"]]
    print(f"{len(results) - len(failed)}/{len(results)} passed")
    return 1 if failed else 0
