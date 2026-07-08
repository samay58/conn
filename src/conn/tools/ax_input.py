from __future__ import annotations

from dataclasses import dataclass, field
from difflib import SequenceMatcher
import os
from typing import Protocol

from .ax import RawNode
from .base import ExecutionContext, ToolError, app_matches_bundle

MAX_TEXT_CHARS = 2000
TYPE_CHUNK_CHARS = 20
MATCH_THRESHOLD = 0.6
AMBIGUITY_DELTA = 0.1
MODIFIER_ORDER = ("cmd", "ctrl", "alt", "shift")
TEXT_INPUT_ROLES = {"AXTextField", "AXTextArea", "AXSecureTextField"}
TAB_ROLES = {"AXTab"}
SCROLL_ROLES = {"AXScrollArea", "AXScrollView"}
BROWSER_BUNDLES = {
    "com.google.Chrome",
    "com.apple.Safari",
    "com.microsoft.edgemac",
    "com.brave.Browser",
    "org.chromium.Chromium",
    "com.operasoftware.Opera",
}
MODIFIER_FLAGS = {
    "cmd": 1 << 20,
    "shift": 1 << 17,
    "alt": 1 << 19,
    "ctrl": 1 << 18,
}
KEYCODES = {
    "a": 0x00,
    "b": 0x0B,
    "c": 0x08,
    "d": 0x02,
    "e": 0x0E,
    "f": 0x03,
    "g": 0x05,
    "h": 0x04,
    "i": 0x22,
    "j": 0x26,
    "k": 0x28,
    "l": 0x25,
    "m": 0x2E,
    "n": 0x2D,
    "o": 0x1F,
    "p": 0x23,
    "q": 0x0C,
    "r": 0x0F,
    "s": 0x01,
    "t": 0x11,
    "u": 0x20,
    "v": 0x09,
    "w": 0x0D,
    "x": 0x07,
    "y": 0x10,
    "z": 0x06,
    "0": 0x1D,
    "1": 0x12,
    "2": 0x13,
    "3": 0x14,
    "4": 0x15,
    "5": 0x17,
    "6": 0x16,
    "7": 0x1A,
    "8": 0x1C,
    "9": 0x19,
    "return": 0x24,
    "tab": 0x30,
    "space": 0x31,
    "escape": 0x35,
    "delete": 0x33,
    "up": 0x7E,
    "down": 0x7D,
    "left": 0x7B,
    "right": 0x7C,
}


class InputBackend(Protocol):
    lane: str

    def posting_capability(self) -> bool: ...
    def ax_press(self, pid: int, path: tuple[int, ...]) -> bool: ...
    def click(self, x: float, y: float, *, pid: int | None = None, path: tuple[int, ...] | None = None) -> None: ...
    def type_unicode(self, text: str) -> None: ...
    def key_chord(self, keys: tuple[str, ...]) -> None: ...
    def scroll_to_visible(self, pid: int, path: tuple[int, ...]) -> bool: ...
    def scroll_wheel(self, x: float, y: float, delta_y: int) -> None: ...
    def frontmost_window_frame(self, pid: int | None = None) -> tuple[float, float, float, float] | None: ...
    def coordinate_fallback_safe(self, pid: int, path: tuple[int, ...]) -> bool: ...
    def focused_path(self, pid: int) -> tuple[int, ...] | None: ...
    def press_menu_path(self, pid: int, titles: tuple[str, ...]) -> bool: ...


