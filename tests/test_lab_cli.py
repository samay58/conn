from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from conn.lab.cli import (
    GOLDEN_VM,
    PINNED_BASE_IMAGE,
    PINNED_TART_VERSION,
    build_parser,
    doctor,
    load_run_report,
    softnet_is_privileged,
)


def test_lab_parser_exposes_only_the_approved_commands() -> None:
    parser = build_parser()

    assert parser.parse_args(["doctor"]).command == "doctor"
    assert parser.parse_args(["bootstrap"]).command == "bootstrap"
    run = parser.parse_args([
        "run",
        "safari-tab",
        "--mode",
        "live",
        "--fresh",
    ])
    assert run.scenario == "safari-tab"
    assert run.mode == "live"
    assert run.fresh is True
    assert parser.parse_args(["suite", "smoke"]).suite == "smoke"
    assert parser.parse_args(["suite", "release"]).suite == "release"
    assert parser.parse_args(["report", "run-123"]).run_id == "run-123"


def test_report_loads_one_bounded_run_without_private_payloads(
    tmp_path: Path,
) -> None:
    root = tmp_path / "repo"
    run_dir = root / "data" / "lab-runs" / "2026-07-16" / "run-123"
    run_dir.mkdir(parents=True)
    (run_dir / "vertical-result.json").write_text(json.dumps({
        "scenario": "control",
        "model_mode": "live",
        "machine_receipt": {
            "outcome": "verified",
            "reason_code": None,
            "data": {"image_bytes": "private"},
        },
        "independent_oracle": {
            "verdict": "matched",
            "effect": "control_changed",
            "effect_count": 1,
        },
        "transaction_count": 1,
        "dispatch_count": 1,
        "cost": {"estimated_usd": 0.01},
    }))
    (run_dir / "runner-timings.json").write_text(json.dumps({
        "clone_ms": 1,
        "boot_ms": 2,
        "cleanup_ms": 3,
        "total_ms": 10,
    }))
    (run_dir / "scenario-timings.json").write_text(json.dumps({
        "install_ms": 1,
        "scenario_ms": 2,
        "export_ms": 1,
    }))

    report = load_run_report(root, "run-123")

    assert report == {
        "run_id": "run-123",
        "scenario": "control",
        "mode": "live",
        "receipt": {
            "outcome": "verified",
            "reason_code": None,
        },
        "oracle": {
            "verdict": "matched",
            "effect": "control_changed",
            "effect_count": 1,
        },
        "transaction_count": 1,
        "dispatch_count": 1,
        "cost_usd": 0.01,
        "timings_ms": {
            "clone_ms": 1,
            "boot_ms": 2,
            "install_ms": 1,
            "scenario_ms": 2,
            "export_ms": 1,
            "cleanup_ms": 3,
            "total_ms": 10,
        },
    }


