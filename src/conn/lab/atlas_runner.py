from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import json
from pathlib import Path
import re
import subprocess
import time

from .atlas import compile_atlas, load_capability_matrix, rank_blockers
from .runner import LabRunner, LabRunnerConfig, LabRunnerError
from .scenario import GUEST_ARTIFACTS, GUEST_PYTHON, GUEST_REPO, parse_frontmost_bundle


_IDENTIFIER = re.compile(r"^[a-zA-Z][a-zA-Z0-9_.-]*$")
_COUNT_LIMIT = 100_000
_CANDIDATE_JOBS = frozenset({
    "collection_selection",
    "control_activation",
    "document_history",
    "field_text_entry",
    "menus_overlays",
    "named_scroll",
})
_PROBE_JOBS = _CANDIDATE_JOBS | {
    "app_window_selection",
    "visual_fallback",
}


@dataclass(frozen=True, slots=True)
class CapsuleProbe:
    surface: str
    expected_bundle: str
    menu_kind: str
    setup_commands: tuple[tuple[str, ...], ...]
    truth_ready: bool = False
    reset_process: str | None = None


def capsule_probes() -> tuple[CapsuleProbe, ...]:
    html = "http://127.0.0.1:18888/atlas"
    return (
        CapsuleProbe(
            "calendar",
            "com.apple.iCal",
            "window",
            (("/usr/bin/open", "-a", "Calendar"),),
        ),
        CapsuleProbe(
            "finder",
            "com.apple.finder",
            "window",
            (
                ("/bin/mkdir", "-p", "/Users/admin/Conn Lab/Projects"),
                ("/bin/mkdir", "-p", "/Users/admin/Conn Lab/Archive"),
                ("/usr/bin/touch", "/Users/admin/Conn Lab/Projects/fixture.txt"),
                ("/usr/bin/open", "/Users/admin/Conn Lab"),
            ),
        ),
        CapsuleProbe(
            "firefox",
            "org.mozilla.firefox",
            "tab",
            (("/usr/bin/open", "-a", "Firefox", html),),
            truth_ready=True,
            reset_process="firefox",
        ),
        CapsuleProbe(
            "fixture",
            "com.conn.ActionFixture",
            "window",
            (
                (
                    "/bin/launchctl",
                    "setenv",
                    "CONN_FIXTURE_SCENE",
                    "unique_control",
                ),
                (
                    "/bin/launchctl",
                    "setenv",
                    "CONN_FIXTURE_TRUTH_LOG",
                    f"{GUEST_ARTIFACTS}/fixture-atlas-truth.jsonl",
                ),
                (
                    "/usr/bin/open",
                    "-na",
                    "/Applications/ConnActionFixture.app",
                    "--args",
                    "--scene",
                    "unique_control",
                ),
            ),
        ),
        CapsuleProbe(
            "notes",
            "com.apple.Notes",
            "note",
            (("/usr/bin/open", "-a", "Notes"),),
        ),
        CapsuleProbe(
            "preview",
            "com.apple.Preview",
            "window",
            ((
                "/usr/bin/open",
                f"{GUEST_REPO}/lab/fixtures/preview-atlas.pdf",
            ),),
        ),
        CapsuleProbe(
            "safari",
            "com.apple.Safari",
            "tab",
            (("/usr/bin/open", "-a", "Safari", html),),
            truth_ready=True,
        ),
        CapsuleProbe(
            "terminal",
            "com.apple.Terminal",
            "window",
            (("/usr/bin/open", "-a", "Terminal"),),
        ),
    )


