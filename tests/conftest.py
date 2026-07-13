from __future__ import annotations

import pytest

from conn.config import Config
from conn.tools.ax import FakeAxBackend, RawNode, SnapshotStore
from conn.tools.base import ExecutionContext
from conn.tools.harness import ToolHarness
from conn.tools.registry import build_registry


@pytest.fixture
def cfg(tmp_path):
    c = Config()
    c.data_dir = tmp_path / "data"
    c.apps.allowlist = ["Obsidian", "Google Chrome", "Safari"]
    c.apps.bundle_ids = {
        "Obsidian": "md.obsidian",
        "Google Chrome": "com.google.Chrome",
        "Safari": "com.apple.Safari",
    }
    c.apps.team_ids = {"Obsidian": "6JSW4SJWN9"}
    c.phoenix.vault_root = str(tmp_path / "vault")
    (tmp_path / "vault").mkdir()
    return c


@pytest.fixture
def ctx(cfg, tmp_path):
    tree = RawNode(
        role="AXWindow",
        title="Fixture Window",
        children=(
            RawNode(role="AXButton", title="Send"),
            RawNode(role="AXTextField", title="Body"),
            RawNode(role="AXScrollArea", title="Results", children=(RawNode(role="AXStaticText", title="Target"),)),
        ),
    )
    store = SnapshotStore(FakeAxBackend("com.apple.TextEdit", 42, tree), cfg)
    return ExecutionContext(cfg=cfg, screenshot_dir=tmp_path / "shots", ax=store)


@pytest.fixture
def harness(cfg, ctx):
    return ToolHarness(build_registry(), cfg, ctx)
