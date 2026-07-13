from __future__ import annotations

import json
import os
import plistlib
import subprocess
import time
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass(frozen=True)
class ProbeResult:
    target: str
    requested_effect: str
    dispatch_returned_success: bool
    independent_effect_seen: bool
    false_success_reproduced: bool
    supported_actions: tuple[str, ...]
    before_value: str | None
    after_value: str | None
    duration_ms: int


PROBE_TARGETS = ("fixture", "terminal", "safari", "chrome", "notes", "obsidian")


def _probe_artifact_path(output_dir: Path, target: str, state: str) -> Path:
    return output_dir / f"{target}-{state}-{time.time_ns()}.json"


def classify_fixture_probe(
    *, dispatch_returned_success: bool, truth_entries: list[dict],
    before_value: str | None, after_value: str | None,
    supported_actions: tuple[str, ...], duration_ms: int,
) -> ProbeResult:
    independent_effect_seen = bool(truth_entries) or before_value != after_value
    return ProbeResult(
        target="Reports success, no effect",
        requested_effect="fixture status changes",
        dispatch_returned_success=dispatch_returned_success,
        independent_effect_seen=independent_effect_seen,
        false_success_reproduced=(
            dispatch_returned_success and not independent_effect_seen
        ),
        supported_actions=supported_actions,
        before_value=before_value,
        after_value=after_value,
        duration_ms=duration_ms,
    )


def _truth_entries_after(entries: list[dict], *, started_ns: int) -> list[dict]:
    return [
        entry for entry in entries
        if isinstance(entry.get("monotonic_ns"), int)
        and entry["monotonic_ns"] >= started_ns
    ]


def _wait_for_truth_effect(path: Path, effect: str, *, timeout_s: float) -> bool:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if any(entry.get("effect") == effect for entry in _read_jsonl(path)):
            return True
        time.sleep(0.01)
    return False


