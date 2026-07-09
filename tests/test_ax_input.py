from __future__ import annotations

from types import SimpleNamespace

import pytest

from conn.config import Config
from conn.doctor import FAIL, OK
import conn.doctor as doctor
from conn.tools.ax import FakeAxBackend, RawNode, SnapshotStore
from conn.tools.base import ToolError
from conn.tools.fake_executors import FAKE_EXECUTORS
from conn.tools.ax_input import (
    FakeInputBackend,
    click,
    focus_tab,
    hotkey,
    menu,
    scroll,
    type_text,
)


def configure_ax(cfg: Config) -> Config:
    object.__setattr__(
        cfg,
        "ax",
        SimpleNamespace(
            snapshot_ttl_s=10,
            max_elements=120,
            max_depth=12,
            deny_bundles=[],
        ),
    )
    return cfg


def node(
    role: str,
    title: str = "",
    *,
    value=None,
    enabled: bool = True,
    focused: bool = False,
    secure_hints=(),
    frame=(0, 0, 10, 10),
    children=(),
    subrole: str = "",
):
    return RawNode(
        role=role,
        subrole=subrole,
        title=title,
        value=value,
        enabled=enabled,
        focused=focused,
        secure_hints=tuple(secure_hints),
        frame=frame,
        children=tuple(children),
    )


class RecordingStore:
    def __init__(self, store: SnapshotStore):
        self._store = store
        self.backend = store.backend
        self.calls: list[tuple[str, str, bool]] = []

    def resolve(self, snapshot_id: str, ref: str, *, for_execution: bool):
        self.calls.append((snapshot_id, ref, for_execution))
        return self._store.resolve(snapshot_id, ref, for_execution=for_execution)


def make_store(cfg: Config, tree: RawNode, *, bundle: str = "com.apple.TextEdit"):
    configure_ax(cfg)
    backend = FakeAxBackend(bundle, 42, tree)
    store = SnapshotStore(backend, cfg)
    snap = store.take()
    return RecordingStore(store), backend, snap


def attach(ctx, store, input_backend):
    ctx.ax = store
    ctx.input_backend = input_backend
    return ctx


def test_click_resolves_for_execution_prefers_ax_press(cfg, ctx):
    tree = node("AXWindow", "Main", frame=(0, 0, 600, 400), children=(node("AXButton", "Send", frame=(30, 40, 80, 24)),))
    store, _backend, snap = make_store(cfg, tree)
    input_backend = FakeInputBackend(window_frame=(0, 0, 600, 400))
    attach(ctx, store, input_backend)

    result = click({"snapshot_id": snap.snapshot_id, "ref": "e2"}, ctx)

    assert store.calls == [(snap.snapshot_id, "e2", True)]
    assert result["via"] == "ax_press"
    assert [action["kind"] for action in input_backend.actions] == ["ax_press"]


def test_click_refuses_blind_coordinate_fallback_when_not_visible(cfg, ctx):
    tree = node("AXWindow", "Main", frame=(0, 0, 200, 150), children=(node("AXButton", "Offscreen", frame=(400, 400, 80, 24)),))
    store, _backend, snap = make_store(cfg, tree)
    input_backend = FakeInputBackend(window_frame=(0, 0, 200, 150), default_ax_press=False)
    attach(ctx, store, input_backend)

    with pytest.raises(ToolError, match="element_not_visible: scroll it into view or re-snapshot"):
        click({"snapshot_id": snap.snapshot_id, "ref": "e2"}, ctx)

    assert [action["kind"] for action in input_backend.actions] == ["ax_press"]


