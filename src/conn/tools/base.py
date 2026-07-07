from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from ..config import Config

if TYPE_CHECKING:
    from .ax import SnapshotStore


class ToolError(Exception):
    """Raised by executors for expected, reportable failures."""


# Shared by the risk gate (proposal time) and the AX executors (execution
# time): both must agree on whether a human app name matches the frontmost
# bundle id, or the gate blocks what the executor would have allowed.
APP_BUNDLE_ALIASES = {
    "Google Chrome": {"com.google.Chrome"},
    "Safari": {"com.apple.Safari"},
    "Obsidian": {"md.obsidian"},
}


def app_matches_bundle(app: str, bundle_id: str) -> bool:
    if app == bundle_id or bundle_id in APP_BUNDLE_ALIASES.get(app, set()):
        return True
    # The model names apps the human way ("Terminal", "Kaku"); the alias map
    # cannot enumerate every app, so match the bundle id's last component
    # against the normalized name.
    tail = bundle_id.rsplit(".", 1)[-1].lower()
    return bool(tail) and tail == app.lower().replace(" ", "")


@dataclass
class ExecutionContext:
    cfg: Config
    screenshot_dir: Path
    ax: SnapshotStore | None = None
    mcp: object | None = None
