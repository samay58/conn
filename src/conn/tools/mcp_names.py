"""Model-facing names for configured MCP tools. A leaf module so risk.py and
the bridge can share it without an import cycle."""

from __future__ import annotations

import hashlib
import re

NAME_MAX = 64


def normalize_name(name: str) -> str:
    name = re.sub(r"[^a-zA-Z0-9_-]", "_", name)
    if len(name) > NAME_MAX:
        name = name[:NAME_MAX - 5] + "_" + hashlib.sha1(name.encode()).hexdigest()[:4]
    return name


def conn_name(server: str, tool: str, alias: str = "") -> str:
    return normalize_name(alias or f"{server}_{tool}")