def test_type_text_clicks_to_focus_reverifies_types_in_chunks_and_submits(cfg, ctx):
    text = "x" * 45
    tree = node("AXWindow", "Compose", frame=(0, 0, 640, 480), children=(node("AXTextField", "Body", frame=(20, 30, 300, 40)),))
    store, _backend, snap = make_store(cfg, tree)
    input_backend = FakeInputBackend(window_frame=(0, 0, 640, 480), default_ax_press=False)
    attach(ctx, store, input_backend)

    result = type_text(
        {"snapshot_id": snap.snapshot_id, "ref": "e2", "text": text, "submit": True},
        ctx,
    )

    assert store.calls == [(snap.snapshot_id, "e2", True)]
    assert result == {"ref": "e2", "typed": 45, "submitted": True}
    assert [action["kind"] for action in input_backend.actions] == [
        "ax_press",
        "click",
        "type_unicode",
        "type_unicode",
        "type_unicode",
        "key_chord",
    ]
    assert [action["text"] for action in input_backend.actions if action["kind"] == "type_unicode"] == [
        "x" * 20,
        "x" * 20,
        "x" * 5,
    ]
    assert input_backend.actions[-1]["keys"] == ("return",)


def test_type_text_refuses_uncertain_browser_submit(cfg, ctx):
    tree = node("AXWindow", "Browser", frame=(0, 0, 640, 480), children=(node("AXTextField", "Search", frame=(20, 30, 300, 40)),))
    store, _backend, snap = make_store(cfg, tree, bundle="com.google.Chrome")
    input_backend = FakeInputBackend(window_frame=(0, 0, 640, 480))
    attach(ctx, store, input_backend)

    with pytest.raises(ToolError, match="submit_uncertain_field"):
        type_text(
            {"snapshot_id": snap.snapshot_id, "ref": "e2", "text": "hello", "submit": True},
            ctx,
        )

    assert store.calls == [(snap.snapshot_id, "e2", True)]
    assert input_backend.actions == []


def test_type_text_rejects_text_over_2000_chars(cfg, ctx):
    tree = node("AXWindow", "Compose", frame=(0, 0, 640, 480), children=(node("AXTextField", "Body", frame=(20, 30, 300, 40)),))
    store, _backend, snap = make_store(cfg, tree)
    input_backend = FakeInputBackend(window_frame=(0, 0, 640, 480))
    attach(ctx, store, input_backend)

    with pytest.raises(ToolError, match="text_too_long"):
        type_text(
            {"snapshot_id": snap.snapshot_id, "ref": "e2", "text": "x" * 2001},
            ctx,
        )

    assert store.calls == [(snap.snapshot_id, "e2", True)]


def test_type_text_refuses_when_focus_changes_after_click(cfg, ctx):
    tree = node(
        "AXWindow",
        "Compose",
        frame=(0, 0, 640, 480),
        children=(
            node("AXTextField", "Body", frame=(20, 30, 300, 40)),
            node("AXButton", "Elsewhere", frame=(20, 90, 120, 24)),
        ),
    )
    store, _backend, snap = make_store(cfg, tree)
    input_backend = FakeInputBackend(window_frame=(0, 0, 640, 480), default_ax_press=False)
    input_backend.next_focus_path = (1,)
    attach(ctx, store, input_backend)

    with pytest.raises(ToolError, match="focus_changed: take a new snapshot"):
        type_text(
            {"snapshot_id": snap.snapshot_id, "ref": "e2", "text": "hello"},
            ctx,
        )

    assert [action["kind"] for action in input_backend.actions] == ["ax_press", "click"]


def test_type_text_stops_when_focus_drifts_between_chunks(cfg, ctx):
    text = "x" * 45
    tree = node("AXWindow", "Compose", frame=(0, 0, 640, 480), children=(node("AXTextField", "Body", frame=(20, 30, 300, 40)),))
    store, _backend, snap = make_store(cfg, tree)

    class DriftAfterFirstChunkBackend(FakeInputBackend):
        def type_unicode(self, text: str) -> None:
            super().type_unicode(text)
            if len([action for action in self.actions if action["kind"] == "type_unicode"]) == 1:
                self.focused_path_value = (99,)

    input_backend = DriftAfterFirstChunkBackend(window_frame=(0, 0, 640, 480), default_ax_press=False)
    attach(ctx, store, input_backend)

    with pytest.raises(ToolError, match="focus_changed: take a new snapshot"):
        type_text(
            {"snapshot_id": snap.snapshot_id, "ref": "e2", "text": text},
            ctx,
        )

    assert [action["kind"] for action in input_backend.actions] == [
        "ax_press",
        "click",
        "type_unicode",
    ]


