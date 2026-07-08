"""T4: computer_hotkey and app_menu ride Conn.app's Accessibility grant over
the websocket when the app is attached; the python lane stays the fallback
when it is not; wire failures refuse instead of silently switching lanes.
"""

from __future__ import annotations

import pytest

import conn.tools.ax_input as ax_input
from conn.tools.ax_input import (
    AppLaneInputBackend, FakeInputBackend, _menu_node_from_wire,
    _posting_backend, hotkey, menu,
)
from conn.tools.base import ToolError


class FakeBridge:
    def __init__(self, responses, app_present=True):
        self.responses = responses
        self.app_present = app_present
        self.calls = []

    def request_action_sync(self, op, params):
        self.calls.append((op, params))
        return self.responses.get(op)


MENU_TREE = {
    "title": "",
    "children": [
        {"title": "File", "children": [
            {"title": "New Tab", "children": []},
            {"title": "Close Window", "children": []},
        ]},
        {"title": "Edit", "children": []},
    ],
}


def test_hotkey_rides_app_lane_when_attached(ctx):
    bridge = FakeBridge({"posting_capability": True, "key_chord": True})
    ctx.ax_reader = bridge
    result = hotkey({"combo": "cmd+t"}, ctx)
    assert result == {"combo": "cmd+t", "lane": "app"}
    assert ("key_chord", {"keys": ["cmd", "t"]}) in bridge.calls


def test_app_lane_untrusted_refusal_names_conn_app(ctx):
    ctx.ax_reader = FakeBridge({"posting_capability": False})
    with pytest.raises(ToolError, match="app lane") as excinfo:
        hotkey({"combo": "cmd+t"}, ctx)
    assert "Conn.app" in str(excinfo.value)
    assert "accessibility_untrusted" in str(excinfo.value)


def test_app_lane_wire_failure_refuses_without_fallback(ctx):
    bridge = FakeBridge({"posting_capability": True, "key_chord": None})
    ctx.ax_reader = bridge
    with pytest.raises(ToolError, match="app_lane_error"):
        hotkey({"combo": "cmd+t"}, ctx)


def test_python_fallback_when_no_app_attached(ctx, monkeypatch):
    fake = FakeInputBackend()
    monkeypatch.setattr(ax_input, "_input_backend", lambda _ctx: fake)
    ctx.ax_reader = FakeBridge({}, app_present=False)
    result = hotkey({"combo": "cmd+t"}, ctx)
    assert result["lane"] == "python"
    assert fake.actions == [{"kind": "key_chord", "keys": ("cmd", "t")}]


def test_injected_backend_wins_over_bridge(ctx):
    fake = FakeInputBackend()
    ctx.input_backend = fake
    ctx.ax_reader = FakeBridge({"posting_capability": True, "key_chord": True})
    assert _posting_backend(ctx) is fake


def test_menu_rides_app_lane(ctx):
    bridge = FakeBridge({
        "posting_capability": True,
        "menu_tree": MENU_TREE,
        "press_menu_path": True,
    })
    ctx.ax_reader = bridge
    result = menu({"path": ["File", "New Tab"]}, ctx)
    assert result == {"pressed": ["File", "New Tab"]}
    assert ("press_menu_path", {"pid": 42, "titles": ["File", "New Tab"]}) in bridge.calls


def test_menu_tree_unreadable_refuses(ctx):
    ctx.ax_reader = FakeBridge({"posting_capability": True, "menu_tree": None})
    with pytest.raises(ToolError, match="app_lane_error"):
        menu({"path": ["File", "New Tab"]}, ctx)


def test_menu_press_failure_surfaces(ctx):
    ctx.ax_reader = FakeBridge({
        "posting_capability": True,
        "menu_tree": MENU_TREE,
        "press_menu_path": False,
    })
    with pytest.raises(ToolError, match="menu_press_failed"):
        menu({"path": ["File", "New Tab"]}, ctx)


def test_menu_node_from_wire_rejects_malformed():
    assert _menu_node_from_wire(None) is None
    assert _menu_node_from_wire(["not", "a", "dict"]) is None
    node = _menu_node_from_wire({"title": "File", "children": "garbage"})
    assert node.title == "File"
    assert node.children == ()


def test_menu_node_from_wire_caps_depth():
    tree: dict = {"title": "root", "children": []}
    leaf = tree
    for index in range(20):
        child: dict = {"title": f"level{index}", "children": []}
        leaf["children"] = [child]
        leaf = child
    node = _menu_node_from_wire(tree)
    depth = 0
    while node.children:
        node = node.children[0]
        depth += 1
    assert depth <= 8


def test_app_lane_backend_is_selected_only_when_present(ctx):
    ctx.ax_reader = FakeBridge({}, app_present=True)
    assert isinstance(_posting_backend(ctx), AppLaneInputBackend)
