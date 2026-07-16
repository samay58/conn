from __future__ import annotations

import base64
import json
from pathlib import Path
import plistlib
import re
import secrets
import subprocess
import time

from conn.config import load_config

from .catalog import driver_config, result_matches_manifest
from .desktop import (
    WindowRecord,
    approval_point,
    navigation_menu_point,
    notes_new_note_point,
    select_new_window,
)
from .runner import LabRunner, LabRunnerConfig, LabRunnerError, VNCGuestSession
from .models import ScenarioManifest, ScenarioMode
from .records import collect_build_identity, write_run_records
from .vnc import VNCClient


GUEST_REPO = "/Volumes/My Shared Files/repo"
GUEST_ARTIFACTS = "/Volumes/My Shared Files/artifacts"
GUEST_PYTHON = f"{GUEST_REPO}/.venv/bin/python"
_NOTES_OBJECT_ID = re.compile(
    r"^x-coredata://[A-F0-9-]{36}/ICNote/p[1-9][0-9]{0,9}$"
)


def guest_launch_environment(token: str) -> dict[str, str]:
    try:
        decoded = base64.b64decode(token, validate=True)
    except ValueError as error:
        raise ValueError("bridge token is invalid") from error
    if len(decoded) != 32:
        raise ValueError("bridge token is invalid")
    return {
        "CONN_BRIDGE_TOKEN": token,
        "CONN_DATA_DIR": f"{GUEST_ARTIFACTS}/data",
        "CONN_LAB_GUEST": "1",
        "CONN_PROJECT_ROOT": GUEST_REPO,
        "CONN_PYTHON": GUEST_PYTHON,
        "CONN_SERVER_PORT": "18787",
    }


def parse_snapshot(payload: dict) -> tuple[
    tuple[float, float], list[WindowRecord]
]:
    screen = payload.get("screen")
    windows = payload.get("windows")
    if (
        not isinstance(screen, dict)
        or not isinstance(windows, list)
        or len(windows) > 512
    ):
        raise ValueError("window snapshot is invalid")
    try:
        size = (float(screen["width"]), float(screen["height"]))
        records = [
            WindowRecord(
                number=int(value["number"]),
                owner=str(value["owner"]),
                layer=int(value["layer"]),
                x=float(value["x"]),
                y=float(value["y"]),
                width=float(value["width"]),
                height=float(value["height"]),
            )
            for value in windows
        ]
    except (KeyError, TypeError, ValueError) as error:
        raise ValueError("window snapshot is invalid") from error
    if size[0] <= 0 or size[1] <= 0:
        raise ValueError("window snapshot is invalid")
    return size, records


def parse_frontmost_bundle(payload: dict) -> str:
    bundle = payload.get("frontmost_bundle")
    if not isinstance(bundle, str) or not bundle or len(bundle) > 255:
        raise ValueError("frontmost bundle is invalid")
    return bundle


def has_owner_window(payload: dict, *, owner: str) -> bool:
    _, windows = parse_snapshot(payload)
    return any(window.owner == owner and window.layer == 0 for window in windows)


def parse_nonnegative_count(value: str) -> int:
    text = value.strip()
    if not text.isdigit():
        raise ValueError("app adapter count is invalid")
    count = int(text)
    if count > 10_000:
        raise ValueError("app adapter count is invalid")
    return count


def parse_notes_titles(value: str) -> tuple[str, ...]:
    try:
        titles = json.loads(value)
    except ValueError as error:
        raise ValueError("app adapter titles are invalid") from error
    if (
        not isinstance(titles, list)
        or len(titles) > 10_000
        or any(
            not isinstance(title, str) or len(title) > 1_024
            for title in titles
        )
    ):
        raise ValueError("app adapter titles are invalid")
    return tuple(titles)


def parse_notes_selected_object_id(value: str) -> str:
    encoded = value.encode()
    if not encoded or len(encoded) > 65_536:
        raise ValueError("app adapter selected note is invalid")
    try:
        state = plistlib.loads(encoded)
        selected = state["windowStateArchive"]["currentNoteObjectID"]
    except (KeyError, TypeError, ValueError, plistlib.InvalidFileException) as error:
        raise ValueError("app adapter selected note is invalid") from error
    if not isinstance(selected, str) or not _NOTES_OBJECT_ID.fullmatch(selected):
        raise ValueError("app adapter selected note is invalid")
    return selected


def browser_truth_oracle(
    events: list[dict],
    *,
    event: str,
    value: str,
) -> dict:
    matches = [
        item for item in events
        if item.get("event") == event and item.get("value") == value
    ]
    return {
        "verdict": "matched" if len(matches) == 1 else "not_matched",
        "effect": event,
        "effect_count": len(matches),
        "value": matches[0].get("value") if len(matches) == 1 else None,
    }