@dataclass
class FakeInputBackend:
    lane = "python"
    posting_ok: bool = True
    window_frame: tuple[float, float, float, float] | None = (0.0, 0.0, 1440.0, 900.0)
    default_ax_press: bool = True
    default_scroll_to_visible: bool = True
    default_coordinate_fallback_safe: bool = True
    ax_press_overrides: dict[tuple[int, ...], bool] = field(default_factory=dict)
    scroll_to_visible_overrides: dict[tuple[int, ...], bool] = field(default_factory=dict)
    coordinate_fallback_overrides: dict[tuple[int, ...], bool] = field(default_factory=dict)
    menu_press_overrides: dict[tuple[str, ...], bool] = field(default_factory=dict)
    focused_path_value: tuple[int, ...] | None = None
    next_focus_path: tuple[int, ...] | None = None
    actions: list[dict] = field(default_factory=list)

    def posting_capability(self) -> bool:
        return self.posting_ok

    def ax_press(self, pid: int, path: tuple[int, ...]) -> bool:
        supported = self.ax_press_overrides.get(path, self.default_ax_press)
        self.actions.append({"kind": "ax_press", "path": path, "supported": supported})
        if supported:
            self.focused_path_value = path
        return supported

    def click(self, x: float, y: float, *, pid: int | None = None, path: tuple[int, ...] | None = None) -> None:
        self.actions.append({"kind": "click", "point": (x, y), "path": path})
        if self.next_focus_path is not None:
            self.focused_path_value = self.next_focus_path
        else:
            self.focused_path_value = path

    def type_unicode(self, text: str) -> None:
        self.actions.append({"kind": "type_unicode", "text": text})

    def key_chord(self, keys: tuple[str, ...]) -> None:
        self.actions.append({"kind": "key_chord", "keys": keys})

    def scroll_to_visible(self, pid: int, path: tuple[int, ...]) -> bool:
        supported = self.scroll_to_visible_overrides.get(path, self.default_scroll_to_visible)
        self.actions.append({"kind": "scroll_to_visible", "path": path, "supported": supported})
        return supported

    def scroll_wheel(self, x: float, y: float, delta_y: int) -> None:
        self.actions.append({"kind": "scroll_wheel", "point": (x, y), "delta_y": delta_y})

    def frontmost_window_frame(self, pid: int | None = None) -> tuple[float, float, float, float] | None:
        return self.window_frame

    def coordinate_fallback_safe(self, pid: int, path: tuple[int, ...]) -> bool:
        return self.coordinate_fallback_overrides.get(path, self.default_coordinate_fallback_safe)

    def focused_path(self, pid: int) -> tuple[int, ...] | None:
        return self.focused_path_value

    def press_menu_path(self, pid: int, titles: tuple[str, ...]) -> bool:
        supported = self.menu_press_overrides.get(titles, True)
        self.actions.append({"kind": "press_menu_path", "titles": titles, "supported": supported})
        return supported


class AppLaneInputBackend:
    """computer_hotkey and app_menu through Conn.app's Accessibility grant
    (T4): the app posts the chord or presses the menu item and answers over
    the websocket. Only the ops those two tools need cross the wire; the
    grounded lane (snapshot, click, type) stays on the python backend and
    its own grant. Wire failures raise instead of falling back: a chord
    that may or may not have posted must never be posted twice."""

    lane = "app"

    def __init__(self, bridge):
        self._bridge = bridge

    def posting_capability(self) -> bool:
        return self._bridge.request_action_sync("posting_capability", {}) is True

    def key_chord(self, keys: tuple[str, ...]) -> None:
        result = self._bridge.request_action_sync("key_chord", {"keys": list(keys)})
        if result is not True:
            raise ToolError("app_lane_error: key chord did not post; is Conn.app still connected?")

    def press_menu_path(self, pid: int, titles: tuple[str, ...]) -> bool:
        result = self._bridge.request_action_sync(
            "press_menu_path", {"pid": pid, "titles": list(titles)})
        if result is None:
            raise ToolError("app_lane_error: menu press did not answer; is Conn.app still connected?")
        return bool(result)

    def menu_tree(self, pid: int) -> RawNode | None:
        data = self._bridge.request_action_sync("menu_tree", {"pid": pid, "max_depth": 8})
        return _menu_node_from_wire(data)


def _menu_node_from_wire(data: object, depth: int = 8) -> RawNode | None:
    """Menu trees cross a process boundary; whitelist and coerce, and cap the
    depth so a malformed answer cannot recurse away."""
    if not isinstance(data, dict) or depth < 0:
        return None
    raw_children = data.get("children")
    children = tuple(
        node
        for node in (
            _menu_node_from_wire(child, depth - 1)
            for child in (raw_children if isinstance(raw_children, list) else [])
        )
        if node is not None
    )
    return RawNode(role=str(data.get("role", "")), title=str(data.get("title", "")),
                   children=children)


