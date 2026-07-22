from __future__ import annotations

from datetime import date
from dataclasses import dataclass
import json
import math
from pathlib import Path
import re
import time
from typing import Callable

from conn.actions import ActionOutcome, uncertain_failure_receipt
from conn.events import (
    ExecTool,
    Gate,
    PttDown,
    PttUp,
    ResponseDone,
    ToolCall,
    ToolFinished,
    ToolProposed,
)
from conn.navigation import NavigationEffect, NavigationLease
from conn.state import CallStatus, SessionStateMachine


_HOST_KEYS = (
    "frontmost_bundle",
    "pointer",
    "clipboard_sha256",
    "applications_sha256",
    "personal_data_sha256",
)
_TIMING_KEYS = (
    "clone_ms",
    "boot_ms",
    "install_ms",
    "scenario_ms",
    "export_ms",
    "cleanup_ms",
    "total_ms",
)
_V1_JOBS = (
    "app_window_selection",
    "collection_selection",
    "control_activation",
    "document_history",
    "field_text_entry",
    "menus_overlays",
    "multi_step",
    "named_scroll",
    "visual_fallback",
)


@dataclass(frozen=True, slots=True)
class BreadthCase:
    command_id: str
    scenario_id: str | None
    expected_effect: str
    surface: str | None = None
    job: str | None = None


_BREADTH_CASES = {
    "finder-open": ("finder-open", "frontmost_bundle"),
    "finder-select-folder": ("finder-select", "row_selected"),
    "finder-search": ("finder-search", "finder_search_value"),
    "calendar-open": ("calendar-open", "frontmost_bundle"),
    "calendar-today": ("calendar-today", "current_month_visible"),
    "calendar-next": ("calendar-next", "next_month_visible"),
    "preview-open": ("preview-open", "frontmost_bundle"),
    "preview-next-page": ("preview-next-page", "page_2_visible"),
    "preview-scroll-heading": ("preview-scroll", "appendix_visible"),
    "safari-url": ("safari-local", "page_loaded"),
    "safari-new-tab": ("safari-tab", "page_hidden"),
    "safari-focus-tab": ("safari-focus", "page_hidden"),
    "firefox-url": ("firefox-local", "page_loaded"),
    "firefox-play": ("firefox-visual", "pointer_play"),
    "firefox-space": ("firefox-space", "space_play"),
    "notes-create": ("notes-create", "notes_store_count_delta"),
    "notes-select-next": ("notes-select", "notes_selected_object_changed"),
    "notes-type": ("notes-type", "notes_store_title_replaced"),
    "terminal-menu": ("terminal-window", "window_count_delta"),
    "fixture-composed": ("fixture-composed", "row_selected"),
}


def breadth_cases(repo_root: Path) -> tuple[BreadthCase, ...]:
    path = repo_root.resolve(strict=True) / "lab" / "v1-command-corpus.json"
    try:
        payload = json.loads(path.read_text())
        commands = payload["commands"]
    except (OSError, ValueError, KeyError, TypeError) as error:
        raise RuntimeError("breadth_corpus_invalid") from error
    if (
        payload.get("schema_version") != 1
        or payload.get("frozen") is not True
        or not isinstance(commands, list)
        or len(commands) != 20
    ):
        raise RuntimeError("breadth_corpus_invalid")
    ids = [item.get("id") for item in commands if isinstance(item, dict)]
    if len(ids) != 20 or len(set(ids)) != 20 or set(ids) != set(_BREADTH_CASES):
        raise RuntimeError("breadth_corpus_invalid")
    cases = []
    for item in commands:
        command_id = item["id"]
        surface = item.get("surface")
        job = item.get("job")
        if (
            not isinstance(surface, str)
            or not isinstance(job, str)
            or not re.fullmatch(r"[a-z][a-z0-9_]{0,79}", surface)
            or not re.fullmatch(r"[a-z][a-z0-9_]{0,79}", job)
        ):
            raise RuntimeError("breadth_corpus_invalid")
        cases.append(BreadthCase(
            command_id,
            *_BREADTH_CASES[command_id],
            surface=surface,
            job=job,
        ))
    return tuple(cases)