def run_fixture_probe(repo_root: Path, data_dir: Path) -> ProbeResult:
    if _console_locked():
        output_dir = data_dir / "action-probes"
        output_dir.mkdir(parents=True, exist_ok=True)
        output = _probe_artifact_path(output_dir, "fixture", "blocked")
        output.write_text(json.dumps({
            "target": "fixture",
            "requested_effect": "reproduce AX success without visible effect",
            "outcome": "blocked",
            "engine_outcome": None,
            "independent_verdict": None,
            "reason": "console_locked",
            "console_locked": True,
            "duration_ms": 0,
            "strategy": None,
            "evidence": [{"kind": "environment", "summary": "Mac console is locked"}],
            "retry_decision": "rerun after console unlock",
        }, indent=2) + "\n")
        raise RuntimeError(
            "live action probe requires an unlocked Mac console; "
            f"unlock the Mac and rerun; artifact: {output}"
        )
    macos = repo_root / "macos"
    developer_dir = os.environ.get(
        "DEVELOPER_DIR", "/Applications/Xcode-beta.app/Contents/Developer"
    )
    subprocess.run(
        [str(macos / "make-fixture-app.sh")],
        cwd=macos,
        env={**os.environ, "DEVELOPER_DIR": developer_dir},
        check=True,
    )
    app = macos / ".build/fixture/ConnActionFixture.app"
    truth_path = data_dir / "action-probes" / "fixture-truth.jsonl"
    truth_path.parent.mkdir(parents=True, exist_ok=True)
    truth_path.unlink(missing_ok=True)
    _terminate_fixture_processes()
    existing: set[int] = set()
    process = subprocess.Popen(
        [
            "open", "-n", "-W", str(app),
            "--env", f"CONN_FIXTURE_TRUTH_LOG={truth_path}",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        fixture = _wait_for_fixture_process(existing)
        target, status = _wait_for_fixture(fixture.processIdentifier())
        before = _string_attr(status, "AXValue") or _string_attr(status, "AXTitle")
        actions = tuple(_action_names(target))
        baseline_entry_count = len(_read_jsonl(truth_path))
        started = time.monotonic()
        dispatch_success = _perform_press(target)
        time.sleep(0.35)
        after = _string_attr(status, "AXValue") or _string_attr(status, "AXTitle")
        entries = _read_jsonl(truth_path)[baseline_entry_count:]
        result = classify_fixture_probe(
            dispatch_returned_success=dispatch_success,
            truth_entries=entries,
            before_value=before,
            after_value=after,
            supported_actions=actions,
            duration_ms=int((time.monotonic() - started) * 1000),
        )
        output = _probe_artifact_path(
            data_dir / "action-probes", "fixture", "legacy"
        )
        output.write_text(json.dumps(asdict(result), indent=2) + "\n")
        print(json.dumps({**asdict(result), "artifact": str(output)}, indent=2))
        return result
    finally:
        if "fixture" in locals():
            fixture.terminate()
        process.terminate()
        try:
            process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            process.kill()


def run_verified_probe(repo_root: Path, data_dir: Path, target: str) -> dict:
    if target not in PROBE_TARGETS:
        raise RuntimeError(f"unsupported action probe: {target}")
    if _console_locked():
        artifact = _write_blocked_probe(data_dir, target)
        raise RuntimeError(
            "live action probe requires an unlocked Mac console; "
            f"unlock the Mac and rerun; artifact: {artifact}"
        )
    if target == "fixture":
        return _run_verified_fixture_probe(repo_root, data_dir)
    record = _run_native_probe_binary(repo_root, target)
    return _write_verified_probe(data_dir, target, record)


def _run_verified_fixture_probe(repo_root: Path, data_dir: Path) -> dict:
    macos = repo_root / "macos"
    developer_dir = os.environ.get(
        "DEVELOPER_DIR", "/Applications/Xcode-beta.app/Contents/Developer"
    )
    subprocess.run(
        [str(macos / "make-fixture-app.sh")],
        cwd=macos,
        env={**os.environ, "DEVELOPER_DIR": developer_dir},
        check=True,
    )
    app = macos / ".build/fixture/ConnActionFixture.app"
    truth_path = data_dir / "action-probes" / "verified-fixture-truth.jsonl"
    truth_path.parent.mkdir(parents=True, exist_ok=True)
    truth_path.unlink(missing_ok=True)
    _terminate_fixture_processes()
    launcher = subprocess.Popen(
        [
            "open", "-n", "-W", str(app),
            "--env", f"CONN_FIXTURE_TRUTH_LOG={truth_path}",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        fixture = _wait_for_fixture_process(set())
        if not _wait_for_truth_effect(
            truth_path, "fixture_ready", timeout_s=2.0
        ):
            raise RuntimeError("fixture did not report ready")
        started_ns = time.monotonic_ns()
        record = _run_native_probe_binary(repo_root, "fixture")
        time.sleep(0.15)
        truth_entries = _truth_entries_after(
            _read_jsonl(truth_path), started_ns=started_ns
        )
        engine_outcome = record.get("engine_outcome")
        independent_effect_seen = bool(truth_entries)
        record.update({
            "independent_effect_seen": independent_effect_seen,
            "independent_source": "fixture_truth_log",
            "independent_verdict": (
                "no_effect" if not independent_effect_seen else "effect_seen"
            ),
            "receipt_agrees": (
                engine_outcome == "no_effect" and not independent_effect_seen
            ),
            "truth_entries": truth_entries[:8],
        })
        return _write_verified_probe(data_dir, "fixture", record)
    finally:
        if "fixture" in locals():
            fixture.terminate()
        launcher.terminate()
        try:
            launcher.wait(timeout=2)
        except subprocess.TimeoutExpired:
            launcher.kill()


def _run_native_probe_binary(repo_root: Path, target: str) -> dict:
    binary = Path("/Applications/Conn.app/Contents/MacOS/Conn")
    release_binary = repo_root / "macos/.build/release/Conn"
    if not binary.exists():
        raise RuntimeError("Conn.app is not installed; run macos/make-app.sh install")
    if release_binary.exists() and binary.stat().st_mtime < release_binary.stat().st_mtime:
        raise RuntimeError(
            "installed Conn.app is older than the current build; "
            "run macos/make-app.sh install"
        )
    completed = subprocess.run(
        [str(binary), "--action-probe", target],
        check=True,
        capture_output=True,
        text=True,
        timeout=15,
    )
    lines = [line for line in completed.stdout.splitlines() if line.strip()]
    if not lines:
        raise RuntimeError("native action probe returned no record")
    try:
        record = json.loads(lines[-1])
    except json.JSONDecodeError as error:
        raise RuntimeError("native action probe returned invalid JSON") from error
    if not isinstance(record, dict):
        raise RuntimeError("native action probe returned a non-object record")
    return record


def _write_verified_probe(data_dir: Path, target: str, record: dict) -> dict:
    output_dir = data_dir / "action-probes"
    output_dir.mkdir(parents=True, exist_ok=True)
    outcome = record.get("outcome") or record.get("engine_outcome")
    state = outcome if isinstance(outcome, str) and outcome else "unclassified"
    output = _probe_artifact_path(output_dir, target, state)
    payload = {**record, "artifact": str(output)}
    output.write_text(json.dumps(payload, indent=2) + "\n")
    print(json.dumps(payload, indent=2))
    return payload


def _write_blocked_probe(data_dir: Path, target: str) -> Path:
    output_dir = data_dir / "action-probes"
    output_dir.mkdir(parents=True, exist_ok=True)
    output = _probe_artifact_path(output_dir, target, "blocked")
    output.write_text(json.dumps({
        "target": target,
        "requested_effect": "run a bounded verified semantic action",
        "outcome": "blocked",
        "engine_outcome": None,
        "independent_verdict": None,
        "reason": "console_locked",
        "console_locked": True,
        "duration_ms": 0,
        "strategy": None,
        "evidence": [{"kind": "environment", "summary": "Mac console is locked"}],
        "retry_decision": "rerun after console unlock",
    }, indent=2) + "\n")
    return output


def _console_locked() -> bool:
    try:
        result = subprocess.run(
            ["ioreg", "-n", "Root", "-d1", "-a"],
            check=True,
            capture_output=True,
        )
        roots = plistlib.loads(result.stdout)
        if isinstance(roots, dict):
            return bool(roots.get("IOConsoleLocked"))
        if isinstance(roots, list) and roots:
            return bool(roots[0].get("IOConsoleLocked"))
        return False
    except (OSError, subprocess.SubprocessError, plistlib.InvalidFileException):
        return False


def _fixture_processes() -> set[int]:
    from AppKit import NSRunningApplication

    return {
        int(app.processIdentifier())
        for app in NSRunningApplication.runningApplicationsWithBundleIdentifier_(
            "com.conn.ActionFixture"
        )
    }


def _terminate_fixture_processes() -> None:
    from AppKit import NSRunningApplication

    for app in NSRunningApplication.runningApplicationsWithBundleIdentifier_(
        "com.conn.ActionFixture"
    ):
        app.terminate()
    deadline = time.monotonic() + 2
    while _fixture_processes() and time.monotonic() < deadline:
        time.sleep(0.05)


def _wait_for_fixture_process(existing: set[int]):
    from AppKit import NSRunningApplication

    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        candidates = [
            app
            for app in NSRunningApplication.runningApplicationsWithBundleIdentifier_(
                "com.conn.ActionFixture"
            )
            if int(app.processIdentifier()) not in existing
        ]
        if candidates:
            return candidates[-1]
        time.sleep(0.05)
    raise RuntimeError("fixture process did not launch")


def _wait_for_fixture(pid: int):
    deadline = time.monotonic() + 5
    last_error = "fixture window unavailable"
    while time.monotonic() < deadline:
        try:
            app = _application(pid)
            root = _copy_attr(app, "AXFocusedWindow")
            if root is None:
                windows = _copy_attr(app, "AXWindows") or []
                root = windows[0] if windows else None
            if root is not None:
                target = _find(root, title="Reports success, no effect")
                status = _find(root, identifier="fixture.status")
                if target is not None and status is not None:
                    return target, status
        except Exception as error:
            last_error = str(error)
        time.sleep(0.05)
    raise RuntimeError(last_error)


def _application(pid: int):
    from ApplicationServices import AXIsProcessTrusted, AXUIElementCreateApplication

    if not AXIsProcessTrusted():
        raise RuntimeError("Python Accessibility permission is required for the fixture probe")
    return AXUIElementCreateApplication(pid)


def _copy_attr(element, attribute: str):
    from ApplicationServices import AXUIElementCopyAttributeValue

    error, value = AXUIElementCopyAttributeValue(element, attribute, None)
    return value if error == 0 else None


def _string_attr(element, attribute: str) -> str | None:
    value = _copy_attr(element, attribute)
    return str(value) if value is not None else None


def _find(element, *, title: str | None = None, identifier: str | None = None):
    queue = [(element, 0)]
    inspected = 0
    while queue and inspected < 500:
        current, depth = queue.pop(0)
        inspected += 1
        if title is not None:
            candidate = (
                _string_attr(current, "AXTitle")
                or _string_attr(current, "AXDescription")
            )
            if candidate == title:
                return current
        if identifier is not None and _string_attr(current, "AXIdentifier") == identifier:
            return current
        if depth < 15:
            queue.extend((child, depth + 1) for child in _copy_attr(current, "AXChildren") or [])
    return None


def _action_names(element) -> list[str]:
    from ApplicationServices import AXUIElementCopyActionNames

    error, names = AXUIElementCopyActionNames(element, None)
    return [str(name) for name in names] if error == 0 and names else []


def _perform_press(element) -> bool:
    from ApplicationServices import AXUIElementPerformAction, kAXPressAction

    return AXUIElementPerformAction(element, kAXPressAction) == 0


def _read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line]