class MacInputBackend:
    lane = "python"

    def posting_capability(self) -> bool:
        try:
            from ApplicationServices import AXIsProcessTrusted, CGEventCreateKeyboardEvent, CGEventPostToPid
        except Exception:
            return False
        if not AXIsProcessTrusted():
            return False
        try:
            event = CGEventCreateKeyboardEvent(None, 0, True)
            if event is None:
                return False
            CGEventPostToPid(os.getpid(), event)
            return True
        except Exception:
            return False

    def ax_press(self, pid: int, path: tuple[int, ...]) -> bool:
        from ApplicationServices import AXUIElementPerformAction

        element = self._element_for_path(pid, path)
        if element is None:
            return False
        try:
            return AXUIElementPerformAction(element, "AXPress") == 0
        except Exception:
            return False

    def click(self, x: float, y: float, *, pid: int | None = None, path: tuple[int, ...] | None = None) -> None:
        from Quartz import (
            CGEventCreateMouseEvent,
            CGEventPost,
            kCGEventLeftMouseDown,
            kCGEventLeftMouseUp,
            kCGHIDEventTap,
            kCGMouseButtonLeft,
        )

        point = (float(x), float(y))
        down = CGEventCreateMouseEvent(None, kCGEventLeftMouseDown, point, kCGMouseButtonLeft)
        up = CGEventCreateMouseEvent(None, kCGEventLeftMouseUp, point, kCGMouseButtonLeft)
        CGEventPost(kCGHIDEventTap, down)
        CGEventPost(kCGHIDEventTap, up)

    def type_unicode(self, text: str) -> None:
        from Quartz import (
            CGEventCreateKeyboardEvent,
            CGEventKeyboardSetUnicodeString,
            CGEventPost,
            kCGHIDEventTap,
        )

        down = CGEventCreateKeyboardEvent(None, 0, True)
        up = CGEventCreateKeyboardEvent(None, 0, False)
        CGEventKeyboardSetUnicodeString(down, len(text), text)
        CGEventKeyboardSetUnicodeString(up, len(text), text)
        CGEventPost(kCGHIDEventTap, down)
        CGEventPost(kCGHIDEventTap, up)

    def key_chord(self, keys: tuple[str, ...]) -> None:
        from Quartz import CGEventCreateKeyboardEvent, CGEventPost, kCGHIDEventTap

        modifiers = tuple(key for key in keys if key in MODIFIER_FLAGS)
        primary = next((key for key in keys if key not in MODIFIER_FLAGS), None)
        if primary is None:
            raise ToolError("invalid_hotkey: missing primary key")
        keycode = KEYCODES.get(primary)
        if keycode is None:
            raise ToolError(f"invalid_hotkey: unsupported key {primary}")
        flags = 0
        for modifier in modifiers:
            flags |= MODIFIER_FLAGS[modifier]
        down = CGEventCreateKeyboardEvent(None, keycode, True)
        up = CGEventCreateKeyboardEvent(None, keycode, False)
        down.setFlags_(flags)
        up.setFlags_(flags)
        CGEventPost(kCGHIDEventTap, down)
        CGEventPost(kCGHIDEventTap, up)

    def scroll_to_visible(self, pid: int, path: tuple[int, ...]) -> bool:
        from ApplicationServices import AXUIElementPerformAction

        element = self._element_for_path(pid, path)
        if element is None:
            return False
        try:
            return AXUIElementPerformAction(element, "AXScrollToVisible") == 0
        except Exception:
            return False

    def scroll_wheel(self, x: float, y: float, delta_y: int) -> None:
        from Quartz import CGEventCreateScrollWheelEvent, CGEventPost, kCGHIDEventTap, kCGScrollEventUnitLine

        event = CGEventCreateScrollWheelEvent(None, kCGScrollEventUnitLine, 1, int(delta_y))
        event.setLocation_((float(x), float(y)))
        CGEventPost(kCGHIDEventTap, event)

    def frontmost_window_frame(self, pid: int | None = None) -> tuple[float, float, float, float] | None:
        window = self._focused_window(pid or self._frontmost_pid())
        if window is None:
            return None
        return self._frame(window)

    def coordinate_fallback_safe(self, pid: int, path: tuple[int, ...]) -> bool:
        return False

    def focused_path(self, pid: int) -> tuple[int, ...] | None:
        from ApplicationServices import (
            AXUIElementCopyAttributeValue,
            AXUIElementCreateApplication,
            kAXFocusedUIElementAttribute,
        )

        app = AXUIElementCreateApplication(pid)
        try:
            err, focused = AXUIElementCopyAttributeValue(app, kAXFocusedUIElementAttribute, None)
        except Exception:
            return None
        if err != 0 or focused is None:
            return None
        window = self._focused_window(pid)
        if window is None:
            return None
        return self._find_path(window, focused)

    def press_menu_path(self, pid: int, titles: tuple[str, ...]) -> bool:
        from ApplicationServices import AXUIElementCopyAttributeValue, AXUIElementCreateApplication, AXUIElementPerformAction, kAXMenuBarAttribute

        app = AXUIElementCreateApplication(pid)
        try:
            err, menu_bar = AXUIElementCopyAttributeValue(app, kAXMenuBarAttribute, None)
        except Exception:
            return False
        if err != 0 or menu_bar is None:
            return False
        element = menu_bar
        for title in titles:
            children = self._copy_attr(element, "AXChildren") or []
            match = None
            for child in children:
                if str(self._copy_attr(child, "AXTitle") or "") == title:
                    match = child
                    break
            if match is None:
                return False
            element = match
        try:
            return AXUIElementPerformAction(element, "AXPress") == 0
        except Exception:
            return False

    def _frontmost_pid(self) -> int:
        from AppKit import NSWorkspace

        app = NSWorkspace.sharedWorkspace().frontmostApplication()
        if app is None:
            raise ToolError("frontmost_unavailable")
        return int(app.processIdentifier())

    def _focused_window(self, pid: int) -> object | None:
        from ApplicationServices import AXUIElementCopyAttributeValue, AXUIElementCreateApplication, kAXFocusedWindowAttribute

        app = AXUIElementCreateApplication(pid)
        try:
            err, window = AXUIElementCopyAttributeValue(app, kAXFocusedWindowAttribute, None)
        except Exception:
            return None
        if err != 0:
            return None
        return window

    def _element_for_path(self, pid: int, path: tuple[int, ...]) -> object | None:
        element = self._focused_window(pid)
        if element is None:
            return None
        for index in path:
            children = self._copy_attr(element, "AXChildren") or []
            if index < 0 or index >= len(children):
                return None
            element = children[index]
        return element

    def _find_path(self, root: object, target: object, path: tuple[int, ...] = ()) -> tuple[int, ...] | None:
        if root == target:
            return path
        children = self._copy_attr(root, "AXChildren") or []
        for index, child in enumerate(children):
            found = self._find_path(child, target, (*path, index))
            if found is not None:
                return found
        return None

    def _copy_attr(self, element: object, attr: str) -> object | None:
        from ApplicationServices import AXUIElementCopyAttributeValue

        try:
            err, value = AXUIElementCopyAttributeValue(element, attr, None)
        except Exception:
            return None
        if err != 0:
            return None
        return value

    def _frame(self, element: object) -> tuple[float, float, float, float]:
        position = self._copy_attr(element, "AXPosition")
        size = self._copy_attr(element, "AXSize")
        x, y = _point(position)
        w, h = _size(size)
        return (x, y, w, h)


