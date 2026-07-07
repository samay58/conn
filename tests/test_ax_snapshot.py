from __future__ import annotations

from types import SimpleNamespace

import pytest

from conn.config import Config
from conn.tools.ax import FakeAxBackend, MacAxBackend, RawNode, SnapshotStore, StaleRef
from conn.tools.base import ToolError


def cfg(*, max_elements=120, snapshot_ttl_s=10, max_depth=12, deny_bundles=None):
    config = Config()
    object.__setattr__(
        config,
        "ax",
        SimpleNamespace(
            snapshot_ttl_s=snapshot_ttl_s,
            max_elements=max_elements,
            max_depth=max_depth,
            deny_bundles=deny_bundles
            if deny_bundles is not None
            else ["com.1password.1password", "com.apple.keychainaccess"],
        ),
    )
    return config


def node(role, title="", *, value=None, enabled=True, focused=False, secure_hints=(), frame=(0, 0, 10, 10), children=(), subrole=""):
    return RawNode(
        role=role,
        subrole=subrole,
        title=title,
        value=value,
        enabled=enabled,
        focused=focused,
        secure_hints=secure_hints,
        frame=frame,
        children=tuple(children),
    )


def store_for(tree, *, bundle="com.apple.TextEdit", pid=42, window_title=None, config=None):
    backend = FakeAxBackend(bundle, pid, tree)
    if window_title is not None:
        backend.window_title = window_title
    return SnapshotStore(backend, config or cfg()), backend


def test_take_refs_are_stable_and_render_matches_golden():
    tree = node(
        "AXWindow",
        "Main",
        frame=(0, 0, 500, 400),
        children=(
            node("AXButton", "Send", frame=(10, 10, 70, 30)),
            node("AXTextField", "Search", value="openai", focused=True, frame=(10, 50, 200, 30)),
            node("AXButton", "Cancel", enabled=False, frame=(90, 10, 80, 30)),
        ),
    )
    store, _backend = store_for(tree)

    first = store.take()
    second = store.take()

    assert [element.ref for element in first.elements] == ["e1", "e2", "e3", "e4"]
    assert [element.ref for element in second.elements] == ["e1", "e2", "e3", "e4"]
    assert len({element.ref for element in first.elements}) == len(first.elements)
    assert first.render() == "\n".join(
        [
            f'snapshot {first.snapshot_id} app=com.apple.TextEdit window="Main" elements=4',
            'e1 AXWindow "Main"',
            '  e2 AXButton "Send"',
            '  e3 AXTextField "Search" value="openai" (focused)',
            '  e4 AXButton "Cancel" (disabled)',
        ]
    )


def test_interactive_roles_are_kept_before_plain_containers_at_max_elements():
    tree = node(
        "AXWindow",
        "Main",
        children=(
            node("AXGroup", "Decorative", children=(node("AXStaticText", "Copy"),)),
            node("AXButton", "Save"),
            node("AXTextField", "Name", value="samay"),
            node("AXGroup", "Extra"),
        ),
    )
    store, _backend = store_for(tree, config=cfg(max_elements=3))

    snap = store.take()

    assert [(element.role, element.label) for element in snap.elements] == [
        ("AXWindow", "Main"),
        ("AXButton", "Save"),
        ("AXTextField", "Name"),
    ]


def test_secure_detection_redacts_and_query_cannot_match_secret_value():
    tree = node(
        "AXWindow",
        "Browser",
        children=(
            node("AXTextField", "Email", value="samay@example.com"),
            node("AXTextField", "Password", value="hunter2", subrole="AXSecureTextField"),
            node("AXGroup", "Login form", children=(node("AXTextField", "Nested", value="child secret"),), subrole="AXSecureTextField"),
            node("AXTextField", "Chromium password", value="browser secret", secure_hints=("AXDOMClassList: password-field",)),
            node("AXTextField", "Role desc", value="role secret", secure_hints=("AXRoleDescription: password text field",)),
        ),
    )
    store, _backend = store_for(tree, bundle="com.google.Chrome")

    snap = store.take()

    secure = {element.label: element for element in snap.elements if element.secure}
    assert set(secure) == {"Password", "Login form", "Nested", "Chromium password", "Role desc"}
    assert {element.value for element in secure.values()} == {"[redacted]"}
    assert "hunter2" not in snap.render()
    assert snap.render(query="hunter2") == f'snapshot {snap.snapshot_id} app=com.google.Chrome window="Browser" elements=0'


