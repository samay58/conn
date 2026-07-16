from __future__ import annotations

import argparse
from datetime import datetime
import json
import math
import os
from pathlib import Path
import re
import secrets
import shutil
import stat
import subprocess
import sys

from .catalog import driver_config, load_catalog
from .records import PINNED_BASE_IMAGE, PINNED_TART_VERSION, SIGNING_IDENTITY
from .scenario import run_l3
from .suite import run_scripted_matrix, run_smoke_suite


GOLDEN_VM = "conn-lab-golden"
_TIMING_KEYS = (
    "clone_ms",
    "boot_ms",
    "install_ms",
    "scenario_ms",
    "export_ms",
    "cleanup_ms",
    "total_ms",
)
_RUN_ID = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
_REPORT_IDENTIFIER = re.compile(r"^[a-z][a-z0-9_-]{0,127}$")


def repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m conn.lab",
        description="Run Conn in an isolated disposable macOS guest.",
    )
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("doctor", help="check the pinned lab environment")
    commands.add_parser(
        "bootstrap",
        help="create the golden guest before its one-time permission setup",
    )

    run = commands.add_parser("run", help="run one scenario in a fresh guest")
    run.add_argument("scenario", choices=tuple(load_catalog(repo_root())))
    run.add_argument("--mode", choices=("scripted", "live"), default="scripted")
    run.add_argument(
        "--fresh",
        action="store_true",
        help="require a fresh clone; all lab runs are fresh",
    )

    suite = commands.add_parser("suite", help="run a frozen lab suite")
    suite.add_argument("suite", choices=("smoke", "release"))

    report = commands.add_parser("report", help="print one bounded run report")
    report.add_argument("run_id")
    return parser


def load_run_report(root: Path, run_id: str) -> dict:
    if len(run_id) > 64 or not _RUN_ID.fullmatch(run_id):
        raise RuntimeError("lab_run_id_invalid")
    matches = sorted(
        path.parent
        for path in (root / "data" / "lab-runs").glob(
            f"*/{run_id}/vertical-result.json"
        )
    )
    if not matches:
        raise RuntimeError("lab_run_not_found")
    if len(matches) != 1:
        raise RuntimeError("lab_run_ambiguous")
    run_dir = matches[0]
    result = _read_object(run_dir / "vertical-result.json")
    runner = _read_object(run_dir / "runner-timings.json")
    scenario = _read_object(run_dir / "scenario-timings.json")
    receipt = result.get("machine_receipt") or {}
    oracle = result.get("independent_oracle") or {}
    cost = result.get("cost") or {}
    timings = runner | scenario
    return {
        "run_id": run_id,
        "scenario": _report_text(result.get("scenario")),
        "mode": _report_text(result.get("model_mode")),
        "receipt": {
            "outcome": _report_text(receipt.get("outcome")),
            "reason_code": _report_text(
                receipt.get("reason_code"),
                optional=True,
            ),
        },
        "oracle": {
            "verdict": _report_text(oracle.get("verdict")),
            "effect": _report_text(oracle.get("effect")),
            "effect_count": _report_count(oracle.get("effect_count")),
        },
        "transaction_count": _report_count(result.get("transaction_count")),
        "dispatch_count": _report_count(result.get("dispatch_count")),
        "cost_usd": _report_cost(cost.get("estimated_usd")),
        "timings_ms": {
            key: _report_count(timings.get(key), ceiling=3_600_000)
            for key in _TIMING_KEYS
        },
    }


def doctor(root: Path) -> dict:
    failures: list[str] = []
    tart = shutil.which("tart")
    version = _output([tart, "--version"]) if tart else None
    if version != PINNED_TART_VERSION:
        failures.append("tart_version")
    softnet = shutil.which("softnet")
    softnet_ready = _softnet_ready(softnet)
    vms = _tart_vms(tart) if tart else []
    vm_names = {
        item.get("Name"): item
        for item in vms
        if isinstance(item, dict) and isinstance(item.get("Name"), str)
    }
    golden = vm_names.get(GOLDEN_VM)
    if not golden or golden.get("State") != "stopped":
        failures.append("golden_vm")
    if PINNED_BASE_IMAGE not in vm_names:
        failures.append("base_image")

    app = root / "macos" / "Conn.app"
    fixture = (
        root / "macos" / ".build" / "fixture" / "ConnActionFixture.app"
    )
    signing = _output([
        "/usr/bin/codesign",
        "-dv",
        "--verbose=2",
        str(app),
    ], stderr=True) if app.exists() else ""
    if f"Authority={SIGNING_IDENTITY}" not in signing:
        failures.append("signing_identity")
    if not fixture.exists():
        failures.append("fixture_app")

    free_bytes = shutil.disk_usage(root).free
    if free_bytes < 100 * 1024**3:
        failures.append("disk_space")
    artifact_root = root / "data" / "lab-runs"
    artifact_root.mkdir(parents=True, exist_ok=True)
    writable = os.access(artifact_root, os.W_OK)
    if not writable:
        failures.append("artifact_root")
    return {
        "ok": not failures,
        "failures": failures,
        "tart_version": version,
        "network_mode": "default_nat",
        "softnet_privileged": softnet_ready,
        "base_image": PINNED_BASE_IMAGE in vm_names,
        "golden_vm": golden.get("State") if golden else "missing",
        "signing_identity": SIGNING_IDENTITY in signing,
        "fixture_app": fixture.exists(),
        "disk_free_gb": round(free_bytes / 1024**3, 1),
        "artifact_root_writable": writable,
    }


