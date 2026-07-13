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
    "Finder": {"com.apple.finder"},
    "Notes": {"com.apple.Notes"},
    "Terminal": {"com.apple.Terminal"},
}


def app_matches_bundle(
    app: str,
    bundle_id: str,
    configured_bundle_ids: dict[str, str] | None = None,
) -> bool:
    if app == bundle_id:
        return True
    if configured_bundle_ids is not None:
        return configured_bundle_ids.get(app) == bundle_id
    return bundle_id in APP_BUNDLE_ALIASES.get(app, set())


@dataclass
class ExecutionContext:
    cfg: Config
    screenshot_dir: Path
    ax: SnapshotStore | None = None
    mcp: object | None = None
    # AxBridge when the daemon serves an app client: context reads route
    # through the app's Accessibility grant (TCC binds to the binary, and
    # the grant lives on Conn.app, not on the spawned python).
    ax_reader: object | None = None