def test_plain_password_label_redacts_and_query_cannot_match_secret_value():
    tree = node(
        "AXWindow",
        "Login",
        children=(
            node("AXTextField", "Password", value="plain secret"),
        ),
    )
    store, _backend = store_for(tree)

    snap = store.take()

    password = next(element for element in snap.elements if element.label == "Password")
    assert password.secure is True
    assert password.value == "[redacted]"
    assert "plain secret" not in snap.render()
    assert snap.render(query="plain secret") == f'snapshot {snap.snapshot_id} app=com.apple.TextEdit window="Login" elements=0'


def test_masked_value_is_secure_and_regular_value_truncates_to_80_chars():
    long_value = "x" * 100
    tree = node(
        "AXWindow",
        "Main",
        children=(
            node("AXTextField", "Long", value=long_value),
            node("AXTextField", "Masked", value="••••••"),
        ),
    )
    store, _backend = store_for(tree)

    snap = store.take()

    long_element = next(element for element in snap.elements if element.label == "Long")
    masked_element = next(element for element in snap.elements if element.label == "Masked")
    assert long_element.value == "x" * 80
    assert masked_element.secure is True
    assert masked_element.value == "[redacted]"


def test_query_filters_elements_and_keeps_ancestors():
    tree = node(
        "AXWindow",
        "Main",
        children=(
            node("AXGroup", "Toolbar", children=(node("AXButton", "Send"),)),
            node("AXButton", "Archive"),
        ),
    )
    store, _backend = store_for(tree)

    query_snap = store.take(query="send")
    full_snap = store.take()

    assert [(element.role, element.label) for element in query_snap.elements] == [
        ("AXWindow", "Main"),
        ("AXGroup", "Toolbar"),
        ("AXButton", "Send"),
    ]
    assert full_snap.render(query="archive").splitlines() == [
        f'snapshot {full_snap.snapshot_id} app=com.apple.TextEdit window="Main" elements=2',
        'e1 AXWindow "Main"',
        '  e4 AXButton "Archive"',
    ]


def test_deny_bundles_raise_tool_error():
    tree = node("AXWindow", "Secrets")
    store, _backend = store_for(tree, bundle="com.1password.1password")

    with pytest.raises(ToolError, match="bundle_denied: com.1password.1password"):
        store.take()


def test_resolve_happy_path_in_both_modes_returns_element_and_raw_node():
    tree = node("AXWindow", "Main", children=(node("AXButton", "Send", frame=(10, 10, 20, 20)),))
    store, _backend = store_for(tree)
    snap = store.take()

    element_read, raw_read = store.resolve(snap.snapshot_id, "e2", for_execution=False)
    element_exec, raw_exec = store.resolve(snap.snapshot_id, "e2", for_execution=True)

    assert element_read == element_exec
    assert raw_read.title == "Send"
    assert raw_exec.title == "Send"


def test_resolve_label_change_raises_stale_ref():
    tree = node("AXWindow", "Main", children=(node("AXButton", "Send"),))
    store, backend = store_for(tree)
    snap = store.take()
    backend.root.children = (node("AXButton", "Submit"),)

    with pytest.raises(StaleRef, match="stale_ref: take a new snapshot"):
        store.resolve(snap.snapshot_id, "e2", for_execution=True)


def test_resolve_sibling_insertion_or_reorder_raises_stale_ref():
    tree = node("AXWindow", "Main", children=(node("AXButton", "Send", frame=(10, 10, 20, 20)),))
    store, backend = store_for(tree)
    snap = store.take()
    backend.root.children = (
        node("AXButton", "Cancel", frame=(5, 5, 20, 20)),
        node("AXButton", "Send", frame=(10, 10, 20, 20)),
    )

    with pytest.raises(StaleRef, match="stale_ref: take a new snapshot"):
        store.resolve(snap.snapshot_id, "e2", for_execution=True)