def bootstrap(root: Path) -> dict:
    report = doctor(root)
    if report["golden_vm"] == "stopped":
        return {
            "ok": report["ok"],
            "status": "already_ready",
            "doctor": report,
        }
    if report["tart_version"] != PINNED_TART_VERSION:
        raise RuntimeError("bootstrap_requires_pinned_tart")
    if not report["base_image"]:
        _required(["tart", "clone", PINNED_BASE_IMAGE, GOLDEN_VM], 3_600)
    else:
        _required(["tart", "clone", PINNED_BASE_IMAGE, GOLDEN_VM], 600)
    _required([
        "tart",
        "set",
        GOLDEN_VM,
        "--cpu",
        "4",
        "--memory",
        "12288",
        "--disk-size",
        "80",
        "--display",
        "1440x900",
        "--no-display-refit",
    ], 120)
    return {
        "ok": False,
        "status": "tcc_setup_required",
        "next": (
            "Run the golden guest graphically, install the signed Conn.app, "
            "approve Accessibility and Screen Recording once, then stop it."
        ),
    }


def run_scenario(
    root: Path,
    *,
    scenario: str,
    mode: str,
    run_id: str | None = None,
) -> dict:
    manifest = load_catalog(root)[scenario]
    driver_config(manifest)
    actual_run_id = run_id or _new_run_id(scenario)
    return run_l3(
        root,
        run_id=actual_run_id,
        model_mode=mode,
        manifest=manifest,
    )


def run_suite(root: Path, name: str) -> dict:
    runs = 1 if name == "smoke" else 20
    prefix = f"lab-{name}-{datetime.now().strftime('%H%M%S')}"
    smoke = run_smoke_suite(root, runs=runs, run_prefix=prefix)
    matrix = run_scripted_matrix(iterations=100)
    passed = smoke["passed"] and matrix["passed"] == 100
    result = {
        "suite": name,
        "passed": passed,
        "fresh_clone_runs": runs,
        "smoke": smoke,
        "scripted_matrix": matrix,
    }
    output = (
        root
        / "data"
        / "lab-runs"
        / datetime.now().date().isoformat()
        / f"{prefix}-suite.json"
    )
    output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    return result


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    root = repo_root()
    try:
        if args.command == "doctor":
            result = doctor(root)
        elif args.command == "bootstrap":
            result = bootstrap(root)
        elif args.command == "run":
            _build_candidate(root)
            result = run_scenario(
                root,
                scenario=args.scenario,
                mode=args.mode,
            )
        elif args.command == "suite":
            _build_candidate(root)
            result = run_suite(root, args.suite)
        else:
            result = load_run_report(root, args.run_id)
    except (OSError, RuntimeError, subprocess.SubprocessError) as error:
        print(str(error), file=sys.stderr)
        return 2
    print(json.dumps(result, indent=2, sort_keys=True))
    if args.command == "doctor":
        return 0 if result["ok"] else 1
    if args.command == "bootstrap":
        return 0 if result["ok"] else 3
    if args.command == "suite":
        return 0 if result["passed"] else 1
    return 0


def _build_candidate(root: Path) -> None:
    _required([str(root / "macos" / "make-app.sh")], 600, cwd=root / "macos")


def _new_run_id(scenario: str) -> str:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    return f"lab-{scenario}-{stamp}-{secrets.token_hex(3)}"


def _read_object(path: Path) -> dict:
    try:
        value = json.loads(path.read_text())
    except (OSError, ValueError) as error:
        raise RuntimeError(f"lab_report_invalid:{path.name}") from error
    if not isinstance(value, dict):
        raise RuntimeError(f"lab_report_invalid:{path.name}")
    return value


def _report_text(value, *, optional: bool = False) -> str | None:
    if optional and value is None:
        return None
    if not isinstance(value, str) or not _REPORT_IDENTIFIER.fullmatch(value):
        raise RuntimeError("lab_report_invalid:field")
    return value


def _report_count(value, *, ceiling: int = 10_000) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise RuntimeError("lab_report_invalid:field")
    if not 0 <= value <= ceiling:
        raise RuntimeError("lab_report_invalid:field")
    return value


def _report_cost(value) -> float:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(value)
        or not 0 <= value <= 1_000_000
    ):
        raise RuntimeError("lab_report_invalid:field")
    return value


def _output(argv: list[str | None], *, stderr: bool = False) -> str:
    if not all(isinstance(item, str) and item for item in argv):
        return ""
    result = subprocess.run(
        argv,
        check=False,
        capture_output=True,
        text=True,
        timeout=10,
    )
    stream = result.stderr if stderr else result.stdout
    return stream.strip()


def _tart_vms(tart: str) -> list:
    try:
        value = json.loads(_output([tart, "list", "--format", "json"]))
    except ValueError:
        return []
    return value if isinstance(value, list) else []


def softnet_is_privileged(file_stat, *, sudo_works: bool) -> bool:
    root_suid = (
        file_stat is not None
        and file_stat.st_uid == 0
        and bool(file_stat.st_mode & stat.S_ISUID)
    )
    return root_suid or sudo_works


def _softnet_ready(path: str | None) -> bool:
    if not path:
        return False
    try:
        file_stat = Path(path).resolve(strict=True).stat()
    except OSError:
        return False
    sudo = subprocess.run(
        ["/usr/bin/sudo", "-n", path, "--help"],
        check=False,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        timeout=5,
    )
    return softnet_is_privileged(file_stat, sudo_works=sudo.returncode == 0)


def _required(
    argv: list[str],
    timeout_s: float,
    *,
    cwd: Path | None = None,
) -> None:
    subprocess.run(
        argv,
        cwd=cwd,
        check=True,
        timeout=timeout_s,
    )