def click(args: dict, ctx: ExecutionContext) -> dict:
    store = _store(ctx)
    backend = _input_backend(ctx)
    _require_posting(backend)
    element, _raw = store.resolve(args["snapshot_id"], args["ref"], for_execution=True)
    via = _click_like(store, element, backend)
    return {"ref": element.ref, "via": via}


def type_text(args: dict, ctx: ExecutionContext) -> dict:
    store = _store(ctx)
    backend = _input_backend(ctx)
    _require_posting(backend)
    element, raw = store.resolve(args["snapshot_id"], args["ref"], for_execution=True)
    text = str(args["text"])
    if len(text) > MAX_TEXT_CHARS:
        raise ToolError(f"text_too_long: max {MAX_TEXT_CHARS} characters")
    if element.secure:
        raise ToolError("secure_field: Conn never types into password fields")
    bundle_id, pid = store.backend.frontmost()
    submit = bool(args.get("submit", False))
    if submit and _submit_uncertain(bundle_id, element, raw):
        raise ToolError("submit_uncertain_field")
    _click_like(store, element, backend)
    for chunk in _chunks(text, TYPE_CHUNK_CHARS):
        _require_focus(backend, pid, element.path)
        backend.type_unicode(chunk)
    if submit:
        _require_focus(backend, pid, element.path)
        backend.key_chord(("return",))
    return {"ref": element.ref, "typed": len(text), "submitted": submit}