def browser_capsule_passes(
    *,
    scenario: str,
    receipt: dict,
    oracle: dict,
    transaction_count: int,
    dispatch_count: int,
    actual_bundle: str,
    expected_bundle: str,
) -> bool:
    allowed_outcomes = {
        "firefox_open": {"verified"},
        "safari_local": {"verified", "dispatch_only"},
        "firefox_local": {"verified", "dispatch_only"},
        "firefox_visual": {"dispatch_only"},
        "firefox_space": {"dispatch_only"},
    }.get(scenario)
    if allowed_outcomes is None:
        return False
    outcome = receipt.get("outcome")
    honest_ceiling = (
        outcome == "verified"
        or receipt.get("reason_code") == "no_trustworthy_witness"
    )
    return (
        outcome in allowed_outcomes
        and honest_ceiling
        and transaction_count == 1
        and dispatch_count == 1
        and actual_bundle == expected_bundle
        and oracle.get("verdict") == "matched"
    )


def notes_type_oracle(
    *,
    before: tuple[str, ...],
    after: tuple[str, ...],
    frontmost_bundle: str,
) -> dict:
    matched = (
        len(before) == 1
        and before == ("conn lab seed",)
        and after == ("conn lab scratch",)
        and frontmost_bundle == "com.apple.Notes"
    )
    return {
        "verdict": "matched" if matched else "not_matched",
        "effect": "notes_store_title_replaced",
        "effect_count": 1 if matched else 0,
        "before": list(before),
        "after": list(after),
        "frontmost_bundle": frontmost_bundle,
    }


def notes_selection_oracle(
    *,
    titles_before: tuple[str, ...],
    titles_after: tuple[str, ...],
    selected_before: str,
    selected_after: str,
    expected_selected: str,
    frontmost_bundle: str,
) -> dict:
    matched = (
        titles_before == ("conn lab seed", "Conn lab second")
        and titles_after == titles_before
        and selected_before != expected_selected
        and selected_after == expected_selected
        and frontmost_bundle == "com.apple.Notes"
    )
    return {
        "verdict": "matched" if matched else "not_matched",
        "effect": "notes_selected_object_changed",
        "effect_count": 1 if matched else 0,
        "titles_before": list(titles_before),
        "titles_after": list(titles_after),
        "selected_before": selected_before,
        "selected_after": selected_after,
        "expected_selected": expected_selected,
        "frontmost_bundle": frontmost_bundle,
    }


def _lab_trace_events(artifact_dir: Path) -> list[dict]:
    paths = sorted((artifact_dir / "data" / "traces").glob("*/*.jsonl"))
    if len(paths) > 64:
        raise ValueError("lab trace set is unbounded")
    events = []
    for path in paths:
        with path.open("rb") as handle:
            payload = handle.read(16_000_001)
        if len(payload) > 16_000_000:
            raise ValueError("lab trace is unbounded")
        for line in payload.decode("utf-8", errors="replace").splitlines():
            try:
                event = json.loads(line)
            except ValueError:
                continue
            if isinstance(event, dict):
                events.append(event)
    return events


def trace_reached_phase(artifact_dir: Path, phase: str) -> bool:
    if not phase or len(phase) > 64:
        raise ValueError("trace phase is invalid")
    return any(
        event.get("kind") == "phase_change"
        and event.get("to_phase") == phase
        for event in _lab_trace_events(artifact_dir)
    )


def trace_reached_ui_moment(artifact_dir: Path, moment: str) -> bool:
    if not moment or len(moment) > 64:
        raise ValueError("UI moment is invalid")
    return any(
        event.get("kind") == "ui_ack"
        and event.get("moment") == moment
        for event in _lab_trace_events(artifact_dir)
    )


def _read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    values = []
    for line in path.read_text().splitlines():
        try:
            value = json.loads(line)
        except ValueError:
            continue
        if isinstance(value, dict):
            values.append(value)
    return values


def _wait_for_guest_http(
    session: VNCGuestSession,
    *,
    url: str,
    timeout_s: float,
    process=None,
) -> None:
    deadline = time.monotonic() + timeout_s
    last_error = "no response"
    while time.monotonic() < deadline:
        result = session.execute_optional([
            "/usr/bin/curl",
            "--fail",
            "--silent",
            "--max-time",
            "1",
            url,
        ])
        if result.returncode == 0:
            return
        detail = (result.stderr or result.stdout).strip()[:260]
        last_error = f"curl_{result.returncode}:{detail}"
        if process is not None and process.poll() is not None:
            output = _worker_output(process).strip()
            raise LabRunnerError(
                f"guest_truth_server_exited:{output[:500]}"
            )
        time.sleep(0.1)
    raise LabRunnerError(f"guest_truth_server_not_ready:{last_error}")


def _wait_for_truth_event(
    path: Path,
    *,
    event: str,
    timeout_s: float,
) -> list[dict]:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        events = _read_jsonl(path)
        if any(item.get("event") == event for item in events):
            return events
        time.sleep(0.05)
    return _read_jsonl(path)


def _desktop_payload(session: VNCGuestSession) -> dict:
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
    if not isinstance(payload, dict):
        raise LabRunnerError("guest_window_snapshot_invalid")
    return payload


