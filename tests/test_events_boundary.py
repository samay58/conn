from __future__ import annotations

import ast
import types
from pathlib import Path
from typing import get_args

from conn import events


REPO_ROOT = Path(__file__).resolve().parents[1]
EVENTS_PATH = REPO_ROOT / "src" / "conn" / "events.py"
STATE_PATH = REPO_ROOT / "src" / "conn" / "state.py"


def _union_members(union: object) -> set[type]:
    return {member for member in get_args(union) if isinstance(member, type)}


def _state_imports_from_events() -> set[str]:
    tree = ast.parse(STATE_PATH.read_text())
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module == "events":
            names.update(alias.name for alias in node.names)
    return names


def test_events_does_not_import_behavior_layers() -> None:
    tree = ast.parse(EVENTS_PATH.read_text())
    blocked = {"state", "app", "tools", "server", "ui"}
    imports: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.append(node.module)

    assert all(not name.startswith(tuple(blocked)) for name in imports)


def test_state_protocol_members_are_exported_from_events() -> None:
    imported = _state_imports_from_events()
    machine_inputs = _union_members(events.MachineInput)
    commands = _union_members(events.Command)

    for name in imported:
        value = getattr(events, name)
        if isinstance(value, type) and value.__module__ == events.__name__:
            if name.endswith(("Input", "Tick", "Decision", "Timeout", "Speaking",
                              "Done", "Cancelled", "Drained", "Failed",
                              "Reconnected", "Tripped", "Override", "Stop",
                              "Command", "Proposed", "Finished")):
                assert value in machine_inputs or value in commands or name in {
                    "Gate",
                    "ToolCall",
                }


def test_reject_and_watchdog_stay_in_events_boundary() -> None:
    assert events.RejectInput in _union_members(events.Command)
    assert events.WatchdogTick in _union_members(events.MachineInput)
    assert isinstance(events.MachineInput, types.UnionType)
    assert isinstance(events.Command, types.UnionType)