def scroll(args: dict, ctx: ExecutionContext) -> dict:
    store = _store(ctx)
    backend = _input_backend(ctx)
    _require_posting(backend)
    element, _raw = store.resolve(args["snapshot_id"], args["ref"], for_execution=True)
    _bundle_id, pid = store.backend.frontmost()
    if backend.scroll_to_visible(pid, element.path):
        return {"ref": element.ref, "via": "ax_scroll"}
    scroll_target = _nearest_scroll_target(store, pid, element.path)
    if scroll_target is None:
        raise ToolError("scroll_area_not_found")
    if not _is_visible(_node_frame(scroll_target), backend.frontmost_window_frame(pid)):
        raise ToolError("element_not_visible: scroll it into view or re-snapshot")
    cx, cy = _center(_node_frame(scroll_target))
    backend.scroll_wheel(cx, cy, -6)
    return {"ref": element.ref, "via": "scroll_wheel"}


def hotkey(args: dict, ctx: ExecutionContext) -> dict:
    backend = _posting_backend(ctx)
    _require_posting(backend)
    combo = _normalize_combo(str(args["combo"]))
    keys = _parse_combo(combo)
    backend.key_chord(keys)
    return {"combo": combo, "lane": backend.lane}


def focus_tab(args: dict, ctx: ExecutionContext) -> dict:
    store = _store(ctx)
    backend = _input_backend(ctx)
    _require_posting(backend)
    bundle_id, pid = store.backend.frontmost()
    _require_named_app_frontmost(args, bundle_id)
    window = store.backend.window_element(pid)
    root = next(store.backend.walk(window, 12))
    candidates = [
        (element_path, raw, raw.title or "")
        for element_path, raw, parent in _walk_with_parent(root)
        if _is_tab_candidate(bundle_id, raw, parent)
    ]
    result = _choose_match(args["title"], candidates)
    if result["match"] is None:
        return {"candidates": result["candidates"]}
    path, raw, title = result["match"]
    if not backend.ax_press(pid, path):
        frame = _node_frame(raw)
        if not _is_visible(frame, backend.frontmost_window_frame(pid)):
            raise ToolError("element_not_visible: scroll it into view or re-snapshot")
        if not backend.coordinate_fallback_safe(pid, path):
            raise ToolError("element_not_visible: scroll it into view or re-snapshot")
        cx, cy = _center(frame)
        backend.click(cx, cy, pid=pid, path=path)
    return {"focused": title}


def menu(args: dict, ctx: ExecutionContext) -> dict:
    store = _store(ctx)
    backend = _posting_backend(ctx)
    _require_posting(backend)
    bundle_id, pid = store.backend.frontmost()
    _require_named_app_frontmost(args, bundle_id)
    if isinstance(backend, AppLaneInputBackend):
        root = backend.menu_tree(pid)
        if root is None:
            raise ToolError("app_lane_error: menu bar not readable through Conn.app")
    else:
        root = getattr(store.backend, "menu_root", None) or store.backend.menu_bar(pid)
    if root is None:
        return {"candidates": []}
    titles: list[str] = []
    current = root
    for segment in list(args["path"]):
        children = [(child, child.title or "") for child in current.children if child.title]
        result = _choose_match(segment, [((index,), child, title) for index, (child, title) in enumerate(children)])
        if result["match"] is None:
            return {"candidates": [title for _path, _raw, title in result["ranked"]]}
        _path, matched, title = result["match"]
        titles.append(title)
        current = matched
    if not backend.press_menu_path(pid, tuple(titles)):
        raise ToolError("menu_press_failed")
    return {"pressed": titles}


def _store(ctx: ExecutionContext):
    store = getattr(ctx, "ax", None)
    if store is None:
        raise ToolError("ax_unavailable")
    return store


