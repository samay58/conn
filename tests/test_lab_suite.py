from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest

from conn.lab.suite import (
    BreadthCase,
    breadth_cases,
    compare_host_snapshots,
    run_breadth_suite,
    run_scripted_matrix,
    run_smoke_suite,
    run_v1_breadth_gate,
    supporting_cases,
    supporting_refusals,
)


ROOT = Path(__file__).resolve().parents[1]


def test_breadth_cases_keep_all_twenty_frozen_commands() -> None:
    cases = breadth_cases(ROOT)

    assert len(cases) == 20
    assert {case.command_id for case in cases} == {
        item["id"]
        for item in json.loads((ROOT / "lab/v1-command-corpus.json").read_text())[
            "commands"
        ]
    }
    preview = next(case for case in cases if case.command_id == "preview-scroll-heading")
    assert preview.scenario_id == "preview-scroll"
    assert preview.surface == "preview"
    assert preview.job == "named_scroll"


def test_supporting_cases_fill_the_fixed_v1_denominator() -> None:
    cases = supporting_cases(ROOT)
    refusals = supporting_refusals(ROOT)

    assert len(cases) == 9
    assert {case.job for case in cases} == {
        "control_activation",
        "document_history",
        "field_text_entry",
        "multi_step",
        "named_scroll",
        "visual_fallback",
    }
    assert {item["job"] for item in refusals} == {
        "app_window_selection",
        "collection_selection",
        "control_activation",
        "document_history",
        "field_text_entry",
        "menus_overlays",
        "multi_step",
        "named_scroll",
        "visual_fallback",
    }
    assert all(item["source_validated"] for item in refusals)