def _wait_for_frontmost_bundle(
    session: VNCGuestSession, *, bundle_id: str, timeout_s: float
) -> None:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if parse_frontmost_bundle(_desktop_payload(session)) == bundle_id:
            return
        time.sleep(0.1)
    raise LabRunnerError("guest_frontmost_app_timeout")


def _wait_for_owner_window(
    session: VNCGuestSession, *, owner: str, timeout_s: float
) -> None:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if has_owner_window(_desktop_payload(session), owner=owner):
            return
        time.sleep(0.1)
    raise LabRunnerError("guest_app_window_timeout")


def _notes_count(session: VNCGuestSession) -> int:
    result = session.execute([
        "/usr/bin/sqlite3",
        "-cmd",
        ".timeout 2000",
        "/Users/admin/Library/Group Containers/group.com.apple.notes/"
        "NoteStore.sqlite",
        "PRAGMA query_only=ON; "
        "SELECT COUNT(*) FROM ZICCLOUDSYNCINGOBJECT "
        "WHERE Z_ENT=12 AND COALESCE(ZMARKEDFORDELETION,0)=0;",
    ])
    return parse_nonnegative_count(result.stdout)


def _notes_titles(session: VNCGuestSession) -> tuple[str, ...]:
    result = session.execute([
        "/usr/bin/sqlite3",
        "-cmd",
        ".timeout 2000",
        "/Users/admin/Library/Group Containers/group.com.apple.notes/"
        "NoteStore.sqlite",
        "PRAGMA query_only=ON; "
        "SELECT json_group_array(title) FROM ("
        "SELECT COALESCE(ZTITLE1,'') AS title "
        "FROM ZICCLOUDSYNCINGOBJECT "
        "WHERE Z_ENT=12 AND COALESCE(ZMARKEDFORDELETION,0)=0 "
        "ORDER BY Z_PK"
        ");",
    ])
    return parse_notes_titles(result.stdout.strip())


def _notes_selected_object_id(session: VNCGuestSession) -> str:
    result = session.execute([
        "/usr/bin/defaults",
        "export",
        "com.apple.Notes",
        "-",
    ])
    return parse_notes_selected_object_id(result.stdout)


def _notes_count_after(
    session: VNCGuestSession, *, baseline: int, timeout_s: float
) -> int:
    deadline = time.monotonic() + timeout_s
    current = baseline
    while time.monotonic() < deadline:
        current = _notes_count(session)
        if current != baseline:
            return current
        time.sleep(0.1)
    return current


def _snapshot(session: VNCGuestSession) -> tuple[
    tuple[float, float], list[WindowRecord]
]:
    return parse_snapshot(_desktop_payload(session))


def _wait_for_new_window(
    session: VNCGuestSession,
    before: list[WindowRecord],
    *,
    owner: str,
    layer: int,
    timeout_s: float,
) -> tuple[tuple[float, float], list[WindowRecord], WindowRecord]:
    deadline = time.monotonic() + timeout_s
    last_error: ValueError | None = None
    while time.monotonic() < deadline:
        screen, windows = _snapshot(session)
        try:
            selected = select_new_window(
                before,
                windows,
                owner=owner,
                layer=layer,
            )
        except ValueError as error:
            last_error = error
            time.sleep(0.1)
            continue
        return screen, windows, selected
    reason = str(last_error) if last_error is not None else "window missing"
    raise LabRunnerError(f"guest_window_timeout:{reason}")


def _wait_for_file(path: Path, timeout_s: float) -> None:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if path.exists():
            return
        time.sleep(0.05)
    raise LabRunnerError(f"guest_artifact_missing:{path.name}")


def _wait_for_process_absent(
    session: VNCGuestSession,
    *,
    name: str,
    timeout_s: float,
) -> None:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        result = session.execute_optional([
            "/usr/bin/pgrep",
            "-x",
            name,
        ])
        if result.returncode != 0:
            return
        time.sleep(0.05)
    raise LabRunnerError(f"guest_process_still_running:{name}")


def _set_launch_environment(
    session: VNCGuestSession,
    environment: dict[str, str],
) -> None:
    for key, value in sorted(environment.items()):
        session.execute_private(["/bin/launchctl", "setenv", key, value])


def _stop_worker(worker) -> None:
    if worker is None or worker.poll() is not None:
        return
    worker.terminate()
    try:
        worker.wait(timeout=2)
    except subprocess.TimeoutExpired:
        worker.kill()
        worker.wait(timeout=2)


def _worker_output(worker, *, limit: int = 262_144) -> str:
    chunks: list[str] = []
    size = 0
    while size < limit:
        line = worker.read_line(0.01)
        if line is None:
            break
        remaining = limit - size
        chunks.append(line[:remaining])
        size += len(line[:remaining])
    return "".join(chunks)