def _input_backend(ctx: ExecutionContext) -> InputBackend:
    backend = getattr(ctx, "input_backend", None)
    if backend is None:
        backend = MacInputBackend()
        ctx.input_backend = backend
    return backend


def _posting_backend(ctx: ExecutionContext) -> InputBackend:
    """The backend for pure event posting (hotkey, menu press): Conn.app's
    lane when the app is attached, the python lane otherwise. An injected
    ctx.input_backend always wins so tests and callers can pin a lane."""
    injected = getattr(ctx, "input_backend", None)
    if injected is not None:
        return injected
    bridge = getattr(ctx, "ax_reader", None)
    if bridge is not None and getattr(bridge, "app_present", False):
        return AppLaneInputBackend(bridge)
    return _input_backend(ctx)


def _require_posting(backend: InputBackend) -> None:
    if not backend.posting_capability():
        if getattr(backend, "lane", "python") == "app":
            raise ToolError(
                "accessibility_untrusted: app lane; Conn.app's Accessibility "
                "grant is off. Toggle Conn off and on in System Settings, "
                "Privacy and Security, Accessibility"
            )
        from ..identity import grant_target

        raise ToolError(
            "accessibility_untrusted: python lane; grant Accessibility to "
            f"{grant_target()} in System Settings, Privacy and Security, "
            "then relaunch the daemon"
        )


def _click_like(store, element, backend: InputBackend) -> str:
    _bundle_id, pid = store.backend.frontmost()
    if backend.ax_press(pid, element.path):
        return "ax_press"
    if not _is_visible(element.frame, backend.frontmost_window_frame(pid)):
        raise ToolError("element_not_visible: scroll it into view or re-snapshot")
    if not backend.coordinate_fallback_safe(pid, element.path):
        raise ToolError("element_not_visible: scroll it into view or re-snapshot")
    cx, cy = _center(element.frame)
    backend.click(cx, cy, pid=pid, path=element.path)
    return "cg_event_click"


def _require_focus(backend: InputBackend, pid: int, path: tuple[int, ...]) -> None:
    if backend.focused_path(pid) != path:
        raise ToolError("focus_changed: take a new snapshot")


def _require_named_app_frontmost(args: dict, bundle_id: str) -> None:
    app = str(args.get("app") or "").strip()
    if not app:
        return
    if not app_matches_bundle(app, bundle_id):
        raise ToolError(f"app_not_frontmost: {app}")


def _submit_uncertain(bundle_id: str, element, raw: RawNode) -> bool:
    if bundle_id not in BROWSER_BUNDLES:
        return False
    if element.secure:
        return False
    if element.role not in TEXT_INPUT_ROLES:
        return False
    if raw.subrole == "AXSecureTextField":
        return False
    hints = " ".join(str(hint).lower() for hint in raw.secure_hints)
    if "password" in hints:
        return False
    return True


def _nearest_scroll_target(store, pid: int, path: tuple[int, ...]) -> RawNode | None:
    for depth in range(len(path), -1, -1):
        candidate = store.backend.resolve_path(pid, path[:depth])
        if candidate is None:
            continue
        if candidate.role in SCROLL_ROLES or "scroll" in candidate.role.lower():
            return candidate
    return None


def _normalize_combo(combo: str) -> str:
    aliases = {
        "command": "cmd",
        "cmd": "cmd",
        # The model speaks cross-platform: meta/super/win all mean cmd on a
        # Mac. Without these, "meta+t" parses as two primary keys and dies.
        "meta": "cmd",
        "super": "cmd",
        "win": "cmd",
        "control": "ctrl",
        "ctrl": "ctrl",
        "option": "alt",
        "opt": "alt",
        "alt": "alt",
        "shift": "shift",
        "enter": "return",
        "return": "return",
        "esc": "escape",
    }
    parts = [part.strip().lower() for part in combo.split("+") if part.strip()]
    normalized = [aliases.get(part, part) for part in parts]
    modifiers = [part for part in MODIFIER_ORDER if part in normalized]
    primary = [part for part in normalized if part not in MODIFIER_ORDER]
    if len(primary) != 1:
        raise ToolError("invalid_hotkey: expected exactly one primary key")
    return "+".join([*modifiers, primary[0]])


