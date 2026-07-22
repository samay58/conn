from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

from .models import (
    ArtifactManifest,
    LabRun,
    OracleResult,
    OracleVerdict,
    RunStatus,
    ScenarioManifest,
)


PINNED_TART_VERSION = "2.32.1"
PINNED_BASE_IMAGE = (
    "ghcr.io/cirruslabs/macos-tahoe-base@"
    "sha256:a8e1c8305758643f513fdccdd829c2243687c60791083dea42f73f0b7aeb435c"
)
SIGNING_IDENTITY = "Conn Dev Signing"


@dataclass(frozen=True, slots=True)
class BuildIdentity:
    guest_os_build: str
    tart_version: str
    image_digest: str
    conn_commit: str
    dirty_tree_digest: str
    binary_sha256: str
    signing_identity: str


def write_run_records(
    artifact_dir: Path,
    *,
    run_id: str,
    manifest: ScenarioManifest,
    result: dict,
    started_ms: int,
    finished_ms: int,
    identity: BuildIdentity,
) -> None:
    oracle_value = result.get("independent_oracle")
    if not isinstance(oracle_value, dict):
        raise RuntimeError("lab_oracle_record_missing")
    try:
        oracle_verdict = OracleVerdict(oracle_value.get("verdict"))
    except ValueError as error:
        raise RuntimeError("lab_oracle_record_invalid") from error
    passed = result.get("passed") is True
    run = LabRun(
        run_id=run_id,
        scenario_id=manifest.id,
        scenario_digest=manifest.digest,
        vm_name=f"conn-lab-{run_id}",
        mode=manifest.mode,
        status=RunStatus.PASSED if passed else RunStatus.FAILED,
        started_ms=started_ms,
        finished_ms=finished_ms,
        artifact_dir=run_id,
        failure_reason=None if passed else "scenario_contract_not_met",
    )
    oracle = OracleResult(
        run_id=run_id,
        scenario_id=manifest.id,
        kind=manifest.oracle.kind,
        verdict=oracle_verdict,
        expected=manifest.oracle.expected,
        actual=oracle_value,
        reason=None,
    )
    artifact = ArtifactManifest(
        run_id=run_id,
        scenario_id=manifest.id,
        scenario_digest=manifest.digest,
        guest_os_build=identity.guest_os_build,
        tart_version=identity.tart_version,
        image_digest=identity.image_digest,
        conn_commit=identity.conn_commit,
        dirty_tree_digest=identity.dirty_tree_digest,
        binary_sha256=identity.binary_sha256,
        signing_identity=identity.signing_identity,
    )
    for filename, model in (
        ("lab-run.json", run),
        ("oracle-result.json", oracle),
        ("artifact-manifest.json", artifact),
    ):
        _atomic_write(artifact_dir / filename, model.model_dump_json(indent=2) + "\n")


@lru_cache(maxsize=8)
def collect_build_identity(root: Path, *, guest_os_build: str) -> BuildIdentity:
    root = root.resolve(strict=True)
    tart = shutil.which("tart")
    if tart is None:
        raise RuntimeError("lab_tart_missing")
    tart_version = _run_text([tart, "--version"], cwd=root)
    if tart_version != PINNED_TART_VERSION:
        raise RuntimeError("lab_tart_version_mismatch")
    commit = _run_text(["git", "rev-parse", "HEAD"], cwd=root)
    binary = root / "macos" / "Conn.app" / "Contents" / "MacOS" / "Conn"
    binary_sha256 = _file_sha256(binary)
    signing = _run_text([
        "/usr/bin/codesign",
        "-dv",
        "--verbose=2",
        str(root / "macos" / "Conn.app"),
    ], cwd=root, stderr=True)
    authorities = [
        line.removeprefix("Authority=")
        for line in signing.splitlines()
        if line.startswith("Authority=")
    ]
    if SIGNING_IDENTITY not in authorities:
        raise RuntimeError("lab_signing_identity_mismatch")
    return BuildIdentity(
        guest_os_build=guest_os_build,
        tart_version=tart_version,
        image_digest=PINNED_BASE_IMAGE.rsplit("@", 1)[1],
        conn_commit=commit,
        dirty_tree_digest=dirty_tree_digest(root),
        binary_sha256=binary_sha256,
        signing_identity=SIGNING_IDENTITY,
    )


def dirty_tree_digest(root: Path) -> str:
    root = root.resolve(strict=True)
    digest = hashlib.sha256()
    diff = subprocess.run(
        ["git", "diff", "--binary", "HEAD", "--", "."],
        cwd=root,
        check=True,
        capture_output=True,
    ).stdout
    digest.update(diff)
    untracked = subprocess.run(
        ["git", "ls-files", "--others", "--exclude-standard", "-z"],
        cwd=root,
        check=True,
        capture_output=True,
    ).stdout.split(b"\0")
    for raw in sorted(value for value in untracked if value):
        relative = os.fsdecode(raw)
        if relative == ".build" or relative.startswith(".build/"):
            continue
        path = root / relative
        digest.update(raw)
        digest.update(b"\0")
        if path.is_symlink():
            digest.update(os.readlink(path).encode())
        elif path.is_file():
            with path.open("rb") as handle:
                for chunk in iter(lambda: handle.read(1_048_576), b""):
                    digest.update(chunk)
        digest.update(b"\0")
    return digest.hexdigest()


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1_048_576), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _run_text(
    argv: list[str],
    *,
    cwd: Path,
    stderr: bool = False,
) -> str:
    result = subprocess.run(
        argv,
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
    )
    return (result.stderr if stderr else result.stdout).strip()


def _atomic_write(path: Path, content: str) -> None:
    descriptor, temporary = tempfile.mkstemp(
        prefix=f".{path.name}.",
        dir=path.parent,
    )
    try:
        with os.fdopen(descriptor, "w") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except BaseException:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        raise