def test_v1_breadth_gate_combines_core_and_supporting_surface_proof(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    (repo / "data/lab-runs").mkdir(parents=True)
    core = tuple(
        BreadthCase(
            f"core-{job}-{surface}",
            f"core-{job}-{surface}",
            "done",
            surface=surface,
            job=job,
        )
        for job in ("select", "visual")
        for surface in ("one", "two")
    )
    support = tuple(
        BreadthCase(
            f"support-{job}",
            f"support-{job}",
            "done",
            surface="three",
            job=job,
        )
        for job in ("select", "visual")
    )
    refusals = (
        {"job": "select", "test_id": "swift:select", "source_validated": True},
        {"job": "visual", "test_id": "swift:visual", "source_validated": True},
    )

    summary = run_v1_breadth_gate(
        repo,
        core_cases=core,
        support_cases=support,
        refusal_evidence=refusals,
        required_jobs=("select", "visual"),
        scenario_runner=lambda *args, **kwargs: {
            "passed": True,
            "contract_passed": True,
            "machine_receipt": {"outcome": "verified"},
            "independent_oracle": {"verdict": "matched", "effect": "done"},
            "dispatch_count": 1,
        },
        host_probe=lambda: dict(HOST_STATE),
        run_prefix="breadth-gate",
    )

    assert summary["passed"] is True
    assert summary["commands"] == 6
    assert summary["primitive_coverage"] == {
        "select": ["one", "three", "two"],
        "visual": ["one", "three", "two"],
    }
    assert summary["adversarial_coverage_passed"] is True


def test_v1_breadth_gate_refuses_a_missing_adversarial_job(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    (repo / "data/lab-runs").mkdir(parents=True)
    case = BreadthCase("one", "one", "done", surface="surface", job="select")

    summary = run_v1_breadth_gate(
        repo,
        core_cases=(case,),
        support_cases=(case,),
        refusal_evidence=(),
        required_jobs=("select",),
        scenario_runner=lambda *args, **kwargs: {
            "passed": True,
            "contract_passed": True,
            "machine_receipt": {"outcome": "verified"},
            "independent_oracle": {"verdict": "matched", "effect": "done"},
            "dispatch_count": 1,
        },
        host_probe=lambda: dict(HOST_STATE),
        run_prefix="breadth-refusal",
    )

    assert summary["adversarial_coverage_passed"] is False
    assert summary["passed"] is False


def test_breadth_suite_counts_oracle_matched_dispatch_only_but_not_wrong_effect(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    (repo / "data/lab-runs").mkdir(parents=True)
    cases = (
        BreadthCase("one", "one-scenario", "goal_one"),
        BreadthCase("two", "two-scenario", "goal_two"),
        BreadthCase("missing", None, "goal_three"),
    )

    def scenario_runner(
        root: Path, *, scenario: str, mode: str, run_id: str
    ) -> dict:
        effect = "goal_one" if scenario == "one-scenario" else "wrong"
        return {
            "passed": True,
            "contract_passed": True,
            "machine_receipt": {"outcome": "dispatch_only"},
            "independent_oracle": {"verdict": "matched", "effect": effect},
            "dispatch_count": 1,
        }

    summary = run_breadth_suite(
        repo,
        cases=cases,
        scenario_runner=scenario_runner,
        host_probe=lambda: dict(HOST_STATE),
        run_prefix="breadth-test",
    )

    assert summary["commands"] == 3
    assert summary["completed"] == 1
    assert summary["first_try_rate"] == pytest.approx(1 / 3)
    assert summary["safe_replans_attempted"] == 0
    assert summary["after_safe_replan_rate"] == pytest.approx(1 / 3)
    assert summary["passed"] is False
    assert [row["reason"] for row in summary["rows"]] == [
        None,
        "oracle_effect_mismatch",
        "scenario_missing",
    ]


def test_breadth_suite_records_one_run_error_and_continues(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    (repo / "data/lab-runs").mkdir(parents=True)
    seen = []

    def scenario_runner(
        root: Path, *, scenario: str, mode: str, run_id: str
    ) -> dict:
        seen.append(scenario)
        if scenario == "broken":
            raise RuntimeError("vertical_guest_failed:exit_1")
        return {
            "passed": True,
            "contract_passed": True,
            "machine_receipt": {"outcome": "verified"},
            "independent_oracle": {"verdict": "matched", "effect": "done"},
            "dispatch_count": 1,
        }

    summary = run_breadth_suite(
        repo,
        cases=(
            BreadthCase("one", "broken", "done"),
            BreadthCase("two", "working", "done"),
        ),
        scenario_runner=scenario_runner,
        host_probe=lambda: dict(HOST_STATE),
        run_prefix="breadth-error",
    )

    assert seen == ["broken", "working"]
    assert summary["completed"] == 1
    assert summary["rows"][0]["reason"] == "scenario_error"
    assert summary["rows"][0]["error"] == "vertical_guest_failed:exit_1"


def test_breadth_suite_does_not_call_nineteen_of_twenty_complete(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    (repo / "data/lab-runs").mkdir(parents=True)
    cases = tuple(
        BreadthCase(f"case-{index}", f"scenario-{index}", "done")
        for index in range(20)
    )

    def scenario_runner(
        root: Path, *, scenario: str, mode: str, run_id: str
    ) -> dict:
        completed = scenario != "scenario-19"
        return {
            "passed": completed,
            "contract_passed": completed,
            "machine_receipt": {
                "outcome": "verified" if completed else "no_effect"
            },
            "independent_oracle": {
                "verdict": "matched" if completed else "not_matched",
                "effect": "done",
            },
            "dispatch_count": 1,
        }

    summary = run_breadth_suite(
        repo,
        cases=cases,
        scenario_runner=scenario_runner,
        host_probe=lambda: dict(HOST_STATE),
        run_prefix="breadth-nineteen",
    )

    assert summary["first_try_rate"] == 0.95
    assert summary["after_safe_replan_rate"] == 0.95
    assert summary["safe_replans_attempted"] == 0
    assert summary["passed"] is False


def test_breadth_suite_cannot_pass_without_three_surfaces_per_primitive(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    (repo / "data/lab-runs").mkdir(parents=True)
    cases = tuple(
        BreadthCase(
            f"case-{index}", f"scenario-{index}", "done",
            surface="finder", job="collection_selection",
        )
        for index in range(20)
    )

    summary = run_breadth_suite(
        repo,
        cases=cases,
        scenario_runner=lambda *args, **kwargs: {
            "passed": True,
            "contract_passed": True,
            "machine_receipt": {"outcome": "verified"},
            "independent_oracle": {"verdict": "matched", "effect": "done"},
            "dispatch_count": 1,
        },
        host_probe=lambda: dict(HOST_STATE),
        run_prefix="breadth-coverage",
        required_jobs=("collection_selection",),
    )

    assert summary["first_try_rate"] == 1.0
    assert summary["primitive_coverage"]["collection_selection"] == ["finder"]
    assert summary["coverage_passed"] is False
    assert summary["passed"] is False


def test_breadth_suite_records_platform_error_and_continues(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    (repo / "data/lab-runs").mkdir(parents=True)
    seen = []

    def scenario_runner(
        root: Path, *, scenario: str, mode: str, run_id: str
    ) -> dict:
        seen.append(scenario)
        if scenario == "blocked":
            raise PermissionError(1, "Operation not permitted")
        return {
            "passed": True,
            "contract_passed": True,
            "machine_receipt": {"outcome": "verified"},
            "independent_oracle": {"verdict": "matched", "effect": "done"},
            "dispatch_count": 1,
        }

    summary = run_breadth_suite(
        repo,
        cases=(
            BreadthCase("one", "blocked", "done"),
            BreadthCase("two", "working", "done"),
        ),
        scenario_runner=scenario_runner,
        host_probe=lambda: dict(HOST_STATE),
        run_prefix="breadth-platform-error",
    )

    assert seen == ["blocked", "working"]
    assert summary["completed"] == 1
    assert summary["rows"][0]["reason"] == "scenario_error"
    assert summary["rows"][0]["error"] == "PermissionError"


def test_breadth_suite_refuses_a_result_that_failed_its_scenario_contract(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    (repo / "data/lab-runs").mkdir(parents=True)

    summary = run_breadth_suite(
        repo,
        cases=(BreadthCase("composed", "fixture-composed", "row_selected"),),
        scenario_runner=lambda *args, **kwargs: {
            "passed": True,
            "contract_passed": False,
            "machine_receipt": {"outcome": "verified"},
            "independent_oracle": {
                "verdict": "matched",
                "effect": "row_selected",
            },
            "dispatch_count": 1,
        },
        host_probe=lambda: dict(HOST_STATE),
        run_prefix="breadth-contract",
    )

    assert summary["completed"] == 0
    assert summary["rows"][0]["reason"] == "scenario_contract_failed"
from conn.lab.host import metadata_digest, personal_data_digest


HOST_STATE = {
    "frontmost_bundle": "com.openai.codex",
    "pointer": {"x": 100.0, "y": 200.0},
    "clipboard_sha256": "a" * 64,
    "applications_sha256": "b" * 64,
    "personal_data_sha256": "c" * 64,
}


def test_metadata_digest_changes_with_watched_file_metadata(
    tmp_path: Path,
) -> None:
    watched = tmp_path / "watched"
    watched.mkdir()
    item = watched / "item.txt"
    item.write_text("one")
    before = metadata_digest((watched,), base=tmp_path)

    item.write_text("different size")
    after = metadata_digest((watched,), base=tmp_path)

    assert before != after
    assert len(before) == 64
    assert len(after) == 64


def test_personal_data_digest_ignores_browser_runtime_churn(
    tmp_path: Path,
) -> None:
    documents = tmp_path / "Documents"
    firefox = (
        tmp_path
        / "Library"
        / "Application Support"
        / "Firefox"
        / "Profiles"
        / "profile"
    )
    documents.mkdir()
    firefox.mkdir(parents=True)
    document = documents / "private.txt"
    runtime = firefox / "session.json"
    document.write_text("unchanged")
    runtime.write_text("first")
    before = personal_data_digest(tmp_path)

    runtime.write_text("second browser state")

    assert personal_data_digest(tmp_path) == before

    document.write_text("changed personal data")

    assert personal_data_digest(tmp_path) != before


def test_host_comparison_names_every_changed_surface() -> None:
    after = {
        **HOST_STATE,
        "pointer": {"x": 101.0, "y": 200.0},
        "clipboard_sha256": "d" * 64,
    }

    assert compare_host_snapshots(HOST_STATE, after) == [
        "clipboard_sha256",
        "pointer",
    ]


def test_smoke_suite_runs_each_case_fresh_and_aggregates_timings(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    (repo / "data" / "lab-runs").mkdir(parents=True)
    run_date = date.today().isoformat()
    run_ids = []

    def scenario_runner(root: Path, *, run_id: str) -> dict:
        assert root == repo
        run_ids.append(run_id)
        artifact_dir = (
            root / "data" / "lab-runs" / run_date / run_id
        )
        artifact_dir.mkdir(parents=True)
        (artifact_dir / "runner-timings.json").write_text(json.dumps({
            "clone_ms": 100,
            "boot_ms": 200,
            "cleanup_ms": 50,
            "total_ms": 1000,
        }))
        (artifact_dir / "scenario-timings.json").write_text(json.dumps({
            "install_ms": 100,
            "scenario_ms": 500,
            "export_ms": 50,
        }))
        return {
            "passed": True,
            "machine_receipt": {"outcome": "verified"},
            "independent_oracle": {"verdict": "matched"},
        }

    summary = run_smoke_suite(
        repo,
        runs=3,
        run_prefix="test-smoke",
        scenario_runner=scenario_runner,
        host_probe=lambda: dict(HOST_STATE),
    )

    assert run_ids == [
        "test-smoke-01",
        "test-smoke-02",
        "test-smoke-03",
    ]
    assert summary["passed"] is True
    assert summary["passed_runs"] == 3
    assert summary["host_changes"] == []
    assert summary["host_snapshot_stable"] is True
    assert summary["timings_ms"]["total_ms"]["max"] == 1000


def test_smoke_suite_rejects_host_state_changes(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    (repo / "data" / "lab-runs").mkdir(parents=True)
    run_date = date.today().isoformat()

    def scenario_runner(root: Path, *, run_id: str) -> dict:
        artifact_dir = root / "data" / "lab-runs" / run_date / run_id
        artifact_dir.mkdir(parents=True)
        (artifact_dir / "runner-timings.json").write_text(json.dumps({
            "clone_ms": 1,
            "boot_ms": 1,
            "cleanup_ms": 1,
            "total_ms": 4,
        }))
        (artifact_dir / "scenario-timings.json").write_text(json.dumps({
            "install_ms": 1,
            "scenario_ms": 1,
            "export_ms": 1,
        }))
        return {
            "passed": True,
            "machine_receipt": {"outcome": "verified"},
            "independent_oracle": {"verdict": "matched"},
        }

    snapshots = iter([
        dict(HOST_STATE),
        dict(HOST_STATE),
        dict(HOST_STATE),
        {**HOST_STATE, "pointer": {"x": 101.0, "y": 200.0}},
    ])

    with pytest.raises(RuntimeError, match="smoke_run_failed:host_changed"):
        run_smoke_suite(
            repo,
            runs=1,
            run_prefix="host-drift",
            scenario_runner=scenario_runner,
            host_probe=lambda: next(snapshots),
            host_pause=lambda _: None,
        )

    summary = json.loads(
        (repo / "data" / "lab-runs" / run_date / "host-drift-summary.json")
        .read_text()
    )
    assert summary["passed"] is False
    assert summary["host_changes"] == ["pointer"]


def test_smoke_suite_waits_for_a_quiet_host_before_measuring(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    (repo / "data" / "lab-runs").mkdir(parents=True)
    run_date = date.today().isoformat()

    def scenario_runner(root: Path, *, run_id: str) -> dict:
        artifact_dir = root / "data" / "lab-runs" / run_date / run_id
        artifact_dir.mkdir(parents=True)
        (artifact_dir / "runner-timings.json").write_text(json.dumps({
            "clone_ms": 1,
            "boot_ms": 1,
            "cleanup_ms": 1,
            "total_ms": 4,
        }))
        (artifact_dir / "scenario-timings.json").write_text(json.dumps({
            "install_ms": 1,
            "scenario_ms": 1,
            "export_ms": 1,
        }))
        return {
            "passed": True,
            "machine_receipt": {"outcome": "verified"},
            "independent_oracle": {"verdict": "matched"},
        }

    moving = {**HOST_STATE, "pointer": {"x": 101.0, "y": 200.0}}
    quiet = {**HOST_STATE, "pointer": {"x": 300.0, "y": 400.0}}
    snapshots = iter([dict(HOST_STATE), moving, quiet, quiet, quiet, quiet])

    summary = run_smoke_suite(
        repo,
        runs=1,
        run_prefix="quiet-host",
        scenario_runner=scenario_runner,
        host_probe=lambda: next(snapshots),
        host_pause=lambda _: None,
    )

    assert summary["passed"] is True
    assert summary["host_before"] == quiet
    assert summary["host_after"] == quiet


def test_smoke_suite_rejects_receipt_or_oracle_mismatch(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    (repo / "data" / "lab-runs").mkdir(parents=True)
    run_date = date.today().isoformat()

    def bad_runner(root: Path, *, run_id: str) -> dict:
        artifact_dir = (
            root / "data" / "lab-runs" / run_date / run_id
        )
        artifact_dir.mkdir(parents=True)
        for name, payload in (
            ("runner-timings.json", {
                "clone_ms": 1,
                "boot_ms": 1,
                "cleanup_ms": 1,
                "total_ms": 4,
            }),
            ("scenario-timings.json", {
                "install_ms": 1,
                "scenario_ms": 1,
                "export_ms": 1,
            }),
        ):
            (artifact_dir / name).write_text(json.dumps(payload))
        return {
            "passed": True,
            "machine_receipt": {"outcome": "dispatch_only"},
            "independent_oracle": {"verdict": "matched"},
        }

    with pytest.raises(RuntimeError, match="smoke_run_failed"):
        run_smoke_suite(
            repo,
            runs=1,
            run_prefix="bad-smoke",
            scenario_runner=bad_runner,
            host_probe=lambda: dict(HOST_STATE),
        )


def test_scripted_matrix_runs_one_hundred_bounded_adversarial_cases() -> None:
    summary = run_scripted_matrix(iterations=100)

    assert summary == {
        "iterations": 100,
        "passed": 100,
        "wrong_targets": 0,
        "false_verified": 0,
        "stale_dispatches": 0,
        "retries_after_possible_dispatch": 0,
    }
