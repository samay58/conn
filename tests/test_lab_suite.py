from __future__ import annotations

import json
from pathlib import Path

import pytest

from conn.lab.suite import (
    compare_host_snapshots,
    run_scripted_matrix,
    run_smoke_suite,
)
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
    run_ids = []

    def scenario_runner(root: Path, *, run_id: str) -> dict:
        assert root == repo
        run_ids.append(run_id)
        artifact_dir = (
            root / "data" / "lab-runs" / "2026-07-16" / run_id
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

    host_snapshots = iter([
        dict(HOST_STATE),
        {
            **HOST_STATE,
            "pointer": {"x": 800.0, "y": 600.0},
            "clipboard_sha256": "d" * 64,
        },
    ])
    summary = run_smoke_suite(
        repo,
        runs=3,
        run_prefix="test-smoke",
        scenario_runner=scenario_runner,
        host_probe=lambda: next(host_snapshots),
    )

    assert run_ids == [
        "test-smoke-01",
        "test-smoke-02",
        "test-smoke-03",
    ]
    assert summary["passed"] is True
    assert summary["passed_runs"] == 3
    assert summary["host_changes"] == ["clipboard_sha256", "pointer"]
    assert summary["host_snapshot_stable"] is False
    assert summary["timings_ms"]["total_ms"]["max"] == 1000


def test_smoke_suite_rejects_receipt_or_oracle_mismatch(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    (repo / "data" / "lab-runs").mkdir(parents=True)

    def bad_runner(root: Path, *, run_id: str) -> dict:
        artifact_dir = (
            root / "data" / "lab-runs" / "2026-07-16" / run_id
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