def _supporting_manifest(repo_root: Path) -> dict:
    path = repo_root.resolve(strict=True) / "lab" / "v1-supporting-coverage.json"
    try:
        payload = json.loads(path.read_text())
    except (OSError, ValueError) as error:
        raise RuntimeError("supporting_coverage_invalid") from error
    if (
        not isinstance(payload, dict)
        or payload.get("schema_version") != 1
        or payload.get("frozen") is not True
        or not isinstance(payload.get("successes"), list)
        or len(payload["successes"]) != 9
        or not isinstance(payload.get("refusals"), list)
        or len(payload["refusals"]) != len(_V1_JOBS)
    ):
        raise RuntimeError("supporting_coverage_invalid")
    return payload


def supporting_cases(repo_root: Path) -> tuple[BreadthCase, ...]:
    repo_root = repo_root.resolve(strict=True)
    payload = _supporting_manifest(repo_root)
    from .catalog import load_catalog

    catalog = load_catalog(repo_root)
    cases = []
    ids: set[str] = set()
    for item in payload["successes"]:
        if not isinstance(item, dict):
            raise RuntimeError("supporting_coverage_invalid")
        values = tuple(item.get(key) for key in (
            "id", "scenario", "effect", "surface", "job",
        ))
        if any(
            not isinstance(value, str)
            or not re.fullmatch(r"[a-z][a-z0-9_-]{0,79}", value)
            for value in values
        ):
            raise RuntimeError("supporting_coverage_invalid")
        case_id, scenario, effect, surface, job = values
        if case_id in ids or scenario not in catalog or job not in _V1_JOBS:
            raise RuntimeError("supporting_coverage_invalid")
        ids.add(case_id)
        cases.append(BreadthCase(
            case_id,
            scenario,
            effect,
            surface=surface,
            job=job,
        ))
    return tuple(cases)


def supporting_refusals(repo_root: Path) -> tuple[dict, ...]:
    repo_root = repo_root.resolve(strict=True)
    payload = _supporting_manifest(repo_root)
    refusals = []
    jobs: set[str] = set()
    for item in payload["refusals"]:
        if not isinstance(item, dict):
            raise RuntimeError("supporting_coverage_invalid")
        job = item.get("job")
        test_id = item.get("test_id")
        source = item.get("source")
        if (
            job not in _V1_JOBS
            or job in jobs
            or not isinstance(test_id, str)
            or not re.fullmatch(r"(?:python|swift):[A-Za-z0-9_]{1,120}", test_id)
            or not isinstance(source, str)
            or not re.fullmatch(r"(?:tests|macos/Tests)/[A-Za-z0-9_./-]{1,180}", source)
        ):
            raise RuntimeError("supporting_coverage_invalid")
        source_path = (repo_root / source).resolve(strict=True)
        if not source_path.is_relative_to(repo_root):
            raise RuntimeError("supporting_coverage_invalid")
        test_name = test_id.split(":", 1)[1]
        source_validated = test_name in source_path.read_text()
        if not source_validated:
            raise RuntimeError("supporting_coverage_invalid")
        jobs.add(job)
        refusals.append({
            "job": job,
            "test_id": test_id,
            "source": source,
            "source_validated": True,
        })
    if jobs != set(_V1_JOBS):
        raise RuntimeError("supporting_coverage_invalid")
    return tuple(refusals)