def test_resolve_ancestor_sibling_reorder_raises_stale_ref():
    tree = node(
        "AXWindow",
        "Main",
        children=(
            node("AXGroup", "Left", children=(node("AXButton", "Open", value="left", frame=(10, 10, 20, 20)),)),
            node("AXGroup", "Right", children=(node("AXButton", "Open", value="right", frame=(10, 10, 20, 20)),)),
        ),
    )
    store, _backend = store_for(tree)
    snap = store.take()
    tree.children = (tree.children[1], tree.children[0])

    with pytest.raises(StaleRef, match="stale_ref: take a new snapshot"):
        store.resolve(snap.snapshot_id, "e3", for_execution=True)


def test_resolve_same_label_ancestor_visual_slot_swap_raises_stale_ref():
    tree = node(
        "AXWindow",
        "Main",
        children=(
            node("AXGroup", "Pane", frame=(0, 0, 100, 100), children=(node("AXButton", "Open", value="LEFT", frame=(10, 10, 20, 20)),)),
            node("AXGroup", "Pane", frame=(200, 0, 100, 100), children=(node("AXButton", "Open", value="RIGHT", frame=(210, 10, 20, 20)),)),
        ),
    )
    store, _backend = store_for(tree)
    snap = store.take()
    tree.children = (
        node("AXGroup", "Pane", frame=(0, 0, 100, 100), children=(node("AXButton", "Open", value="RIGHT", frame=(10, 10, 20, 20)),)),
        node("AXGroup", "Pane", frame=(200, 0, 100, 100), children=(node("AXButton", "Open", value="LEFT", frame=(210, 10, 20, 20)),)),
    )

    with pytest.raises(StaleRef, match="stale_ref: take a new snapshot"):
        store.resolve(snap.snapshot_id, "e3", for_execution=True)


def test_resolve_identical_same_label_sibling_reorder_raises_stale_ref():
    tree = node(
        "AXWindow",
        "Main",
        children=(
            node("AXButton", "OK", value="first", frame=(0, 0, 10, 10)),
            node("AXButton", "OK", value="second", frame=(0, 0, 10, 10)),
        ),
    )
    store, _backend = store_for(tree)
    snap = store.take()
    tree.children = (tree.children[1], tree.children[0])

    with pytest.raises(StaleRef, match="stale_ref: take a new snapshot"):
        store.resolve(snap.snapshot_id, "e2", for_execution=True)


def test_resolve_frame_drift_over_40_pixels_raises_stale_ref():
    tree = node("AXWindow", "Main", children=(node("AXButton", "Send", frame=(10, 10, 20, 20)),))
    store, backend = store_for(tree)
    snap = store.take()
    backend.root.children = (node("AXButton", "Send", frame=(51, 10, 20, 20)),)

    with pytest.raises(StaleRef, match="stale_ref: take a new snapshot"):
        store.resolve(snap.snapshot_id, "e2", for_execution=True)


def test_resolve_frame_drift_within_40_pixels_stays_grounded():
    tree = node("AXWindow", "Main", children=(node("AXButton", "Send", frame=(10, 10, 20, 20)),))
    store, backend = store_for(tree)
    snap = store.take()
    backend.root.children = (node("AXButton", "Send", frame=(11, 10, 20, 20)),)

    element, raw = store.resolve(snap.snapshot_id, "e2", for_execution=True)

    assert element.label == "Send"
    assert raw.title == "Send"


@pytest.mark.parametrize(
    "replacement",
    [
        node("AXTextField", "One time code", value="123456", secure_hints=("AXRoleDescription: password text field",), frame=(10, 10, 120, 24)),
        node("AXTextField", "One time code", value="123456", subrole="AXSecureTextField", frame=(10, 10, 120, 24)),
    ],
)
def test_resolve_plain_text_field_that_becomes_secure_raises_stale_ref(replacement):
    tree = node(
        "AXWindow",
        "Login",
        children=(node("AXTextField", "One time code", value="123456", frame=(10, 10, 120, 24)),),
    )
    store, backend = store_for(tree)
    snap = store.take()
    field = next(element for element in snap.elements if element.label == "One time code")
    assert field.secure is False
    backend.root.children = (replacement,)

    with pytest.raises(StaleRef, match="stale_ref: take a new snapshot"):
        store.resolve(snap.snapshot_id, field.ref, for_execution=True)