def test_type_text_refuses_submit_when_focus_drifts_after_typing(cfg, ctx):
    text = "x" * 20
    tree = node("AXWindow", "Compose", frame=(0, 0, 640, 480), children=(node("AXTextField", "Body", frame=(20, 30, 300, 40)),))
    store, _backend, snap = make_store(cfg, tree)

    class DriftAfterTypingBackend(FakeInputBackend):
        def type_unicode(self, text: str) -> None:
            super().type_unicode(text)
            self.focused_path_value = (99,)

    input_backend = DriftAfterTypingBackend(window_frame=(0, 0, 640, 480), default_ax_press=False)
    attach(ctx, store, input_backend)

    with pytest.raises(ToolError, match="focus_changed: take a new snapshot"):
        type_text(
            {"snapshot_id": snap.snapshot_id, "ref": "e2", "text": text, "submit": True},
            ctx,
        )

    assert [action["kind"] for action in input_backend.actions] == [
        "ax_press",
        "click",
        "type_unicode",
    ]


def test_scroll_uses_scroll_to_visible_fallback_rules(cfg, ctx):
    tree = node(
        "AXWindow",
        "Main",
        frame=(0, 0, 500, 400),
        children=(
            node(
                "AXScrollArea",
                "Results",
                frame=(20, 20, 300, 200),
                children=(node("AXStaticText", "Target", frame=(40, 350, 120, 20)),),
            ),
        ),
    )
    store, _backend, snap = make_store(cfg, tree)
    input_backend = FakeInputBackend(
        window_frame=(0, 0, 500, 400),
        default_scroll_to_visible=False,
    )
    attach(ctx, store, input_backend)

    result = scroll({"snapshot_id": snap.snapshot_id, "ref": "e3"}, ctx)

    assert store.calls == [(snap.snapshot_id, "e3", True)]
    assert result["via"] == "scroll_wheel"
    assert [action["kind"] for action in input_backend.actions] == [
        "scroll_to_visible",
        "scroll_wheel",
    ]


def test_hotkey_parses_cmd_shift_t(cfg, ctx):
    input_backend = FakeInputBackend()
    attach(ctx, None, input_backend)

    result = hotkey({"combo": "cmd+shift+t"}, ctx)

    assert result == {"combo": "cmd+shift+t", "lane": "python"}
    assert input_backend.actions == [{"kind": "key_chord", "keys": ("cmd", "shift", "t")}]


@pytest.mark.parametrize("spoken", ["meta+t", "super+t", "win+t", "Meta+T"])
def test_hotkey_aliases_meta_and_super_to_cmd(cfg, ctx, spoken):
    # The 2026-07-07 live drive: the model proposed "meta+t" and the
    # normalizer died with invalid_hotkey because meta parsed as a second
    # primary key.
    input_backend = FakeInputBackend()
    attach(ctx, None, input_backend)

    result = hotkey({"combo": spoken}, ctx)

    assert result == {"combo": "cmd+t", "lane": "python"}
    assert input_backend.actions == [{"kind": "key_chord", "keys": ("cmd", "t")}]