def run_breadth_suite(
    repo_root: Path,
    *,
    cases: tuple[BreadthCase, ...] | None = None,
    scenario_runner: Callable | None = None,
    host_probe: Callable[[], dict] | None = None,
    host_pause: Callable[[float], None] | None = None,
    run_prefix: str = "v1-breadth",
    required_jobs: tuple[str, ...] | None = None,
) -> dict:
    repo_root = repo_root.resolve(strict=True)
    production_cases = cases is None
    selected = cases or breadth_cases(repo_root)
    if required_jobs is None and production_cases:
        required_jobs = tuple(sorted({case.job for case in selected if case.job}))
    if not selected or len(selected) > 20:
        raise ValueError("breadth cases must be in [1, 20]")
    if scenario_runner is None:
        from .cli import run_scenario
        scenario_runner = run_scenario
    production_host_probe = host_probe is None
    if production_host_probe:
        from .host import capture_host_snapshot
        host_probe = capture_host_snapshot
    pause = host_pause or (time.sleep if production_host_probe else lambda _: None)
    before = _wait_for_quiet_host(host_probe, pause)
    rows = []
    for index, case in enumerate(selected, start=1):
        if case.scenario_id is None:
            rows.append({
                "command_id": case.command_id,
                "scenario_id": None,
                "completed": False,
                "reason": "scenario_missing",
                "surface": case.surface,
                "job": case.job,
            })
            continue
        run_id = f"{run_prefix}-{index:02d}"
        try:
            result = scenario_runner(
                repo_root,
                scenario=case.scenario_id,
                mode="scripted",
                run_id=run_id,
            )
        except (RuntimeError, OSError) as error:
            message = str(error)
            safe_error = (
                message
                if re.fullmatch(r"[a-z0-9_.:-]{1,160}", message)
                else type(error).__name__
            )
            rows.append({
                "command_id": case.command_id,
                "scenario_id": case.scenario_id,
                "run_id": run_id,
                "completed": False,
                "reason": "scenario_error",
                "error": safe_error,
                "surface": case.surface,
                "job": case.job,
            })
            continue
        receipt = result.get("machine_receipt") or {}
        oracle = result.get("independent_oracle") or {}
        reason = None
        if result.get("passed") is not True or result.get("contract_passed") is not True:
            reason = "scenario_contract_failed"
        elif receipt.get("outcome") not in {"verified", "dispatch_only"}:
            reason = "receipt_not_completed"
        elif oracle.get("verdict") != "matched":
            reason = "oracle_not_matched"
        elif oracle.get("effect") != case.expected_effect:
            reason = "oracle_effect_mismatch"
        elif (
            not isinstance(result.get("dispatch_count"), int)
            or result["dispatch_count"] < 1
        ):
            reason = "dispatch_missing"
        rows.append({
            "command_id": case.command_id,
            "scenario_id": case.scenario_id,
            "run_id": run_id,
            "completed": reason is None,
            "reason": reason,
            "receipt_outcome": receipt.get("outcome"),
            "oracle_verdict": oracle.get("verdict"),
            "oracle_effect": oracle.get("effect"),
            "dispatch_count": result.get("dispatch_count"),
            "surface": case.surface,
            "job": case.job,
        })
    after = host_probe()
    completed = sum(row["completed"] for row in rows)
    rate = completed / len(selected)
    safe_replans_attempted = 0
    after_safe_replan_rate = rate
    host_changes = compare_host_snapshots(before, after)
    coverage = {
        job: sorted({
            row["surface"]
            for row in rows
            if row.get("completed") is True
            and row.get("job") == job
            and isinstance(row.get("surface"), str)
        })
        for job in (required_jobs or ())
    }
    coverage_passed = all(len(surfaces) >= 3 for surfaces in coverage.values())
    summary = {
        "commands": len(selected),
        "completed": completed,
        "first_try_rate": rate,
        "safe_replans_attempted": safe_replans_attempted,
        "after_safe_replan_rate": after_safe_replan_rate,
        "primitive_coverage": coverage,
        "coverage_passed": coverage_passed,
        "passed": (
            rate >= 0.95
            and after_safe_replan_rate >= 0.99
            and coverage_passed
            and not host_changes
        ),
        "host_changes": host_changes,
        "host_snapshot_stable": not host_changes,
        "rows": rows,
    }
    output_dir = repo_root / "data" / "lab-runs" / date.today().isoformat()
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / f"{run_prefix}-summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n"
    )
    return summary