def run_l3(
    repo_root: Path,
    *,
    run_id: str = "l3-vertical",
    input_mode: str = "typed",
    fixture_scene: str | None = "unique_control",
    vertical_scenario: str = "control",
    truth_server_run_id: str | None = None,
    model_mode: str = "scripted",
    manifest: ScenarioManifest | None = None,
) -> dict:
    if input_mode not in {"typed", "audio"}:
        raise ValueError("lab input mode is invalid")
    if model_mode not in {"scripted", "live"}:
        raise ValueError("lab model mode is invalid")
    if manifest is not None:
        manifest = manifest.model_copy(
            update={"mode": ScenarioMode(model_mode)}
        )
        driver = driver_config(manifest)
        fixture_scene = driver.fixture_scene
        vertical_scenario = driver.vertical_scenario
        truth_server_run_id = driver.truth_server_run_id
    api_key = load_config().api_key if model_mode == "live" else None
    if model_mode == "live" and not api_key:
        raise LabRunnerError("live_model_key_missing")
    repo_root = repo_root.resolve(strict=True)
    runner = LabRunner(LabRunnerConfig(
        repo_root=repo_root,
        artifact_root=repo_root / "data" / "lab-runs",
    ))
    token = base64.b64encode(secrets.token_bytes(32)).decode()
    environment = guest_launch_environment(token)
    worker = None
    truth_worker = None
    vnc = None
    notes_before = None
    notes_titles_before: tuple[str, ...] | None = None
    notes_selected_before: str | None = None
    notes_expected_selected: str | None = None
    timings = {
        "install_ms": 0,
        "scenario_ms": 0,
        "export_ms": 0,
    }
    scenario_started: float | None = None
    export_started: float | None = None
    started_ms = round(time.monotonic() * 1000)
    artifact_dir: Path | None = None
    guest_os_build: str | None = None
    completed_result: dict | None = None
    with runner.vnc_session(run_id) as session:
        try:
            artifact_dir = session.artifact_dir
            guest_os_build = session.execute([
                "/usr/bin/sw_vers",
                "-buildVersion",
            ]).stdout.strip()
            if not guest_os_build or len(guest_os_build) > 80:
                raise LabRunnerError("guest_os_build_invalid")
            if manifest is not None:
                (session.artifact_dir / "scenario.json").write_text(
                    manifest.model_dump_json(indent=2) + "\n"
                )
            audio_args: list[str] = []
            if input_mode == "audio":
                audio_file = session.artifact_dir / "command.pcm"
                audio_file.write_bytes(b"\x00\x01" * 320)
                audio_args = [
                    "--input-mode",
                    "audio",
                    "--audio-file",
                    f"{GUEST_ARTIFACTS}/command.pcm",
                ]
            session.execute_optional(["/usr/bin/pkill", "-x", "Conn"])
            session.execute_optional([
                "/usr/bin/pkill", "-x", "ConnActionFixture",
            ])
            install_started = time.monotonic()
            session.execute([
                "/usr/bin/ditto",
                f"{GUEST_REPO}/macos/Conn.app",
                "/Applications/Conn.app",
            ])
            truth_log = f"{GUEST_ARTIFACTS}/fixture-truth.jsonl"
            launch_environment = dict(environment)
            if fixture_scene is not None:
                session.execute([
                    "/usr/bin/ditto",
                    f"{GUEST_REPO}/macos/.build/fixture/ConnActionFixture.app",
                    "/Applications/ConnActionFixture.app",
                ])
                launch_environment.update({
                    "CONN_FIXTURE_SCENE": fixture_scene,
                    "CONN_FIXTURE_TRUTH_LOG": truth_log,
                })
            timings["install_ms"] = round(
                (time.monotonic() - install_started) * 1000
            )
            scenario_started = time.monotonic()
            _set_launch_environment(session, launch_environment)
            if fixture_scene is not None:
                session.execute([
                    "/usr/bin/open",
                    "-na",
                    "/Applications/ConnActionFixture.app",
                    "--args",
                    "--scene",
                    fixture_scene,
                ])
            else:
                (session.artifact_dir / "fixture-truth.jsonl").write_text("")
            _wait_for_file(session.artifact_dir / "fixture-truth.jsonl", 10)
            if truth_server_run_id is not None:
                truth_worker = session.start_execute(
                    [
                        GUEST_PYTHON,
                        "-m",
                        "conn.lab.truth_server",
                        "--run-id",
                        truth_server_run_id,
                        "--truth-log",
                        f"{GUEST_ARTIFACTS}/browser-truth.jsonl",
                        "--port",
                        "18888",
                    ],
                    environment={
                        "PYTHONPATH": f"{GUEST_REPO}/src",
                    },
                )
                _wait_for_guest_http(
                    session,
                    url="http://127.0.0.1:18888/health",
                    timeout_s=10,
                    process=truth_worker,
                )
            if vertical_scenario in {"firefox_visual", "firefox_space"}:
                session.execute([
                    "/usr/bin/open",
                    "-a",
                    "/Applications/Firefox.app",
                    "http://127.0.0.1:18888/media",
                ])
                _wait_for_truth_event(
                    session.artifact_dir / "browser-truth.jsonl",
                    event="page_loaded",
                    timeout_s=10,
                )
            if vertical_scenario == "safari_tab":
                session.execute([
                    "/usr/bin/open",
                    "-a",
                    "/Applications/Safari.app",
                    "http://127.0.0.1:18888/media",
                ])
                _wait_for_truth_event(
                    session.artifact_dir / "browser-truth.jsonl",
                    event="page_loaded",
                    timeout_s=10,
                )
            if vertical_scenario in {
                "notes_create",
                "notes_observe",
                "notes_type",
                "notes_select",
            }:
                session.execute([
                    "/usr/bin/open",
                    "-a",
                    "/System/Applications/Notes.app",
                ])
                _wait_for_frontmost_bundle(
                    session,
                    bundle_id="com.apple.Notes",
                    timeout_s=10,
                )
                _wait_for_owner_window(
                    session,
                    owner="Notes",
                    timeout_s=10,
                )
                notes_before = _notes_count(session)
                notes_titles_before = _notes_titles(session)
                notes_expected_selected = _notes_selected_object_id(session)
                if vertical_scenario == "notes_select":
                    screen, notes_windows = _snapshot(session)
                    note_windows = [
                        window for window in notes_windows
                        if window.owner == "Notes" and window.layer == 0
                    ]
                    if len(note_windows) != 1:
                        raise LabRunnerError("guest_notes_window_ambiguous")
                    vnc = VNCClient.connect(*session.vnc_endpoint)
                    setup_point = notes_new_note_point(note_windows[0])
                    (session.artifact_dir / "notes-setup-pointer.json").write_text(
                        json.dumps({
                            "window": {
                                "x": note_windows[0].x,
                                "y": note_windows[0].y,
                                "width": note_windows[0].width,
                                "height": note_windows[0].height,
                            },
                            "point": setup_point,
                        }, indent=2, sort_keys=True)
                    )
                    vnc.click(
                        setup_point,
                        logical_size=screen,
                    )
                    time.sleep(0.25)
                    vnc.type_text("conn lab second")
                    deadline = time.monotonic() + 5
                    while time.monotonic() < deadline:
                        notes_titles_before = _notes_titles(session)
                        if notes_titles_before == (
                            "conn lab seed",
                            "Conn lab second",
                        ):
                            break
                        time.sleep(0.1)
                    else:
                        (session.artifact_dir / "notes-setup.json").write_text(
                            json.dumps({
                                "titles": list(notes_titles_before or ()),
                                "expected": [
                                    "conn lab seed",
                                    "Conn lab second",
                                ],
                            }, indent=2, sort_keys=True)
                        )
                        raise LabRunnerError("guest_notes_setup_timeout")
                    deadline = time.monotonic() + 5
                    while time.monotonic() < deadline:
                        notes_selected_before = _notes_selected_object_id(session)
                        if notes_selected_before != notes_expected_selected:
                            break
                        time.sleep(0.1)
                    else:
                        raise LabRunnerError("guest_notes_selection_setup_timeout")
            session.execute_optional(["/usr/bin/pkill", "-x", "Conn"])
            _wait_for_process_absent(
                session,
                name="Conn",
                timeout_s=5,
            )
            _, before_conn = _snapshot(session)
            worker = session.start_private_execute(
                [
                    GUEST_PYTHON,
                    "-m",
                    "conn.lab.vertical",
                    "--artifact-dir",
                    GUEST_ARTIFACTS,
                    "--truth-log",
                    truth_log,
                    "--timeout",
                    "60" if model_mode == "live" else "30",
                    "--scenario",
                    vertical_scenario,
                    "--model-mode",
                    model_mode,
                    *audio_args,
                ],
                environment={
                    "CONN_BRIDGE_TOKEN": token,
                    "CONN_DATA_DIR": f"{GUEST_ARTIFACTS}/data",
                    "PYTHONPATH": f"{GUEST_REPO}/src",
                    **(
                        {"OPENAI_API_KEY": api_key}
                        if api_key is not None
                        else {}
                    ),
                },
            )
            _wait_for_file(session.artifact_dir / "daemon-ready.json", 10)
            session.execute([
                "/usr/bin/open", "-a", "/Applications/Conn.app",
            ])
            screen, after_conn, status_item = _wait_for_new_window(
                session,
                before_conn,
                owner="Control Center",
                layer=25,
                timeout_s=10,
            )
            if vnc is None:
                vnc = VNCClient.connect(*session.vnc_endpoint)
            vnc.click(status_item.center, logical_size=screen)
            _, _, menu = _wait_for_new_window(
                session,
                after_conn,
                owner="Conn",
                layer=101,
                timeout_s=5,
            )
            grant_point = navigation_menu_point(menu)
            (session.artifact_dir / "navigation-menu.json").write_text(
                json.dumps({
                    "x": menu.x,
                    "y": menu.y,
                    "width": menu.width,
                    "height": menu.height,
                    "point": grant_point,
                }, indent=2, sort_keys=True)
            )
            vnc.click(grant_point, logical_size=screen)
            approval_record = None
            if vertical_scenario == "notes_create":
                deadline = time.monotonic() + 10
                while time.monotonic() < deadline:
                    if (
                        trace_reached_phase(
                            session.artifact_dir,
                            "awaiting_approval",
                        )
                        and trace_reached_ui_moment(
                            session.artifact_dir,
                            "approval",
                        )
                    ):
                        break
                    time.sleep(0.05)
                else:
                    raise LabRunnerError("guest_approval_surface_timeout")
                approval_screen, approval_windows = _snapshot(session)
                approval_panels = [
                    window for window in approval_windows
                    if (
                        window.owner == "Conn"
                        and window.layer == 25
                        and window.width == 424
                        and window.height == 196
                    )
                ]
                if len(approval_panels) != 1:
                    raise LabRunnerError("guest_approval_panel_ambiguous")
                approval_record = approval_panels[0]
                point = approval_point(approval_record)
                (session.artifact_dir / "approval-pointer.json").write_text(
                    json.dumps({
                        "window_number": approval_record.number,
                        "x": approval_record.x,
                        "y": approval_record.y,
                        "width": approval_record.width,
                        "height": approval_record.height,
                        "point": point,
                    }, indent=2, sort_keys=True)
                )
                vnc.click(point, logical_size=approval_screen)
            exit_code = worker.wait(
                timeout=80 if model_mode == "live" else 40
            )
            worker_output = _worker_output(worker)
            if worker_output:
                (session.artifact_dir / "guest-worker.log").write_text(
                    worker_output
                )
            if exit_code != 0:
                diagnostics = session.execute_optional([
                    "/usr/bin/log",
                    "show",
                    "--last",
                    "2m",
                    "--style",
                    "compact",
                    "--predicate",
                    'process == "Conn"',
                ])
                if diagnostics is not None:
                    (session.artifact_dir / "guest-conn.log").write_text(
                        diagnostics.stdout
                    )
                raise LabRunnerError(
                    f"vertical_guest_failed:exit_{exit_code}"
                )
            result_path = session.artifact_dir / "vertical-result.json"
            _wait_for_file(result_path, 2)
            result = json.loads(result_path.read_text())
            if vertical_scenario == "firefox_open":
                actual_bundle = parse_frontmost_bundle(
                    _desktop_payload(session)
                )
                expected_bundle = "org.mozilla.firefox"
                result["independent_oracle"] = {
                    "verdict": (
                        "matched"
                        if actual_bundle == expected_bundle
                        else "not_matched"
                    ),
                    "effect": "frontmost_bundle",
                    "effect_count": 1,
                    "value": actual_bundle,
                }
                receipt = result.get("machine_receipt") or {}
                result["passed"] = (
                    receipt.get("outcome") == "verified"
                    and result.get("transaction_count") == 1
                    and result.get("dispatch_count") == 1
                    and actual_bundle == expected_bundle
                )
                result_path.write_text(
                    json.dumps(result, indent=2, sort_keys=True)
                )
            if vertical_scenario == "notes_type":
                deadline = time.monotonic() + 5
                notes_titles_after = _notes_titles(session)
                while (
                    notes_titles_after != ("conn lab scratch",)
                    and time.monotonic() < deadline
                ):
                    time.sleep(0.1)
                    notes_titles_after = _notes_titles(session)
                actual_bundle = parse_frontmost_bundle(
                    _desktop_payload(session)
                )
                result["independent_oracle"] = notes_type_oracle(
                    before=notes_titles_before or (),
                    after=notes_titles_after,
                    frontmost_bundle=actual_bundle,
                )
                receipt = result.get("machine_receipt") or {}
                result["passed"] = (
                    receipt.get("outcome") == "verified"
                    and result.get("transaction_count") == 1
                    and result.get("dispatch_count") == 1
                    and result["independent_oracle"]["verdict"] == "matched"
                )
                result_path.write_text(
                    json.dumps(result, indent=2, sort_keys=True)
                )
            if vertical_scenario == "notes_select":
                deadline = time.monotonic() + 5
                selected_after = _notes_selected_object_id(session)
                while (
                    selected_after != notes_expected_selected
                    and time.monotonic() < deadline
                ):
                    time.sleep(0.1)
                    selected_after = _notes_selected_object_id(session)
                titles_after = _notes_titles(session)
                actual_bundle = parse_frontmost_bundle(
                    _desktop_payload(session)
                )
                result["independent_oracle"] = notes_selection_oracle(
                    titles_before=notes_titles_before or (),
                    titles_after=titles_after,
                    selected_before=notes_selected_before or "",
                    selected_after=selected_after,
                    expected_selected=notes_expected_selected or "",
                    frontmost_bundle=actual_bundle,
                )
                receipt = result.get("machine_receipt") or {}
                result["passed"] = (
                    receipt.get("outcome") == "verified"
                    and result.get("transaction_count") == 1
                    and result.get("dispatch_count") == 1
                    and result["independent_oracle"]["verdict"] == "matched"
                )
                result_path.write_text(
                    json.dumps(result, indent=2, sort_keys=True)
                )
            browser_bundle = {
                "safari_local": "com.apple.Safari",
                "firefox_local": "org.mozilla.firefox",
                "firefox_visual": "org.mozilla.firefox",
                "firefox_space": "org.mozilla.firefox",
            }.get(vertical_scenario)
            if browser_bundle is not None:
                expected_event, expected_value = {
                    "safari_local": ("page_loaded", "ready"),
                    "firefox_local": ("page_loaded", "ready"),
                    "firefox_visual": ("pointer_play", "playing"),
                    "firefox_space": ("space_play", "playing"),
                }[vertical_scenario]
                events = _wait_for_truth_event(
                    session.artifact_dir / "browser-truth.jsonl",
                    event=expected_event,
                    timeout_s=5,
                )
                result["independent_oracle"] = browser_truth_oracle(
                    events,
                    event=expected_event,
                    value=expected_value,
                )
                actual_bundle = parse_frontmost_bundle(
                    _desktop_payload(session)
                )
                receipt = result.get("machine_receipt") or {}
                result["passed"] = browser_capsule_passes(
                    scenario=vertical_scenario,
                    receipt=receipt,
                    oracle=result["independent_oracle"],
                    transaction_count=result.get("transaction_count", 0),
                    dispatch_count=result.get("dispatch_count", 0),
                    actual_bundle=actual_bundle,
                    expected_bundle=browser_bundle,
                )
                result["independent_oracle"]["frontmost_bundle"] = actual_bundle
                result_path.write_text(
                    json.dumps(result, indent=2, sort_keys=True)
                )
            if vertical_scenario == "safari_tab":
                events = _wait_for_truth_event(
                    session.artifact_dir / "browser-truth.jsonl",
                    event="page_hidden",
                    timeout_s=5,
                )
                receipt = result.get("machine_receipt") or {}
                result["independent_oracle"] = browser_truth_oracle(
                    events,
                    event="page_hidden",
                    value="hidden",
                )
                actual_bundle = parse_frontmost_bundle(
                    _desktop_payload(session)
                )
                result["independent_oracle"]["frontmost_bundle"] = actual_bundle
                result["passed"] = (
                    receipt.get("outcome") == "verified"
                    and result.get("transaction_count") == 1
                    and result.get("dispatch_count") == 1
                    and actual_bundle == "com.apple.Safari"
                    and result["independent_oracle"]["verdict"] == "matched"
                )
                result_path.write_text(
                    json.dumps(result, indent=2, sort_keys=True)
                )
            if vertical_scenario == "notes_create":
                notes_after = _notes_count_after(
                    session,
                    baseline=notes_before if notes_before is not None else 0,
                    timeout_s=5,
                )
                receipt = result.get("machine_receipt") or {}
                result["independent_oracle"] = {
                    "verdict": (
                        "matched"
                        if notes_before is not None
                        and notes_after == notes_before + 1
                        else "not_matched"
                    ),
                    "effect": "notes_store_count_delta",
                    "effect_count": (
                        notes_after - notes_before
                        if notes_before is not None
                        else None
                    ),
                    "before": notes_before,
                    "after": notes_after,
                }
                actual_bundle = parse_frontmost_bundle(
                    _desktop_payload(session)
                )
                result["independent_oracle"]["frontmost_bundle"] = actual_bundle
                result["passed"] = (
                    receipt.get("outcome") == "verified"
                    and result.get("transaction_count") == 1
                    and result.get("dispatch_count") == 1
                    and actual_bundle == "com.apple.Notes"
                    and result["independent_oracle"]["verdict"] == "matched"
                )
                result_path.write_text(
                    json.dumps(result, indent=2, sort_keys=True)
                )
            if manifest is not None:
                result["scenario_digest"] = manifest.digest
                result["contract_passed"] = result_matches_manifest(
                    manifest,
                    result,
                )
                result["passed"] = (
                    result.get("passed") is True
                    and result["contract_passed"]
                )
                result_path.write_text(
                    json.dumps(result, indent=2, sort_keys=True) + "\n"
                )
            export_started = time.monotonic()
            if scenario_started is not None:
                timings["scenario_ms"] = round(
                    (export_started - scenario_started) * 1000
                )
            host_record = {
                "framebuffer": {
                    "width": vnc.framebuffer_size[0],
                    "height": vnc.framebuffer_size[1],
                },
                "logical_screen": {
                    "width": screen[0],
                    "height": screen[1],
                },
                "status_item": {
                    "window_number": status_item.number,
                    "point": status_item.center,
                },
                "navigation_menu": {
                    "window_number": menu.number,
                    "point": grant_point,
                },
                "approval_window": (
                    {
                        "window_number": approval_record.number,
                        "point": approval_point(approval_record),
                    }
                    if approval_record is not None
                    else None
                ),
                "input_mode": input_mode,
                "fixture_scene": fixture_scene,
                "vertical_scenario": vertical_scenario,
                "truth_server_run_id": truth_server_run_id,
                "model_mode": model_mode,
                "passed": bool(result.get("passed")),
            }
            (session.artifact_dir / "host-driver.json").write_text(
                json.dumps(host_record, indent=2, sort_keys=True)
            )
            diagnostics = session.execute_optional([
                "/usr/bin/log",
                "show",
                "--last",
                "2m",
                "--style",
                "compact",
                "--predicate",
                'process == "Conn"',
            ])
            if diagnostics.stdout:
                (session.artifact_dir / "guest-conn.log").write_text(
                    diagnostics.stdout
                )
            timings["export_ms"] = round(
                (time.monotonic() - export_started) * 1000
            )
            completed_result = result
        finally:
            if scenario_started is not None and timings["scenario_ms"] == 0:
                timings["scenario_ms"] = round(
                    (time.monotonic() - scenario_started) * 1000
                )
            if export_started is not None and timings["export_ms"] == 0:
                timings["export_ms"] = round(
                    (time.monotonic() - export_started) * 1000
                )
            (session.artifact_dir / "scenario-timings.json").write_text(
                json.dumps(timings, indent=2, sort_keys=True) + "\n"
            )
            if vnc is not None:
                vnc.close()
            _stop_worker(worker)
            if truth_worker is not None:
                _stop_worker(truth_worker)
                truth_output = _worker_output(truth_worker)
                if truth_output:
                    (session.artifact_dir / "truth-server.log").write_text(
                        truth_output
                    )
    if completed_result is None:
        raise LabRunnerError("lab_result_missing")
    if manifest is not None:
        if artifact_dir is None or guest_os_build is None:
            raise LabRunnerError("lab_record_context_missing")
        write_run_records(
            artifact_dir,
            run_id=run_id,
            manifest=manifest,
            result=completed_result,
            started_ms=started_ms,
            finished_ms=round(time.monotonic() * 1000),
            identity=collect_build_identity(
                repo_root,
                guest_os_build=guest_os_build,
            ),
        )
    return completed_result


