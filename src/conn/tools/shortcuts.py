"""Run Samay's own Apple Shortcuts through /usr/bin/shortcuts.

Apps publish their actions to Shortcuts and keep them working across their
own updates, so a Shortcut gives Conn depth in an app without a click script
that breaks when the app's screen changes. Conn cannot see what a Shortcut
will do, so every run waits for a pointer approval (the registry marks it
act_confirm), and a finished run proves only that it ran: its effects belong
to the Shortcut and are not verified here.
"""

from __future__ import annotations

import difflib
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

from .base import ExecutionContext, ToolError

SHORTCUTS_BIN = "/usr/bin/shortcuts"
NAME_MAX_CHARS = 200
INPUT_MAX_CHARS = 4000
OUTPUT_MAX_CHARS = 1000
LIST_MAX = 300
LIST_TIMEOUT_S = 10.0

# A Shortcut can run shell scripts. It gets a plain user environment, never
# the daemon's API key, bridge token, or console capability.
_ENV_KEYS = {"HOME", "LANG", "LC_ALL", "LC_CTYPE", "PATH", "TMPDIR", "USER"}


def _env() -> dict[str, str]:
    return {key: value for key, value in os.environ.items() if key in _ENV_KEYS}


def list_names() -> list[str]:
    try:
        proc = subprocess.run(
            [SHORTCUTS_BIN, "list"], capture_output=True, text=True,
            timeout=LIST_TIMEOUT_S, env=_env(),
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ToolError(f"shortcuts_unavailable: {type(exc).__name__}") from exc
    if proc.returncode != 0:
        detail = (proc.stderr or "").strip()[:200] or f"exit {proc.returncode}"
        raise ToolError(f"shortcuts_unavailable: {detail}")
    names: list[str] = []
    for line in proc.stdout.splitlines():
        name = line.strip()
        if name and name not in names:
            names.append(name)
    return names


def resolve_name(requested: str, names: list[str]) -> str:
    """Exact name first, then one case-insensitive match. Anything else is
    refused with the closest names so the model can ask, never guess."""
    if requested in names:
        return requested
    folded = [name for name in names if name.casefold() == requested.casefold()]
    if len(folded) == 1:
        return folded[0]
    if len(folded) > 1:
        raise ToolError(
            f"shortcut_ambiguous: {requested!r} matches {', '.join(folded[:5])}"
        )
    by_fold = {name.casefold(): name for name in names}
    close = difflib.get_close_matches(
        requested.casefold(), list(by_fold), n=3, cutoff=0.5
    )
    hint = f" Closest: {', '.join(by_fold[c] for c in close)}." if close else ""
    raise ToolError(f"shortcut_not_found: {requested!r}.{hint}")


def _read_output(path: Path) -> str | None:
    if not path.exists() or path.stat().st_size == 0:
        return None
    raw = path.read_bytes()
    try:
        text = raw.decode("utf-8").strip()
    except UnicodeDecodeError:
        return f"[non-text output, {len(raw)} bytes]"
    if len(text) > OUTPUT_MAX_CHARS:
        text = text[:OUTPUT_MAX_CHARS] + "…"
    return text or None


def shortcuts_list(args: dict, ctx: ExecutionContext) -> dict:
    names = list_names()
    return {"count": len(names), "shortcuts": names[:LIST_MAX]}


def shortcuts_run(args: dict, ctx: ExecutionContext) -> dict:
    name = resolve_name(str(args["name"]).strip(), list_names())
    text = args.get("input")
    work = Path(tempfile.mkdtemp(prefix="conn-shortcut-"))
    output_path = work / "output"
    argv = [SHORTCUTS_BIN, "run", name, "--output-path", str(output_path)]
    if text:
        input_path = work / "input.txt"
        input_path.write_text(str(text), encoding="utf-8")
        argv += ["--input-path", str(input_path)]
    try:
        proc = subprocess.Popen(
            argv, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE, text=True, env=_env(),
        )
    except OSError as exc:
        shutil.rmtree(work, ignore_errors=True)
        raise ToolError(f"shortcuts_unavailable: {type(exc).__name__}") from exc
    try:
        _stdout, stderr = proc.communicate(timeout=ctx.cfg.shortcuts.run_timeout_s)
    except subprocess.TimeoutExpired:
        # Never kill a running Shortcut: stopping it halfway could leave its
        # effects half done. Its temp files stay until the OS clears them.
        return {
            "shortcut": name,
            "status": "still_running",
            "safe_user_message": f"{name} is still running.",
        }
    try:
        if proc.returncode != 0:
            detail = (stderr or "").strip()[:300] or f"exit {proc.returncode}"
            raise ToolError(f"shortcut_failed: {name}: {detail}")
        output = _read_output(output_path)
    finally:
        shutil.rmtree(work, ignore_errors=True)
    result = {
        "shortcut": name,
        "status": "finished",
        "safe_user_message": f"Ran {name}.",
    }
    if output is not None:
        result["output"] = output
    return result