@pytest.mark.parametrize("tool_name,args_factory", [
    ("computer_click", lambda snap_id: {"snapshot_id": snap_id, "ref": "e2"}),
    ("computer_type_text", lambda snap_id: {"snapshot_id": snap_id, "ref": "e2", "text": "hello"}),
    ("computer_scroll", lambda snap_id: {"snapshot_id": snap_id, "ref": "e2"}),
])
def test_resolution_based_executors_refuse_accessibility_untrusted(cfg, ctx, tool_name, args_factory):
    tree = node("AXWindow", "Main", frame=(0, 0, 600, 400), children=(node("AXButton", "Send", frame=(30, 40, 80, 24)),))
    store, _backend, snap = make_store(cfg, tree)
    input_backend = FakeInputBackend(posting_ok=False, window_frame=(0, 0, 600, 400))
    attach(ctx, store, input_backend)
    executor = {
        "computer_click": click,
        "computer_type_text": type_text,
        "computer_scroll": scroll,
    }[tool_name]

    with pytest.raises(ToolError, match="accessibility_untrusted"):
        executor(args_factory(snap.snapshot_id), ctx)


@pytest.mark.parametrize("executor,args,tree", [
    (
        hotkey,
        {"combo": "cmd+shift+t"},
        None,
    ),
    (
        focus_tab,
        {"title": "Kaku"},
        node("AXWindow", "Tabs", children=(node("AXTab", "Kaku"),)),
    ),
    (
        menu,
        {"path": ["File", "New Tab"]},
        node(
            "AXMenuBar",
            children=(
                node("AXMenuBarItem", "File", children=(node("AXMenuItem", "New Tab"),)),
            ),
        ),
    ),
])
def test_non_snapshot_executors_refuse_accessibility_untrusted(cfg, ctx, executor, args, tree):
    input_backend = FakeInputBackend(posting_ok=False)
    if tree is not None:
        store, backend, _snap = make_store(cfg, tree)
        if executor is menu:
            backend.menu_root = tree
        attach(ctx, store, input_backend)
    else:
        attach(ctx, None, input_backend)

    with pytest.raises(ToolError, match="accessibility_untrusted"):
        executor(args, ctx)


def test_focus_tab_unique_fuzzy_match_presses_and_returns_title(cfg, ctx):
    tree = node(
        "AXWindow",
        "Tabs",
        children=(
            node("AXTab", "Inbox"),
            node("AXTab", "Kaku"),
            node("AXTab", "Calendar"),
        ),
    )
    store, _backend, _snap = make_store(cfg, tree)
    input_backend = FakeInputBackend()
    attach(ctx, store, input_backend)

    result = focus_tab({"title": "kaku"}, ctx)

    assert result == {"focused": "Kaku"}
    assert input_backend.actions == [{"kind": "ax_press", "path": (1,), "supported": True}]


def test_focus_tab_refuses_coordinate_fallback_when_tab_is_occluded(cfg, ctx):
    tree = node(
        "AXWindow",
        "Tabs",
        children=(
            node("AXTab", "Inbox"),
            node("AXTab", "Kaku"),
            node("AXTab", "Calendar"),
        ),
    )
    store, _backend, _snap = make_store(cfg, tree)
    input_backend = FakeInputBackend(
        default_ax_press=False,
        default_coordinate_fallback_safe=False,
    )
    attach(ctx, store, input_backend)

    with pytest.raises(ToolError, match="element_not_visible: scroll it into view or re-snapshot"):
        focus_tab({"title": "kaku"}, ctx)

    assert input_backend.actions == [{"kind": "ax_press", "path": (1,), "supported": False}]


def test_focus_tab_refuses_when_named_app_is_not_frontmost_at_execution(cfg, ctx):
    tree = node("AXWindow", "Tabs", children=(node("AXTab", "Inbox"),))
    store, backend, _snap = make_store(cfg, tree, bundle="com.apple.Safari")
    backend.bundle_id = "com.evil.App"
    input_backend = FakeInputBackend()
    attach(ctx, store, input_backend)

    with pytest.raises(ToolError, match="app_not_frontmost: Safari"):
        focus_tab({"title": "Inbox", "app": "Safari"}, ctx)

    assert input_backend.actions == []