def run_l4_menu(repo_root: Path, *, run_id: str = "l4-menu") -> dict:
    return run_l3(
        repo_root,
        run_id=run_id,
        fixture_scene="menu_recapture",
        vertical_scenario="menu",
    )


def run_l4_visual(repo_root: Path, *, run_id: str = "l4-visual") -> dict:
    return run_l3(
        repo_root,
        run_id=run_id,
        fixture_scene="opaque_media",
        vertical_scenario="visual",
    )


def run_l5_firefox_open(
    repo_root: Path, *, run_id: str = "l5-firefox-open"
) -> dict:
    return run_l3(
        repo_root,
        run_id=run_id,
        fixture_scene=None,
        vertical_scenario="firefox_open",
    )


def run_l5_safari_local(
    repo_root: Path, *, run_id: str = "l5-safari-local"
) -> dict:
    return run_l3(
        repo_root,
        run_id=run_id,
        fixture_scene=None,
        vertical_scenario="safari_local",
        truth_server_run_id="safari-local",
    )


def run_l5_safari_tab(
    repo_root: Path, *, run_id: str = "l5-safari-tab"
) -> dict:
    return run_l3(
        repo_root,
        run_id=run_id,
        fixture_scene=None,
        vertical_scenario="safari_tab",
        truth_server_run_id="safari-tab",
    )