def sanitize_native_probe(
    payload: dict,
    *,
    expected_bundle: str,
) -> dict:
    if payload.get("schema_version") != 1:
        raise ValueError("native_capability_probe_invalid")
    jobs = payload.get("jobs")
    if not isinstance(jobs, dict) or not set(jobs).issubset(_PROBE_JOBS):
        raise ValueError("native_capability_probe_invalid")
    app = jobs.get("app_window_selection")
    observed_bundle = app.get("bundle_id") if isinstance(app, dict) else None
    if observed_bundle != expected_bundle:
        raise ValueError(
            "native_capability_probe_bundle_mismatch:"
            f"{observed_bundle or 'none'}:{expected_bundle}"
        )
    sanitized: dict[str, dict] = {}
    for job in sorted(jobs):
        value = jobs[job]
        if not isinstance(value, dict):
            raise ValueError("native_capability_probe_invalid")
        if job == "app_window_selection":
            sanitized[job] = {
                "bundle_id": expected_bundle,
                "window_present": _boolean(value.get("window_present")),
                "secure": _boolean(value.get("secure")),
                "denied": _boolean(value.get("denied")),
            }
        elif job == "visual_fallback":
            bundle_id = _identifier(value.get("bundle_id"))
            if bundle_id and bundle_id != expected_bundle:
                raise ValueError(
                    "native_visual_probe_bundle_mismatch:"
                    f"{bundle_id}:{expected_bundle}"
                )
            sanitized[job] = {
                "available": _boolean(value.get("available")),
                "outcome": _identifier(value.get("outcome")),
                "reason_code": _optional_identifier(value.get("reason_code")),
                "image_bytes": _count(value.get("image_bytes")),
                "pixel_width": _count(value.get("pixel_width")),
                "pixel_height": _count(value.get("pixel_height")),
                "bundle_id": bundle_id,
            }
        else:
            sanitized[job] = {
                "bundle_id": _identifier(value.get("bundle_id")),
                "candidate_count": _count(value.get("candidate_count")),
                "total_match_count": _count(value.get("total_match_count")),
                "truncated": _boolean(value.get("truncated")),
                "secure": _boolean(value.get("secure")),
                "denied": _boolean(value.get("denied")),
                "roles": _count_map(value.get("roles")),
                "actions": _count_map(value.get("actions")),
            }
    return {"schema_version": 1, "jobs": sanitized}


def run_native_atlas(root: Path) -> dict:
    root = root.resolve(strict=True)
    matrix = load_capability_matrix(root)
    run_id = f"atlas-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
    runner = LabRunner(LabRunnerConfig(
        repo_root=root,
        artifact_root=root / "data" / "lab-runs",
    ))
    observations: dict[str, dict] = {}
    with runner.vnc_session(run_id) as session:
        truth_worker = session.start_execute(
            [
                GUEST_PYTHON,
                "-m",
                "conn.lab.truth_server",
                "--run-id",
                "atlas",
                "--truth-log",
                f"{GUEST_ARTIFACTS}/atlas-truth.jsonl",
                "--port",
                "18888",
            ],
            environment={"PYTHONPATH": f"{GUEST_REPO}/src"},
        )
        try:
            _wait_for_http(session, truth_worker, timeout_s=10)
            session.execute([
                "/bin/launchctl", "setenv", "CONN_LAB_GUEST", "1",
            ])
            session.execute([
                "/bin/launchctl", "setenv", "CONN_SERVER_PORT", "18787",
            ])
            session.execute([
                "/usr/bin/ditto",
                f"{GUEST_REPO}/macos/Conn.app",
                "/Applications/Conn.app",
            ])
            session.execute([
                "/usr/bin/ditto",
                f"{GUEST_REPO}/macos/.build/fixture/ConnActionFixture.app",
                "/Applications/ConnActionFixture.app",
            ])
            ready_count = 0
            for probe in capsule_probes():
                if probe.reset_process is not None:
                    session.execute_optional([
                        "/usr/bin/pkill", "-x", probe.reset_process,
                    ])
                    _wait_for_process_exit(
                        session, probe.reset_process, timeout_s=10
                    )
                for command in probe.setup_commands:
                    session.execute(command)
                _wait_for_bundle(session, probe.expected_bundle, timeout_s=15)
                if probe.truth_ready:
                    ready_count += 1
                    _wait_for_event_count(
                        session.artifact_dir / "atlas-truth.jsonl",
                        event="accessibility_ready",
                        count=ready_count,
                        timeout_s=10,
                    )
                output = session.artifact_dir / f"capability-{probe.surface}.json"
                session.execute([
                    "/usr/bin/open",
                    "-W",
                    "-na",
                    "/Applications/Conn.app",
                    "--args",
                    "--capability-probe",
                    probe.expected_bundle,
                    "--menu-kind",
                    probe.menu_kind,
                    "--output",
                    f"{GUEST_ARTIFACTS}/{output.name}",
                ])
                if not output.is_file():
                    raise LabRunnerError("native_capability_probe_missing")
                payload = _last_json_object(output.read_text())
                observations[probe.surface] = sanitize_native_probe(
                    payload,
                    expected_bundle=probe.expected_bundle,
                )
        finally:
            _stop_process(truth_worker)
        report = compile_atlas(matrix, observations)
        blockers = rank_blockers(report)
        (session.artifact_dir / "atlas-observations.json").write_text(
            json.dumps(observations, indent=2, sort_keys=True) + "\n"
        )
        (session.artifact_dir / "atlas-report.json").write_text(
            report.model_dump_json(indent=2) + "\n"
        )
        (session.artifact_dir / "atlas-blockers.json").write_text(
            json.dumps(
                [item.model_dump(mode="json") for item in blockers],
                indent=2,
                sort_keys=True,
            ) + "\n"
        )
    exposed = sum(row.exposure.value == "exposed" for row in report.rows)
    return {
        "run_id": run_id,
        "matrix_rows": report.matrix_rows,
        "exposed_rows": exposed,
        "unresolved_rows": report.matrix_rows - exposed,
        "blockers": [item.model_dump(mode="json") for item in blockers],
    }