def test_menu_refuses_when_named_app_is_not_frontmost_at_execution(cfg, ctx):
    store, backend, _snap = make_store(cfg, node("AXWindow", "Main"), bundle="com.apple.Safari")
    backend.bundle_id = "com.evil.App"
    backend.menu_root = node("AXMenuBar", "Menu", children=(node("AXMenu", "File", children=(node("AXMenuItem", "Close"),)),))
    input_backend = FakeInputBackend()
    attach(ctx, store, input_backend)

    with pytest.raises(ToolError, match="app_not_frontmost: Safari"):
        menu({"path": ["File", "Close"], "app": "Safari"}, ctx)

    assert input_backend.actions == []


def test_click_refuses_coordinate_fallback_when_element_is_occluded(cfg, ctx):
    tree = node("AXWindow", "Main", frame=(0, 0, 600, 400), children=(node("AXButton", "Send", frame=(30, 40, 80, 24)),))
    store, _backend, snap = make_store(cfg, tree)
    input_backend = FakeInputBackend(
        window_frame=(0, 0, 600, 400),
        default_ax_press=False,
        default_coordinate_fallback_safe=False,
    )
    attach(ctx, store, input_backend)

    with pytest.raises(ToolError, match="element_not_visible: scroll it into view or re-snapshot"):
        click({"snapshot_id": snap.snapshot_id, "ref": "e2"}, ctx)

    assert [action["kind"] for action in input_backend.actions] == ["ax_press"]


def test_focus_tab_ambiguity_returns_candidates_without_acting(cfg, ctx):
    tree = node(
        "AXWindow",
        "Tabs",
        children=(
            node("AXTab", "Kaku Docs"),
            node("AXTab", "Kaku Deck"),
            node("AXTab", "Calendar"),
        ),
    )
    store, _backend, _snap = make_store(cfg, tree)
    input_backend = FakeInputBackend()
    attach(ctx, store, input_backend)

    result = focus_tab({"title": "kaku d"}, ctx)

    assert result["candidates"][:2] == ["Kaku Docs", "Kaku Deck"]
    assert input_backend.actions == []


def test_menu_walks_segments_and_presses_terminal_item(cfg, ctx):
    menu_root = node(
        "AXMenuBar",
        children=(
            node("AXMenuBarItem", "File", children=(node("AXMenuItem", "New Tab"),)),
            node("AXMenuBarItem", "View", children=(node("AXMenuItem", "Zoom In"),)),
        ),
    )
    tree = node("AXWindow", "Main")
    store, backend, _snap = make_store(cfg, tree)
    backend.menu_root = menu_root
    input_backend = FakeInputBackend()
    attach(ctx, store, input_backend)

    result = menu({"path": ["file", "new tab"]}, ctx)

    assert result == {"pressed": ["File", "New Tab"]}
    assert input_backend.actions == [{"kind": "press_menu_path", "titles": ("File", "New Tab"), "supported": True}]


def test_menu_returns_available_titles_at_failing_level(cfg, ctx):
    menu_root = node(
        "AXMenuBar",
        children=(
            node(
                "AXMenuBarItem",
                "View",
                children=(node("AXMenuItem", "Zoom In"), node("AXMenuItem", "Zoom Out")),
            ),
        ),
    )
    tree = node("AXWindow", "Main")
    store, backend, _snap = make_store(cfg, tree)
    backend.menu_root = menu_root
    input_backend = FakeInputBackend()
    attach(ctx, store, input_backend)

    result = menu({"path": ["View", "Missing"]}, ctx)

    assert result == {"candidates": ["Zoom In", "Zoom Out"]}
    assert input_backend.actions == []


def test_doctor_posting_capability_check_reports_same_launch_context(monkeypatch):
    import conn.tools.ax_input as ax_input

    class ProbeBackend:
        def posting_capability(self) -> bool:
            return False

    monkeypatch.setattr(ax_input, "MacInputBackend", ProbeBackend)

    result = doctor._input_posting()

    assert result["check"] == "input_posting"
    assert result["status"] == FAIL
    assert "same way the daemon runs" in result["detail"]


