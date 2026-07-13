"""JSONL trace, one file per session. Every event that matters for debugging or
evals lands here: inputs, proposals, gate decisions, approvals with latency,
results with duration, per-turn usage, barge-ins, budget events, the receipt.

Schema v2 adds latency-instrumentation kinds, all written through the same
log(kind, **payload) call:
- ptt_down / ptt_up: {client_ts_ms: int | None, source: "hotkey" | "console" | "panel"}
- phase_change: {from_phase: str, to_phase: str, turn: int}, every transition
- model_delta: {response_id: str, modality: "audio" | "text"}, first delta per response only
- audio_silent: {after: "flush" | "drain"}, from the playback callback
- ui_ack: {moment: "listening" | "thinking" | "chip", client_ts_ms: int}

Traces are local, gitignored, and readable line by line.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from datetime import datetime
from pathlib import Path

TRACE_SCHEMA_VERSION = 3


def _git_commit(start: Path) -> str | None:
    """Best-effort HEAD commit without a subprocess: walk up to the repo
    root, then follow .git/HEAD through loose refs or packed-refs."""
    for parent in (start, *start.parents):
        git_dir = parent / ".git"
        if git_dir.is_dir():
            break
    else:
        return None
    try:
        head = (git_dir / "HEAD").read_text().strip()
        if not head.startswith("ref: "):
            return head if len(head) == 40 else None
        ref = head[len("ref: "):]
        loose = git_dir / ref
        if loose.exists():
            return loose.read_text().strip() or None
        packed = git_dir / "packed-refs"
        if packed.exists():
            for line in packed.read_text().splitlines():
                if line.endswith(ref) and not line.startswith(("#", "^")):
                    return line.split(" ", 1)[0]
    except OSError:
        return None
    return None


def runtime_identity(config_path: Path | None) -> dict:
    """The identity block every session trace starts with: which process,
    which code, which config. Fields are None when unknowable, never absent."""
    fingerprint = None
    if config_path is not None:
        path = Path(config_path)
        if path.exists():
            fingerprint = hashlib.sha256(path.read_bytes()).hexdigest()
    return {
        "pid": os.getpid(),
        "parent_pid": os.getppid(),
        "trace_schema": TRACE_SCHEMA_VERSION,
        "commit": _git_commit(Path(__file__).resolve()),
        "config_fingerprint": fingerprint,
    }


class TraceWriter:
    def __init__(self, data_dir: Path, session_id: str):
        day = datetime.now().strftime("%Y-%m-%d")
        self.dir = data_dir / "traces" / day
        self.dir.mkdir(parents=True, exist_ok=True)
        self.path = self.dir / f"{session_id}.jsonl"
        self.session_id = session_id
        self._listeners = []

    def log(self, kind: str, **payload) -> dict:
        event = {"ts": round(time.time(), 3), "kind": kind, **payload}
        with open(self.path, "a") as f:
            f.write(json.dumps(event, default=str) + "\n")
        for listener in self._listeners:
            listener(event)
        return event

    def subscribe(self, fn) -> None:
        """Console bus hook: called synchronously with each event dict."""
        self._listeners.append(fn)

    def read(self) -> list[dict]:
        if not self.path.exists():
            return []
        return [json.loads(line) for line in self.path.read_text().splitlines() if line]


def write_receipt(data_dir: Path, session_id: str, receipt: dict) -> Path:
    """Write the receipt atomically: a kill mid-write must never leave a
    truncated file where a prior valid receipt used to be, since incremental
    receipts (Defect 8) exist exactly to survive a killed-mid-session
    process. Write to a temp file in the same directory, then os.replace
    onto the real path (atomic on APFS)."""
    day = datetime.now().strftime("%Y-%m-%d")
    out_dir = data_dir / "receipts" / day
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{session_id}.json"
    tmp_path = out_dir / f".{session_id}.json.tmp"
    tmp_path.write_text(json.dumps(receipt, indent=2))
    os.replace(tmp_path, path)
    return path
