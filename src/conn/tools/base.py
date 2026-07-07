from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from ..config import Config

if TYPE_CHECKING:
    from .ax import SnapshotStore


class ToolError(Exception):
    """Raised by executors for expected, reportable failures."""


@dataclass
class ExecutionContext:
    cfg: Config
    screenshot_dir: Path
    ax: SnapshotStore | None = None
    mcp: object | None = None