def test_fake_executors_cover_all_grounded_input_tools(ctx):
    expected = {
        "computer_ax_snapshot",
        "computer_click",
        "computer_type_text",
        "computer_scroll",
        "computer_hotkey",
        "app_focus_tab",
        "app_menu",
    }

    assert expected.issubset(FAKE_EXECUTORS)
    assert FAKE_EXECUTORS["computer_ax_snapshot"]({}, ctx)["simulated"] is True
    assert FAKE_EXECUTORS["computer_click"]({"ref": "e2"}, ctx)["ref"] == "e2"
    assert FAKE_EXECUTORS["computer_type_text"]({"text": "hello", "submit": True}, ctx) == {
        "ref": None,
        "typed": 5,
        "submitted": True,
        "simulated": True,
    }
    assert FAKE_EXECUTORS["computer_scroll"]({"ref": "e2"}, ctx)["via"] == "ax_scroll"
    assert FAKE_EXECUTORS["computer_hotkey"]({"combo": "cmd+shift+t"}, ctx)["combo"] == "cmd+shift+t"
    assert FAKE_EXECUTORS["app_focus_tab"]({"title": "Kaku"}, ctx)["focused"] == "Kaku"
    assert FAKE_EXECUTORS["app_menu"]({"path": ["File", "New Tab"]}, ctx)["pressed"] == ["File", "New Tab"]


def test_named_app_frontmost_matches_bundle_tail():
    from conn.tools.ax_input import _require_named_app_frontmost

    # Apps outside the alias map match on the bundle id's last component.
    _require_named_app_frontmost({"app": "Terminal"}, "com.apple.Terminal")
    _require_named_app_frontmost({"app": "kaku"}, "com.example.Kaku")
    # Alias map still works, and a real mismatch still refuses.
    _require_named_app_frontmost({"app": "Google Chrome"}, "com.google.Chrome")
    with pytest.raises(ToolError, match="app_not_frontmost: Safari"):
        _require_named_app_frontmost({"app": "Safari"}, "com.google.Chrome")

def test_menu_walks_through_the_untitled_ax_menu_interposer(cfg, ctx):
    # Real macOS menus: AXMenuBar -> AXMenuBarItem(titled) -> AXMenu("") ->
    # AXMenuItem(titled). The idealized flat trees above hid this until a
    # live drive died with empty candidates (2026-07-09).
    menu_root = node(
        "AXMenuBar",
        children=(
            node("AXMenuBarItem", "Shell", children=(
                node("AXMenu", children=(node("AXMenuItem", "New Tab"), node("AXMenuItem", "New Window"))),
            )),
            node("AXMenuBarItem", "Edit", children=(node("AXMenu"),)),
        ),
    )
    tree = node("AXWindow", "Main")
    store, backend, _snap = make_store(cfg, tree)
    backend.menu_root = menu_root
    input_backend = FakeInputBackend()
    attach(ctx, store, input_backend)

    result = menu({"path": ["shell", "new tab"]}, ctx)

    assert result == {"pressed": ["Shell", "New Tab"]}
    assert input_backend.actions == [{"kind": "press_menu_path", "titles": ("Shell", "New Tab"), "supported": True}]


def test_menu_candidates_surface_through_the_interposer(cfg, ctx):
    menu_root = node(
        "AXMenuBar",
        children=(
            node("AXMenuBarItem", "View", children=(
                node("AXMenu", children=(node("AXMenuItem", "Zoom In"), node("AXMenuItem", "Zoom Out"))),
            )),
        ),
    )
    tree = node("AXWindow", "Main")
    store, backend, _snap = make_store(cfg, tree)
    backend.menu_root = menu_root
    input_backend = FakeInputBackend()
    attach(ctx, store, input_backend)

    result = menu({"path": ["View", "Missing"]}, ctx)

    assert result == {"candidates": ["Zoom In", "Zoom Out"]}
    assert input_backend.actions == []
