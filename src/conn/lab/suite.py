from __future__ import annotations

from datetime import date
import json
import math
from pathlib import Path
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


def compare_host_snapshots(before: dict, after: dict) -> list[str]:
    return sorted(
        key for key in _HOST_KEYS
        if before.get(key) != after.get(key)
    )


def run_smoke_suite(
    repo_root: Path,
    *,
    runs: int = 20,
    run_prefix: str = "l7-smoke",
    scenario_runner: Callable | None = None,
    host_probe: Callable[[], dict] | None = None,
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
    if host_probe is None:
        from .host import capture_host_snapshot
        host_probe = capture_host_snapshot

    before = host_probe()
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
        reason = failure or "incomplete"
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
