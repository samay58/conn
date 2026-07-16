import json
from pathlib import Path
import threading
import time

import pytest

from conn.action_probe import (
    _console_locked,
    _probe_artifact_path,
    _truth_entries_after,
    _wait_for_truth_effect,
    classify_fixture_probe,
    run_verified_probe,
    write_eye_verdict,
)


def test_fixture_probe_requires_independent_effect_evidence() -> None:
    result = classify_fixture_probe(
        dispatch_returned_success=True,
        truth_entries=[],
        before_value="baseline",
        after_value="baseline",
        supported_actions=("AXPress",),
        duration_ms=12,
    )

    assert result.false_success_reproduced is True
    assert result.independent_effect_seen is False


def test_fixture_probe_does_not_call_real_effect_false_success() -> None:
    result = classify_fixture_probe(
        dispatch_returned_success=True,
        truth_entries=[{"effect": "status_changed"}],
        before_value="baseline",
        after_value="changed",
        supported_actions=("AXPress",),
        duration_ms=12,
    )

    assert result.false_success_reproduced is False
    assert result.independent_effect_seen is True


def test_fixture_truth_excludes_late_read_of_pre_action_startup_event() -> None:
    entries = [
        {"effect": "fixture_ready", "monotonic_ns": 99},
        {"effect": "status_changed", "monotonic_ns": 101},
    ]

    assert _truth_entries_after(entries, started_ns=100) == [entries[1]]


def test_fixture_probe_waits_for_ready_truth_barrier(tmp_path) -> None:
    truth_path = tmp_path / "truth.jsonl"

    def write_ready() -> None:
        time.sleep(0.02)
        truth_path.write_text(
            json.dumps({"effect": "fixture_ready", "monotonic_ns": 99}) + "\n"
        )

    writer = threading.Thread(target=write_ready)
    writer.start()
    try:
        assert _wait_for_truth_effect(
            truth_path, "fixture_ready", timeout_s=0.5
        )
    finally:
        writer.join()


def test_probe_artifacts_do_not_collide_within_one_second(
    monkeypatch, tmp_path
) -> None:
    values = iter([100, 101])
    monkeypatch.setattr("conn.action_probe.time.time_ns", lambda: next(values))

    first = _probe_artifact_path(tmp_path, "notes", "verified")
    second = _probe_artifact_path(tmp_path, "notes", "verified")

    assert first != second


def test_console_lock_probe_reads_ioreg_plist(monkeypatch) -> None:
    class Result:
        stdout = b'<?xml version="1.0"?><plist version="1.0"><array><dict><key>IOConsoleLocked</key><true/></dict></array></plist>'

    monkeypatch.setattr("conn.action_probe.subprocess.run", lambda *args, **kwargs: Result())

    assert _console_locked() is True


def test_verified_probe_records_locked_console_block(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr("conn.action_probe._console_locked", lambda: True)

    with pytest.raises(RuntimeError, match="unlocked Mac console"):
        run_verified_probe(tmp_path, tmp_path / "data", "terminal")

    [artifact] = (tmp_path / "data/action-probes").glob("terminal-blocked-*.json")
    payload = json.loads(artifact.read_text())
    assert payload["outcome"] == "blocked"
    assert payload["reason"] == "console_locked"
    assert payload["engine_outcome"] is None


def test_probe_artifact_filename_carries_actual_outcome(tmp_path) -> None:
    from conn.action_probe import _write_verified_probe

    record = {"target": "fixture", "outcome": "no_effect",
              "engine_outcome": "no_effect"}
    payload = _write_verified_probe(tmp_path, "fixture", record)
    name = Path(payload["artifact"]).name
    assert "no_effect" in name
    assert "verified" not in name


def test_probe_artifact_filename_defaults_to_unclassified(tmp_path) -> None:
    from conn.action_probe import _write_verified_probe

    payload = _write_verified_probe(tmp_path, "safari", {"target": "safari"})
    assert "unclassified" in Path(payload["artifact"]).name


def test_eye_verdict_sidecar_links_receipt_without_rewriting_machine_outcome(tmp_path):
    probe = tmp_path / "safari-verified.json"
    probe.write_text(json.dumps({
        "receipt_id": "receipt-1",
        "engine_outcome": "dispatch_only",
    }))

    sidecar = write_eye_verdict(
        probe, receipt_id="receipt-1", verdict="matched", note="Tab appeared"
    )

    assert json.loads(probe.read_text())["engine_outcome"] == "dispatch_only"
    payload = json.loads(sidecar.read_text())
    assert payload == {
        "receipt_id": "receipt-1",
        "verdict": "matched",
        "note": "Tab appeared",
        "probe_artifact": str(probe),
    }