def test_resolve_frontmost_change_raises_window_changed():
    tree = node("AXWindow", "Main", children=(node("AXButton", "Send"),))
    store, backend = store_for(tree)
    snap = store.take()
    backend.bundle_id = "com.apple.finder"

    with pytest.raises(StaleRef, match="window_changed: take a new snapshot"):
        store.resolve(snap.snapshot_id, "e2", for_execution=True)


def test_resolve_same_shape_new_window_identity_raises_window_changed():
    tree = node("AXWindow", "Main", children=(node("AXButton", "Send"),))
    store, backend = store_for(tree)
    snap = store.take()
    backend.root = node("AXWindow", "Main", children=(node("AXButton", "Send"),))

    with pytest.raises(StaleRef, match="window_changed: take a new snapshot"):
        store.resolve(snap.snapshot_id, "e2", for_execution=True)


def test_resolve_returns_node_from_validated_tree_not_backend_refetch():
    class RefetchingBackend(FakeAxBackend):
        def resolve_path(self, pid, path):
            return node("AXButton", "Impostor", frame=(10, 10, 20, 20))

    tree = node("AXWindow", "Main", children=(node("AXButton", "Safe", frame=(10, 10, 20, 20)),))
    backend = RefetchingBackend("com.apple.TextEdit", 42, tree)
    store = SnapshotStore(backend, cfg())
    snap = store.take()

    _element, raw = store.resolve(snap.snapshot_id, "e2", for_execution=True)

    assert raw.title == "Safe"


def test_resolve_same_label_sibling_reorder_within_frame_drift_raises_stale_ref():
    tree = node(
        "AXWindow",
        "Main",
        children=(
            node("AXButton", "OK", value="first", frame=(0, 0, 10, 10)),
            node("AXButton", "OK", value="second", frame=(20, 0, 10, 10)),
        ),
    )
    store, backend = store_for(tree)
    snap = store.take()
    tree.children = (
        node("AXButton", "OK", value="second", frame=(20, 0, 10, 10)),
        node("AXButton", "OK", value="first", frame=(0, 0, 10, 10)),
    )

    with pytest.raises(StaleRef, match="stale_ref: take a new snapshot"):
        store.resolve(snap.snapshot_id, "e2", for_execution=True)


def test_ttl_expiry_applies_only_outside_execution(monkeypatch):
    import conn.tools.ax as ax

    now = [100.0]
    monkeypatch.setattr(ax.time, "monotonic", lambda: now[0])
    tree = node("AXWindow", "Main", children=(node("AXButton", "Send"),))
    store, _backend = store_for(tree, config=cfg(snapshot_ttl_s=10))
    snap = store.take()
    now[0] = 110.001

    with pytest.raises(StaleRef, match="snapshot_expired: take a new snapshot"):
        store.resolve(snap.snapshot_id, "e2", for_execution=False)
    element, raw = store.resolve(snap.snapshot_id, "e2", for_execution=True)
    assert element.label == "Send"
    assert raw.title == "Send"


def test_chromium_enable_records_prior_value_and_restore_puts_it_back():
    tree = node("AXWindow", "Chrome")
    _store, backend = store_for(tree, bundle="com.google.Chrome", pid=77)
    backend.ax_flags[77] = {"AXEnhancedUserInterface": False, "AXManualAccessibility": "old"}

    backend.enable_chromium_ax(77)
    assert backend.ax_flags[77] == {"AXEnhancedUserInterface": True, "AXManualAccessibility": True}
    backend.restore_chromium_ax()

    assert backend.ax_flags[77] == {"AXEnhancedUserInterface": False, "AXManualAccessibility": "old"}


def test_mac_chromium_restore_removes_flags_that_were_absent(monkeypatch):
    backend = MacAxBackend()
    app = object()
    flags = {}
    backend._apps[77] = app

    monkeypatch.setattr(backend, "_app", lambda pid: app)
    monkeypatch.setattr(backend, "_copy_attr", lambda element, attr: flags.get(attr))

    def set_attr(element, attr, value):
        if value is None:
            flags.pop(attr, None)
        else:
            flags[attr] = value

    monkeypatch.setattr(backend, "_set_attr", set_attr)

    backend.enable_chromium_ax(77)
    assert flags == {"AXEnhancedUserInterface": True, "AXManualAccessibility": True}

    backend.restore_chromium_ax()

    assert flags == {}