def _parse_combo(combo: str) -> tuple[str, ...]:
    parts = tuple(combo.split("+"))
    primary = parts[-1]
    if primary not in KEYCODES:
        raise ToolError(f"invalid_hotkey: unsupported key {primary}")
    return parts


def _choose_match(query: str, candidates: list[tuple[tuple[int, ...], RawNode, str]]) -> dict:
    normalized_query = str(query).strip().lower()
    ranked = sorted(
        (
            (path, raw, title, SequenceMatcher(None, normalized_query, title.lower()).ratio())
            for path, raw, title in candidates
            if title
        ),
        key=lambda item: item[3],
        reverse=True,
    )
    if not ranked:
        return {"match": None, "candidates": [], "ranked": []}
    best = ranked[0]
    candidate_titles = [title for _path, _raw, title, _score in ranked]
    if best[3] < MATCH_THRESHOLD:
        return {"match": None, "candidates": candidate_titles, "ranked": [(path, raw, title) for path, raw, title, _score in ranked]}
    close = [item for item in ranked if best[3] - item[3] <= AMBIGUITY_DELTA]
    if len(close) > 1:
        return {"match": None, "candidates": candidate_titles, "ranked": [(path, raw, title) for path, raw, title, _score in ranked]}
    return {
        "match": (best[0], best[1], best[2]),
        "candidates": candidate_titles,
        "ranked": [(path, raw, title) for path, raw, title, _score in ranked],
    }


def _walk_with_parent(root: RawNode, path: tuple[int, ...] = (), parent: RawNode | None = None):
    for index, child in enumerate(root.children):
        child_path = (*path, index)
        yield child_path, child, root
        yield from _walk_with_parent(child, child_path, child)


def _is_tab_candidate(bundle_id: str, raw: RawNode, parent: RawNode | None) -> bool:
    role_lower = raw.role.lower()
    subrole_lower = raw.subrole.lower()
    if raw.role in TAB_ROLES:
        return True
    if raw.role == "AXRadioButton" and parent is not None and parent.role == "AXTabGroup":
        return True
    if "tab" in role_lower or "tab" in subrole_lower:
        return True
    if bundle_id in BROWSER_BUNDLES and raw.role == "AXButton" and "tab" in (raw.title or "").lower():
        return True
    return False


def _chunks(text: str, size: int):
    for start in range(0, len(text), size):
        yield text[start:start + size]


def _center(frame: tuple[float, float, float, float]) -> tuple[float, float]:
    x, y, w, h = frame
    return x + (w / 2.0), y + (h / 2.0)


def _is_visible(frame: tuple[float, float, float, float], window_frame: tuple[float, float, float, float] | None) -> bool:
    if window_frame is None:
        return False
    return _intersects(frame, window_frame)


def _intersects(left: tuple[float, float, float, float], right: tuple[float, float, float, float]) -> bool:
    lx, ly, lw, lh = left
    rx, ry, rw, rh = right
    if lw <= 0 or lh <= 0 or rw <= 0 or rh <= 0:
        return False
    return not (
        lx + lw <= rx
        or rx + rw <= lx
        or ly + lh <= ry
        or ry + rh <= ly
    )


def _node_frame(raw: RawNode) -> tuple[float, float, float, float]:
    return tuple(float(part) for part in raw.frame)


def _point(value: object | None) -> tuple[float, float]:
    if value is None:
        return 0.0, 0.0
    for attrs in (("x", "y"), ("X", "Y")):
        if all(hasattr(value, attr) for attr in attrs):
            return float(getattr(value, attrs[0])), float(getattr(value, attrs[1]))
    if isinstance(value, (tuple, list)) and len(value) >= 2:
        return float(value[0]), float(value[1])
    return 0.0, 0.0


def _size(value: object | None) -> tuple[float, float]:
    if value is None:
        return 0.0, 0.0
    for attrs in (("width", "height"), ("Width", "Height")):
        if all(hasattr(value, attr) for attr in attrs):
            return float(getattr(value, attrs[0])), float(getattr(value, attrs[1]))
    if isinstance(value, (tuple, list)) and len(value) >= 2:
        return float(value[0]), float(value[1])
    return 0.0, 0.0