def run_v1_breadth_gate(
    repo_root: Path,
    *,
    core_cases: tuple[BreadthCase, ...] | None = None,
    support_cases: tuple[BreadthCase, ...] | None = None,
    refusal_evidence: tuple[dict, ...] | None = None,
    required_jobs: tuple[str, ...] = _V1_JOBS,
    scenario_runner: Callable | None = None,
    host_probe: Callable[[], dict] | None = None,
    run_prefix: str = "v1-breadth",
) -> dict:
    repo_root = repo_root.resolve(strict=True)
    core = breadth_cases(repo_root) if core_cases is None else core_cases
    support = (
        supporting_cases(repo_root) if support_cases is None else support_cases
    )
    refusals = (
        supporting_refusals(repo_root)
        if refusal_evidence is None
        else refusal_evidence
    )
    core_summary = run_breadth_suite(
        repo_root,
        cases=core,
        scenario_runner=scenario_runner,
        host_probe=host_probe,
        run_prefix=f"{run_prefix}-core",
        required_jobs=(),
    )
    support_summary = run_breadth_suite(
        repo_root,
        cases=support,
        scenario_runner=scenario_runner,
        host_probe=host_probe,
        run_prefix=f"{run_prefix}-support",
        required_jobs=(),
    )
    rows = [*core_summary["rows"], *support_summary["rows"]]
    coverage = {
        job: sorted({
            row["surface"]
            for row in rows
            if row.get("completed") is True
            and row.get("job") == job
            and isinstance(row.get("surface"), str)
        })
        for job in required_jobs
    }
    coverage_passed = all(len(surfaces) >= 3 for surfaces in coverage.values())
    refusal_jobs = {
        item.get("job")
        for item in refusals
        if item.get("source_validated") is True
    }
    adversarial_coverage_passed = refusal_jobs == set(required_jobs)
    completed = sum(row["completed"] for row in rows)
    commands = len(rows)
    host_changes = sorted(set(
        core_summary["host_changes"] + support_summary["host_changes"]
    ))
    summary = {
        "commands": commands,
        "completed": completed,
        "first_try_rate": completed / commands,
        "after_safe_replan_rate": completed / commands,
        "safe_replans_attempted": 0,
        "primitive_coverage": coverage,
        "coverage_passed": coverage_passed,
        "adversarial_coverage": list(refusals),
        "adversarial_coverage_passed": adversarial_coverage_passed,
        "host_changes": host_changes,
        "host_snapshot_stable": not host_changes,
        "core": core_summary,
        "supporting": support_summary,
        "passed": (
            core_summary["passed"]
            and support_summary["passed"]
            and coverage_passed
            and adversarial_coverage_passed
            and not host_changes
        ),
    }
    output_dir = repo_root / "data" / "lab-runs" / date.today().isoformat()
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / f"{run_prefix}-summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n"
    )
    return summary


def compare_host_snapshots(before: dict, after: dict) -> list[str]:
    return sorted(
        key for key in _HOST_KEYS
        if before.get(key) != after.get(key)
    )


def _wait_for_quiet_host(
    host_probe: Callable[[], dict],
    pause: Callable[[float], None],
) -> dict:
    current = host_probe()
    unchanged = 1
    for _ in range(30):
        pause(0.5)
        candidate = host_probe()
        if compare_host_snapshots(current, candidate):
            unchanged = 1
        else:
            unchanged += 1
            if unchanged == 3:
                return candidate
        current = candidate
    raise RuntimeError("host_not_quiet")