def _wait_for_bundle(session, bundle_id: str, *, timeout_s: float) -> None:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        result = session.execute([
            "/usr/bin/env",
            f"PYTHONPATH={GUEST_REPO}/src",
            GUEST_PYTHON,
            "-m",
            "conn.lab.desktop",
        ])
        try:
            payload = json.loads(result.stdout)
        except ValueError as error:
            raise LabRunnerError("guest_window_snapshot_invalid") from error
        if parse_frontmost_bundle(payload) == bundle_id:
            return
        time.sleep(0.1)
    raise LabRunnerError("guest_frontmost_app_timeout")


def _wait_for_process_exit(session, name: str, *, timeout_s: float) -> None:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        result = session.execute_optional(["/usr/bin/pgrep", "-x", name])
        if result.returncode == 1:
            return
        if result.returncode not in {0, 1}:
            raise LabRunnerError("guest_process_probe_failed")
        time.sleep(0.1)
    raise LabRunnerError("guest_process_exit_timeout")


def _wait_for_http(session, process, *, timeout_s: float) -> None:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        result = session.execute_optional([
            "/usr/bin/curl",
            "--fail",
            "--silent",
            "--max-time",
            "1",
            "http://127.0.0.1:18888/health",
        ])
        if result.returncode == 0:
            return
        if process.poll() is not None:
            raise LabRunnerError("guest_truth_server_exited")
        time.sleep(0.1)
    raise LabRunnerError("guest_truth_server_not_ready")


def _wait_for_event_count(
    path: Path, *, event: str, count: int, timeout_s: float
) -> None:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        matches = 0
        if path.is_file():
            for line in path.read_text().splitlines():
                try:
                    value = json.loads(line)
                except ValueError:
                    continue
                matches += value.get("event") == event
        if matches >= count:
            return
        time.sleep(0.05)
    raise LabRunnerError("guest_browser_surface_not_ready")


def _stop_process(process) -> None:
    if process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=2)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=2)


def _last_json_object(output: str) -> dict:
    for line in reversed(output.splitlines()):
        try:
            value = json.loads(line)
        except ValueError:
            continue
        if isinstance(value, dict):
            return value
    raise ValueError("native_capability_probe_invalid")


def _boolean(value: object) -> bool:
    if not isinstance(value, bool):
        raise ValueError("native_capability_probe_invalid")
    return value


def _identifier(value: object) -> str:
    if not isinstance(value, str) or not _IDENTIFIER.fullmatch(value):
        raise ValueError("native_capability_probe_invalid")
    return value


def _optional_identifier(value: object) -> str:
    if value == "":
        return ""
    return _identifier(value)


def _count(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError("native_capability_probe_invalid")
    if not 0 <= value <= _COUNT_LIMIT:
        raise ValueError("native_capability_probe_invalid")
    return value


def _count_map(value: object) -> dict[str, int]:
    if not isinstance(value, dict) or len(value) > 32:
        raise ValueError("native_capability_probe_invalid")
    result = {}
    for key, count in sorted(value.items()):
        result[_identifier(key)] = _count(count)
    return result
