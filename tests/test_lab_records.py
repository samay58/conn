import json
from pathlib import Path

from conn.lab.catalog import load_catalog
from conn.lab.models import RunStatus
from conn.lab.records import BuildIdentity, write_run_records


ROOT = Path(__file__).resolve().parents[1]


def test_run_records_bind_manifest_receipt_oracle_and_build(tmp_path: Path) -> None:
    manifest = load_catalog(ROOT)["control"]
    result = {
        "machine_receipt": {
            "outcome": "verified",
            "reason_code": None,
        },
        "independent_oracle": {
            "verdict": "matched",
            "effect": "control_changed",
            "effect_count": 1,
        },
        "passed": True,
    }
    identity = BuildIdentity(
        guest_os_build="25A354",
        tart_version="2.32.1",
        image_digest="sha256:" + ("a" * 64),
        conn_commit="75e138c",
        dirty_tree_digest="b" * 64,
        binary_sha256="c" * 64,
        signing_identity="Conn Dev Signing",
    )

    write_run_records(
        tmp_path,
        run_id="lab-control-1",
        manifest=manifest,
        result=result,
        started_ms=100,
        finished_ms=200,
        identity=identity,
    )

    run = json.loads((tmp_path / "lab-run.json").read_text())
    oracle = json.loads((tmp_path / "oracle-result.json").read_text())
    artifact = json.loads((tmp_path / "artifact-manifest.json").read_text())
    assert run["status"] == RunStatus.PASSED
    assert run["scenario_id"] == "control"
    assert oracle["actual"]["effect"] == "control_changed"
    assert artifact["scenario_digest"] == manifest.digest
    assert artifact["binary_sha256"] == "c" * 64