def run_smoke_suite(
    repo_root: Path,
    *,
    runs: int = 20,
    run_prefix: str = "l7-smoke",
    scenario_runner: Callable | None = None,
    host_probe: Callable[[], dict] | None = None,
    host_pause: Callable[[float], None] | None = None,
) -> dict:
    if not 1 <= runs <= 20:
        raise ValueError("smoke runs must be in [1, 20]")
    if (
        not run_prefix
        or len(run_prefix) > 40
        or any(
            not (character.islower() or character.isdigit() or character == "-")
            for character in run_prefix
        )
    ):
        raise ValueError("smoke run prefix is invalid")
    repo_root = repo_root.resolve(strict=True)
    if scenario_runner is None:
        from .scenario import run_l3
        scenario_runner = run_l3
    production_host_probe = host_probe is None
    if production_host_probe:
        from .host import capture_host_snapshot
        host_probe = capture_host_snapshot
    pause = host_pause or (time.sleep if production_host_probe else lambda _: None)

    before = _wait_for_quiet_host(host_probe, pause)
    results = []
    timing_rows = []
    failure = None
    run_date = date.today().isoformat()
    for index in range(1, runs + 1):
        run_id = f"{run_prefix}-{index:02d}"
        result = scenario_runner(repo_root, run_id=run_id)
        artifact_dir = (
            repo_root / "data" / "lab-runs" / run_date / run_id
        )
        timings = _read_timings(artifact_dir)
        receipt = result.get("machine_receipt") or {}
        oracle = result.get("independent_oracle") or {}
        passed = (
            result.get("passed") is True
            and receipt.get("outcome") == "verified"
            and oracle.get("verdict") == "matched"
            and timings["total_ms"] < 180_000
        )
        row = {
            "run_id": run_id,
            "passed": passed,
            "receipt_outcome": receipt.get("outcome"),
            "oracle_verdict": oracle.get("verdict"),
            "timings_ms": timings,
        }
        results.append(row)
        timing_rows.append(timings)
        if not passed:
            failure = run_id
            break

    after = host_probe()
    host_changes = compare_host_snapshots(before, after)
    summary = {
        "runs_requested": runs,
        "runs_completed": len(results),
        "passed_runs": sum(row["passed"] for row in results),
        "passed": (
            failure is None
            and len(results) == runs
            and not host_changes
        ),
        "failed_run": failure,
        "host_before": before,
        "host_after": after,
        "host_changes": host_changes,
        "host_snapshot_stable": not host_changes,
        "timings_ms": _timing_summary(timing_rows),
        "runs": results,
    }
    summary_dir = repo_root / "data" / "lab-runs" / run_date
    summary_dir.mkdir(parents=True, exist_ok=True)
    (summary_dir / f"{run_prefix}-summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n"
    )
    if not summary["passed"]:
        reason = failure or ("host_changed" if host_changes else "incomplete")
        raise RuntimeError(f"smoke_run_failed:{reason}")
    return summary


def run_scripted_matrix(*, iterations: int = 100) -> dict:
    if not 1 <= iterations <= 100:
        raise ValueError("scripted iterations must be in [1, 100]")
    failures = {
        "wrong_targets": 0,
        "false_verified": 0,
        "stale_dispatches": 0,
        "retries_after_possible_dispatch": 0,
    }
    passed = 0
    for index in range(iterations):
        iteration = _scripted_iteration(index)
        for key, failed in iteration.items():
            failures[key] += int(failed)
        if not any(iteration.values()):
            passed += 1
    return {
        "iterations": iterations,
        "passed": passed,
        **failures,
    }