def run_l5_firefox_local(
    repo_root: Path, *, run_id: str = "l5-firefox-local"
) -> dict:
    return run_l3(
        repo_root,
        run_id=run_id,
        fixture_scene=None,
        vertical_scenario="firefox_local",
        truth_server_run_id="firefox-local",
    )


def run_l5_firefox_visual(
    repo_root: Path, *, run_id: str = "l5-firefox-visual"
) -> dict:
    return run_l3(
        repo_root,
        run_id=run_id,
        fixture_scene=None,
        vertical_scenario="firefox_visual",
        truth_server_run_id="firefox-visual",
    )


def run_l5_firefox_space(
    repo_root: Path, *, run_id: str = "l5-firefox-space"
) -> dict:
    return run_l3(
        repo_root,
        run_id=run_id,
        fixture_scene=None,
        vertical_scenario="firefox_space",
        truth_server_run_id="firefox-space",
    )


def run_l5_notes_create(
    repo_root: Path, *, run_id: str = "l5-notes-create"
) -> dict:
    return run_l3(
        repo_root,
        run_id=run_id,
        fixture_scene=None,
        vertical_scenario="notes_create",
    )


def run_l5_notes_observe(
    repo_root: Path, *, run_id: str = "l5-notes-observe"
) -> dict:
    return run_l3(
        repo_root,
        run_id=run_id,
        fixture_scene=None,
        vertical_scenario="notes_observe",
    )


def run_l5_notes_type(
    repo_root: Path, *, run_id: str = "l5-notes-type"
) -> dict:
    return run_l3(
        repo_root,
        run_id=run_id,
        fixture_scene=None,
        vertical_scenario="notes_type",
    )


def run_l5_notes_select(
    repo_root: Path, *, run_id: str = "l5-notes-select"
) -> dict:
    return run_l3(
        repo_root,
        run_id=run_id,
        fixture_scene=None,
        vertical_scenario="notes_select",
    )