def test_report_refuses_missing_or_duplicate_run_ids(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    (root / "data" / "lab-runs").mkdir(parents=True)
    with pytest.raises(RuntimeError, match="lab_run_not_found"):
        load_run_report(root, "missing")

    for day in ("2026-07-15", "2026-07-16"):
        path = root / "data" / "lab-runs" / day / "duplicate"
        path.mkdir(parents=True)
        (path / "vertical-result.json").write_text("{}")
    with pytest.raises(RuntimeError, match="lab_run_ambiguous"):
        load_run_report(root, "duplicate")


def test_report_refuses_invalid_ids_and_nested_private_fields(
    tmp_path: Path,
) -> None:
    root = tmp_path / "repo"
    run_dir = root / "data" / "lab-runs" / "2026-07-16" / "nested"
    run_dir.mkdir(parents=True)
    (run_dir / "vertical-result.json").write_text(json.dumps({
        "scenario": "control",
        "model_mode": "scripted",
        "machine_receipt": {
            "outcome": {"secret": "must not print"},
            "reason_code": None,
        },
        "independent_oracle": {
            "verdict": "matched",
            "effect": "control_changed",
            "effect_count": 1,
        },
        "transaction_count": 1,
        "dispatch_count": 1,
        "cost": {"estimated_usd": 0.01},
    }))
    (run_dir / "runner-timings.json").write_text(json.dumps({
        "clone_ms": 1,
        "boot_ms": 2,
        "cleanup_ms": 3,
        "total_ms": 10,
    }))
    (run_dir / "scenario-timings.json").write_text(json.dumps({
        "install_ms": 1,
        "scenario_ms": 2,
        "export_ms": 1,
    }))

    with pytest.raises(RuntimeError, match="lab_run_id_invalid"):
        load_run_report(root, "../private")
    with pytest.raises(RuntimeError, match="lab_report_invalid"):
        load_run_report(root, "nested")


def test_report_refuses_private_paths_in_displayed_fields(
    tmp_path: Path,
) -> None:
    root = tmp_path / "repo"
    run_dir = root / "data" / "lab-runs" / "2026-07-16" / "private-path"
    run_dir.mkdir(parents=True)
    (run_dir / "vertical-result.json").write_text(json.dumps({
        "scenario": "/Users/samay/private",
        "model_mode": "scripted",
        "machine_receipt": {
            "outcome": "verified",
            "reason_code": None,
        },
        "independent_oracle": {
            "verdict": "matched",
            "effect": "control_changed",
            "effect_count": 1,
        },
        "transaction_count": 1,
        "dispatch_count": 1,
        "cost": {"estimated_usd": 0.01},
    }))
    (run_dir / "runner-timings.json").write_text(json.dumps({
        "clone_ms": 1,
        "boot_ms": 2,
        "cleanup_ms": 3,
        "total_ms": 10,
    }))
    (run_dir / "scenario-timings.json").write_text(json.dumps({
        "install_ms": 1,
        "scenario_ms": 2,
        "export_ms": 1,
    }))

    with pytest.raises(RuntimeError, match="lab_report_invalid"):
        load_run_report(root, "private-path")


def test_softnet_requires_root_suid_or_passwordless_sudo() -> None:
    assert softnet_is_privileged(
        SimpleNamespace(st_uid=0, st_mode=0o104755),
        sudo_works=False,
    )
    assert softnet_is_privileged(
        SimpleNamespace(st_uid=501, st_mode=0o100755),
        sudo_works=True,
    )
    assert not softnet_is_privileged(
        SimpleNamespace(st_uid=501, st_mode=0o100755),
        sudo_works=False,
    )


def test_doctor_reports_unprivileged_softnet_without_failing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    app = tmp_path / "macos" / "Conn.app"
    fixture = (
        tmp_path
        / "macos"
        / ".build"
        / "fixture"
        / "ConnActionFixture.app"
    )
    app.mkdir(parents=True)
    fixture.mkdir(parents=True)

    monkeypatch.setattr(
        "conn.lab.cli.shutil.which",
        lambda name: f"/usr/local/bin/{name}",
    )
    monkeypatch.setattr(
        "conn.lab.cli._output",
        lambda argv, stderr=False: (
            PINNED_TART_VERSION
            if "--version" in argv
            else "Authority=Conn Dev Signing"
        ),
    )
    monkeypatch.setattr(
        "conn.lab.cli._tart_vms",
        lambda tart: [
            {"Name": GOLDEN_VM, "State": "stopped"},
            {"Name": PINNED_BASE_IMAGE, "State": "stopped"},
        ],
    )
    monkeypatch.setattr("conn.lab.cli._softnet_ready", lambda path: False)
    monkeypatch.setattr(
        "conn.lab.cli.shutil.disk_usage",
        lambda root: SimpleNamespace(free=200 * 1024**3),
    )

    report = doctor(tmp_path)

    assert report["ok"] is True
    assert report["failures"] == []
    assert report["network_mode"] == "default_nat"
    assert report["softnet_privileged"] is False