def _scripted_iteration(index: int) -> dict[str, bool]:
    wrong_target_machine = _machine()
    wrong_call = _mutation(f"wrong-{index}")
    wrong_target_machine.handle(ToolProposed(wrong_call))
    running = wrong_target_machine.ledger[wrong_call.call_id].call
    wrong_completion = wrong_target_machine.handle(ToolFinished(
        call_id=wrong_call.call_id,
        ok=True,
        output=_invalid_verified_output(),
        action_outcome=ActionOutcome.VERIFIED,
        execution_id=(running.execution_id or 0) + 1,
    ))
    wrong_target = bool(wrong_completion) or (
        wrong_target_machine.ledger[wrong_call.call_id].status
        is not CallStatus.RUNNING
    )

    evidence_machine = _machine()
    evidence_call = _mutation(f"evidence-{index}")
    evidence_machine.handle(ToolProposed(evidence_call))
    evidence_running = evidence_machine.ledger[evidence_call.call_id].call
    evidence_machine.handle(ToolFinished(
        call_id=evidence_call.call_id,
        ok=True,
        output=_invalid_verified_output(),
        action_outcome=ActionOutcome.VERIFIED,
        execution_id=evidence_running.execution_id,
    ))
    false_verified = (
        evidence_machine.ledger[evidence_call.call_id].status
        is CallStatus.VERIFIED
    )

    lease = NavigationLease(f"session-{index}")
    lease.bind_connection("signed-app")
    lease.grant(f"session-{index}", "signed-app")
    stale_generation = lease.generation
    lease.revoke(f"session-{index}", "signed-app")
    stale_dispatch = lease.allows(
        NavigationEffect.REVERSIBLE_NAVIGATION,
        stale_generation,
    )

    retry_machine = _machine()
    first = _mutation(f"possible-{index}")
    retry_machine.handle(ToolProposed(first))
    first_running = retry_machine.ledger[first.call_id].call
    receipt = uncertain_failure_receipt(
        target="current target",
        strategy="native_bridge",
        duration_ms=1,
        summary="bridge timeout",
    )
    retry_machine.handle(ToolFinished(
        call_id=first.call_id,
        ok=False,
        output=json.dumps(receipt.as_dict()),
        action_outcome=receipt.outcome,
        execution_id=first_running.execution_id,
    ))
    retry_machine.handle(ResponseDone(had_tool_calls=True))
    retry_commands = retry_machine.handle(ToolProposed(
        _mutation(f"retry-{index}", kind="window")
    ))
    retried = any(
        isinstance(command, ExecTool)
        for command in retry_commands
    )
    return {
        "wrong_targets": wrong_target,
        "false_verified": false_verified,
        "stale_dispatches": stale_dispatch,
        "retries_after_possible_dispatch": retried,
    }


def _machine() -> SessionStateMachine:
    machine = SessionStateMachine(
        computer_mutations=frozenset({"computer_create"})
    )
    machine.handle(PttDown(ts_ms=1_000))
    machine.handle(PttUp(ts_ms=2_000, voiced=True))
    return machine


def _mutation(call_id: str, *, kind: str = "tab") -> ToolCall:
    return ToolCall(
        call_id=call_id,
        name="computer_create",
        arguments={"kind": kind},
        gate=Gate.AUTO,
        preview=f"Create a new {kind}",
    )


def _invalid_verified_output() -> str:
    return json.dumps({
        "outcome": "verified",
        "ok": True,
        "dispatch_state": "dispatched",
        "strategy": "ax_press",
        "lane": "semantic",
        "target": "current target",
        "effect": "changed",
        "evidence": [],
        "retry_safe": False,
        "duration_ms": 1,
        "reason_code": None,
    })


def _read_timings(artifact_dir: Path) -> dict[str, int]:
    values = {}
    for filename in ("runner-timings.json", "scenario-timings.json"):
        try:
            payload = json.loads((artifact_dir / filename).read_text())
        except (OSError, ValueError) as error:
            raise RuntimeError(f"smoke_timing_missing:{filename}") from error
        if not isinstance(payload, dict):
            raise RuntimeError(f"smoke_timing_invalid:{filename}")
        values.update(payload)
    if set(values) != set(_TIMING_KEYS):
        raise RuntimeError("smoke_timing_invalid:keys")
    if any(
        not isinstance(value, int) or value < 0
        for value in values.values()
    ):
        raise RuntimeError("smoke_timing_invalid:value")
    return values


def _timing_summary(rows: list[dict[str, int]]) -> dict:
    if not rows:
        return {}
    result = {}
    for key in _TIMING_KEYS:
        values = sorted(row[key] for row in rows)
        result[key] = {
            "min": values[0],
            "p50": values[(len(values) - 1) // 2],
            "p95": values[max(0, math.ceil(len(values) * 0.95) - 1)],
            "max": values[-1],
        }
    return result
