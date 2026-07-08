from __future__ import annotations

from dataclasses import dataclass, field
import secrets
import time
from typing import Iterator, Protocol

from ..config import Config
from .base import ToolError


@dataclass
class RawNode:
    role: str
    subrole: str = ""
    title: str = ""
    value: object | None = None
    enabled: bool = True
    focused: bool = False
    secure_hints: tuple[object, ...] = ()
    frame: tuple[float, float, float, float] = (0.0, 0.0, 0.0, 0.0)
    children: tuple["RawNode", ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class AxElement:
    ref: str
    role: str
    label: str
    value: str | None
    enabled: bool
    focused: bool
    secure: bool
    frame: tuple[float, float, float, float]
    path: tuple[int, ...]
    sibling_counts: tuple[int, ...]


@dataclass(frozen=True)
class AxSnapshot:
    snapshot_id: str
    bundle_id: str
    window_title: str
    elements: tuple[AxElement, ...]
    taken_monotonic: float

    def render(self, query: str | None = None) -> str:
        elements = _filter_elements(self.elements, query)
        lines = [
            f'snapshot {self.snapshot_id} app={self.bundle_id} window="{_escape(self.window_title)}" elements={len(elements)}'
        ]
        for element in elements:
            indent = "  " * len(element.path)
            line = f'{indent}{element.ref} {element.role} "{_escape(element.label)}"'
            if element.value is not None:
                line += f' value="{_escape(element.value)}"'
            if not element.enabled:
                line += " (disabled)"
            if element.focused:
                line += " (focused)"
            lines.append(line)
        return "\n".join(lines)


class StaleRef(Exception):
    pass


class AxBackend(Protocol):
    def frontmost(self) -> tuple[str, int]: ...
    def window_element(self, pid: int) -> object: ...
    def walk(self, window: object, max_depth: int) -> Iterator[RawNode]: ...
    def resolve_path(self, pid: int, path: tuple[int, ...]) -> RawNode | None: ...
    def menu_bar(self, pid: int) -> RawNode | None: ...
    def enable_chromium_ax(self, pid: int) -> None: ...
    def restore_chromium_ax(self) -> None: ...


@dataclass(frozen=True)
class _StoredSnapshot:
    snapshot: AxSnapshot
    pid: int
    window_identity: object
    path_fingerprints: dict[
        tuple[int, ...],
        tuple[tuple[tuple[str, str, int], ...], ...],
    ]
    unambiguous_paths: dict[tuple[int, ...], bool]


class SnapshotStore:
    def __init__(self, backend: AxBackend, cfg: Config):
        self.backend = backend
        self.cfg = cfg
        self._snapshots: dict[str, _StoredSnapshot] = {}

    def take(self, query: str | None = None) -> AxSnapshot:
        bundle_id, pid = self.backend.frontmost()
        if bundle_id in _deny_bundles(self.cfg):
            raise ToolError(f"bundle_denied: {bundle_id}")
        if _is_chromium_bundle(bundle_id):
            self.backend.enable_chromium_ax(pid)
        window = self.backend.window_element(pid)
        root = _walk_root(self.backend.walk(window, _ax_int(self.cfg, "max_depth", 12)))
        all_elements = _elements_from_root(root)
        limited = _limit_elements(all_elements, _ax_int(self.cfg, "max_elements", 120))
        visible = _filter_elements(limited, query)
        snapshot = AxSnapshot(
            snapshot_id=secrets.token_hex(4),
            bundle_id=bundle_id,
            window_title=root.title,
            elements=tuple(visible),
            taken_monotonic=time.monotonic(),
        )
        self._snapshots[snapshot.snapshot_id] = _StoredSnapshot(
            snapshot=snapshot,
            pid=pid,
            window_identity=_window_identity(window),
            path_fingerprints={
                element.path: _path_fingerprint(root, element.path)
                for element in all_elements
            },
            unambiguous_paths={element.path: _path_unambiguous(root, element.path) for element in all_elements},
        )
        return snapshot

    def resolve(self, snapshot_id: str, ref: str, *, for_execution: bool) -> tuple[AxElement, object]:
        stored = self._snapshots.get(snapshot_id)
        if stored is None:
            raise StaleRef("stale_ref: take a new snapshot")
        snapshot = stored.snapshot
        if not for_execution:
            ttl = _ax_float(self.cfg, "snapshot_ttl_s", 10.0)
            if time.monotonic() - snapshot.taken_monotonic > ttl:
                raise StaleRef("snapshot_expired: take a new snapshot")
        element = next((candidate for candidate in snapshot.elements if candidate.ref == ref), None)
        if element is None:
            raise StaleRef("stale_ref: take a new snapshot")
        bundle_id, pid = self.backend.frontmost()
        if bundle_id != snapshot.bundle_id or pid != stored.pid:
            raise StaleRef("window_changed: take a new snapshot")
        window = self.backend.window_element(pid)
        if _window_identity(window) != stored.window_identity:
            raise StaleRef("window_changed: take a new snapshot")
        root = _walk_root(self.backend.walk(window, _ax_int(self.cfg, "max_depth", 12)))
        if root.title != snapshot.window_title:
            raise StaleRef("window_changed: take a new snapshot")
        current_node = _node_at_path(root, element.path)
        if current_node is None:
            raise StaleRef("stale_ref: take a new snapshot")
        if (
            stored.path_fingerprints.get(element.path)
            != _path_fingerprint(root, element.path)
        ):
            raise StaleRef("stale_ref: take a new snapshot")
        if not stored.unambiguous_paths.get(element.path, False) or not _path_unambiguous(root, element.path):
            raise StaleRef("stale_ref: take a new snapshot")
        current_element = _element_from_node(current_node, element.path, _sibling_counts(root, element.path), _ancestor_secure(root, element.path))
        if not _same_grounding(element, current_element):
            raise StaleRef("stale_ref: take a new snapshot")
        return element, current_node


class FakeAxBackend:
    def __init__(self, bundle_id: str, pid: int, root: RawNode):
        self.bundle_id = bundle_id
        self.pid = pid
        self.root = root
        self.window_title = root.title
        self.ax_flags: dict[int, dict[str, object]] = {}
        self._prior_ax_flags: dict[int, dict[str, object]] = {}

    def frontmost(self) -> tuple[str, int]:
        return self.bundle_id, self.pid

    def window_element(self, pid: int) -> object:
        if pid != self.pid:
            raise ToolError(f"pid_not_frontmost: {pid}")
        return self.root

    def walk(self, window: object, max_depth: int) -> Iterator[RawNode]:
        root = window if isinstance(window, RawNode) else self.root
        yield _prune_depth(root, max_depth)

    def resolve_path(self, pid: int, path: tuple[int, ...]) -> RawNode | None:
        if pid != self.pid:
            return None
        return _node_at_path(self.root, path)

    def menu_bar(self, pid: int) -> RawNode | None:
        return None

    def enable_chromium_ax(self, pid: int) -> None:
        flags = self.ax_flags.setdefault(pid, {})
        if pid not in self._prior_ax_flags:
            self._prior_ax_flags[pid] = dict(flags)
        flags["AXEnhancedUserInterface"] = True
        flags["AXManualAccessibility"] = True

    def restore_chromium_ax(self) -> None:
        for pid, prior in self._prior_ax_flags.items():
            self.ax_flags[pid] = dict(prior)
        self._prior_ax_flags.clear()


class MacAxBackend:
    def __init__(self):
        self._apps: dict[int, object] = {}
        self._prior_ax_flags: dict[int, dict[str, object | None]] = {}

    def frontmost(self) -> tuple[str, int]:
        from . import frontmost

        app = frontmost.frontmost_application()
        if app is None:
            raise ToolError("frontmost_unavailable")
        return str(app.bundleIdentifier() or ""), int(app.processIdentifier())

    def window_element(self, pid: int) -> object:
        from ApplicationServices import AXIsProcessTrusted, AXUIElementCopyAttributeValue, AXUIElementCreateApplication, kAXFocusedWindowAttribute

        if not AXIsProcessTrusted():
            raise ToolError("ax_untrusted: Accessibility permission required")
        app = self._app(pid)
        err, window = AXUIElementCopyAttributeValue(app, kAXFocusedWindowAttribute, None)
        if err != 0 or window is None:
            raise ToolError("window_unavailable")
        return window

    def walk(self, window: object, max_depth: int) -> Iterator[RawNode]:
        yield self._read_node(window, max_depth)

    def resolve_path(self, pid: int, path: tuple[int, ...]) -> RawNode | None:
        try:
            window = self.window_element(pid)
            raw = self._read_node(window, len(path) + 1)
            return _node_at_path(raw, path)
        except ToolError:
            return None

    def menu_bar(self, pid: int) -> RawNode | None:
        from ApplicationServices import AXUIElementCopyAttributeValue, kAXMenuBarAttribute

        app = self._app(pid)
        err, menu = AXUIElementCopyAttributeValue(app, kAXMenuBarAttribute, None)
        if err != 0 or menu is None:
            return None
        return self._read_node(menu, 8)

    def enable_chromium_ax(self, pid: int) -> None:
        app = self._app(pid)
        prior = self._prior_ax_flags.setdefault(pid, {})
        for attr in ("AXEnhancedUserInterface", "AXManualAccessibility"):
            if attr not in prior:
                prior[attr] = self._copy_attr(app, attr)
            self._set_attr(app, attr, True)

    def restore_chromium_ax(self) -> None:
        for pid, attrs in list(self._prior_ax_flags.items()):
            app = self._apps.get(pid)
            if app is None:
                continue
            for attr, value in attrs.items():
                self._set_attr(app, attr, value)
        self._prior_ax_flags.clear()

    def _app(self, pid: int) -> object:
        from ApplicationServices import AXUIElementCreateApplication

        if pid not in self._apps:
            self._apps[pid] = AXUIElementCreateApplication(pid)
        return self._apps[pid]

    def _read_node(self, element: object, depth: int) -> RawNode:
        children = ()
        if depth > 0:
            raw_children = self._copy_attr(element, "AXChildren") or []
            children = tuple(self._read_node(child, depth - 1) for child in raw_children)
        return RawNode(
            role=str(self._copy_attr(element, "AXRole") or ""),
            subrole=str(self._copy_attr(element, "AXSubrole") or ""),
            title=str(self._copy_attr(element, "AXTitle") or self._copy_attr(element, "AXDescription") or self._copy_attr(element, "AXHelp") or ""),
            value=self._copy_attr(element, "AXValue"),
            enabled=bool(self._copy_attr(element, "AXEnabled") is not False),
            focused=bool(self._copy_attr(element, "AXFocused") is True),
            secure_hints=tuple(
                hint for hint in (
                    self._copy_attr(element, "AXDOMClassList"),
                    self._copy_attr(element, "AXRoleDescription"),
                    self._copy_attr(element, "AXDOMIdentifier"),
                ) if hint is not None
            ),
            frame=self._frame(element),
            children=children,
        )

    def _copy_attr(self, element: object, attr: str) -> object | None:
        from ApplicationServices import AXUIElementCopyAttributeValue

        try:
            err, value = AXUIElementCopyAttributeValue(element, attr, None)
        except Exception:
            return None
        if err != 0:
            return None
        return value

    def _set_attr(self, element: object, attr: str, value: object) -> None:
        from ApplicationServices import AXUIElementSetAttributeValue

        try:
            AXUIElementSetAttributeValue(element, attr, value)
        except Exception:
            pass

    def _frame(self, element: object) -> tuple[float, float, float, float]:
        position = self._copy_attr(element, "AXPosition")
        size = self._copy_attr(element, "AXSize")
        x, y = _point(position)
        w, h = _size(size)
        return (x, y, w, h)


_INTERACTIVE_ROLES = {
    "AXButton",
    "AXTab",
    "AXLink",
    "AXTextField",
    "AXTextArea",
    "AXCheckBox",
    "AXMenuItem",
    "AXRadioButton",
    "AXPopUpButton",
    "AXComboBox",
    "AXSecureTextField",
}

_MASK_CHARS = set("•●*••••••••")
_TEXT_INPUT_ROLES = {"AXTextField", "AXTextArea"}
_SECURE_LABELS = {"password", "passcode", "token", "secret", "otp", "cvv", "code"}
_CHROMIUM_BUNDLES = {
    "com.google.Chrome",
    "com.microsoft.edgemac",
    "com.brave.Browser",
    "org.chromium.Chromium",
    "com.operasoftware.Opera",
}


def _walk_root(nodes: Iterator[RawNode]) -> RawNode:
    try:
        return next(nodes)
    except StopIteration as exc:
        raise ToolError("window_empty") from exc


def _elements_from_root(root: RawNode) -> tuple[AxElement, ...]:
    elements: list[AxElement] = []

    def visit(raw: RawNode, path: tuple[int, ...], ancestor_secure: bool) -> None:
        secure = ancestor_secure or _node_is_secure(raw)
        elements.append(_element_from_node(raw, path, _sibling_counts(root, path), secure))
        for index, child in enumerate(raw.children):
            visit(child, (*path, index), secure)

    visit(root, (), False)
    return tuple(_assign_refs(elements))


def _assign_refs(elements: list[AxElement]) -> list[AxElement]:
    return [
        AxElement(
            ref=f"e{index}",
            role=element.role,
            label=element.label,
            value=element.value,
            enabled=element.enabled,
            focused=element.focused,
            secure=element.secure,
            frame=element.frame,
            path=element.path,
            sibling_counts=element.sibling_counts,
        )
        for index, element in enumerate(elements, start=1)
    ]


def _element_from_node(raw: RawNode, path: tuple[int, ...], sibling_counts: tuple[int, ...], secure: bool) -> AxElement:
    value = _render_value(raw.value, secure)
    return AxElement(
        ref="",
        role=raw.role,
        label=raw.title or "",
        value=value,
        enabled=raw.enabled,
        focused=raw.focused,
        secure=secure,
        frame=tuple(float(part) for part in raw.frame),
        path=path,
        sibling_counts=sibling_counts,
    )


def _render_value(value: object | None, secure: bool) -> str | None:
    if secure:
        return "[redacted]"
    if value is None:
        return None
    text = str(value)
    if text == "":
        return None
    return text[:80]


def _node_is_secure(raw: RawNode) -> bool:
    fields = [raw.role, raw.subrole, *(str(hint) for hint in raw.secure_hints)]
    lowered = " ".join(fields).lower()
    if "axsecuretextfield" in lowered:
        return True
    if "password" in lowered:
        return True
    if raw.role in _TEXT_INPUT_ROLES and _secure_label(raw.title):
        return True
    if raw.value is not None:
        text = str(raw.value)
        if text and all(char in _MASK_CHARS for char in text):
            return True
    return False


def _secure_label(label: str) -> bool:
    normalized = label.strip().lower().rstrip(":* ")
    return normalized in _SECURE_LABELS


def _filter_elements(elements: tuple[AxElement, ...], query: str | None) -> tuple[AxElement, ...]:
    if not query:
        return elements
    query_lower = query.lower()
    by_path = {element.path: element for element in elements}
    matched_paths: set[tuple[int, ...]] = set()
    for element in elements:
        haystack = [element.role, element.label]
        if element.value is not None and not element.secure:
            haystack.append(element.value)
        if any(query_lower in item.lower() for item in haystack):
            for depth in range(len(element.path) + 1):
                matched_paths.add(element.path[:depth])
    return tuple(element for element in elements if element.path in matched_paths and element.path in by_path)


def _limit_elements(elements: tuple[AxElement, ...], max_elements: int) -> tuple[AxElement, ...]:
    if len(elements) <= max_elements:
        return elements
    if max_elements <= 0:
        return ()
    paths_by_element = {element.path: element for element in elements}
    keep_paths: set[tuple[int, ...]] = set()
    for element in elements:
        if _is_interactive(element):
            for depth in range(len(element.path) + 1):
                keep_paths.add(element.path[:depth])
    if not keep_paths:
        return elements[:max_elements]
    ordered = [element for element in elements if element.path in keep_paths]
    if len(ordered) <= max_elements:
        return tuple(ordered)
    chosen: list[AxElement] = []
    for element in ordered:
        if element.path == ():
            chosen.append(element)
            break
    for element in ordered:
        if len(chosen) >= max_elements:
            break
        if _is_interactive(element) and element not in chosen:
            ancestors = [paths_by_element[element.path[:depth]] for depth in range(len(element.path)) if element.path[:depth] in paths_by_element]
            for ancestor in ancestors:
                if ancestor not in chosen and len(chosen) < max_elements:
                    chosen.append(ancestor)
            if element not in chosen and len(chosen) < max_elements:
                chosen.append(element)
    return tuple(element for element in elements if element in chosen)


def _is_interactive(element: AxElement) -> bool:
    return element.role in _INTERACTIVE_ROLES


def _sibling_counts(root: RawNode, path: tuple[int, ...]) -> tuple[int, ...]:
    counts: list[int] = []
    node = root
    for index in path:
        counts.append(len(node.children))
        if index >= len(node.children):
            return tuple(counts)
        node = node.children[index]
    return tuple(counts)


def _ancestor_secure(root: RawNode, path: tuple[int, ...]) -> bool:
    node = root
    secure = _node_is_secure(node)
    for index in path:
        if index >= len(node.children):
            return secure
        node = node.children[index]
        secure = secure or _node_is_secure(node)
    return secure


def _node_at_path(root: RawNode, path: tuple[int, ...]) -> RawNode | None:
    node = root
    for index in path:
        if index < 0 or index >= len(node.children):
            return None
        node = node.children[index]
    return node


def _window_identity(window: object) -> object:
    if isinstance(window, RawNode):
        return id(window)
    return window


def _path_fingerprint(
    root: RawNode,
    path: tuple[int, ...],
) -> tuple[tuple[tuple[str, str, int], ...], ...]:
    if not path:
        return ((_node_signature(root),),)
    fingerprint: list[tuple[tuple[str, str, int], ...]] = []
    node = root
    for index in path:
        fingerprint.append(tuple(_node_signature(child) for child in node.children))
        if index < 0 or index >= len(node.children):
            return tuple(fingerprint)
        node = node.children[index]
    return tuple(fingerprint)


def _path_unambiguous(root: RawNode, path: tuple[int, ...]) -> bool:
    node = root
    for index in path:
        if index < 0 or index >= len(node.children):
            return False
        selected = node.children[index]
        selected_signature = _node_signature(selected)
        collisions = (child for child in node.children if _node_signature(child) == selected_signature)
        if sum(1 for _child in collisions) != 1:
            return False
        node = node.children[index]
    return True


def _node_signature(raw: RawNode) -> tuple[str, str, int]:
    return (
        raw.role,
        raw.title or "",
        len(raw.children),
    )


def _same_grounding(old: AxElement, new: AxElement) -> bool:
    return (
        old.role == new.role
        and old.label == new.label
        and old.secure == new.secure
        and old.sibling_counts == new.sibling_counts
        and _frame_drift(old.frame, new.frame) <= 40.0
    )


def _frame_drift(a: tuple[float, float, float, float], b: tuple[float, float, float, float]) -> float:
    return max(abs(left - right) for left, right in zip(a, b))


def _prune_depth(raw: RawNode, max_depth: int) -> RawNode:
    if max_depth <= 0:
        return RawNode(
            role=raw.role,
            subrole=raw.subrole,
            title=raw.title,
            value=raw.value,
            enabled=raw.enabled,
            focused=raw.focused,
            secure_hints=raw.secure_hints,
            frame=raw.frame,
            children=(),
        )
    return RawNode(
        role=raw.role,
        subrole=raw.subrole,
        title=raw.title,
        value=raw.value,
        enabled=raw.enabled,
        focused=raw.focused,
        secure_hints=raw.secure_hints,
        frame=raw.frame,
        children=tuple(_prune_depth(child, max_depth - 1) for child in raw.children),
    )


def _deny_bundles(cfg: Config) -> list[str]:
    return list(_ax_value(cfg, "deny_bundles", ["com.1password.1password", "com.apple.keychainaccess"]))


def _ax_int(cfg: Config, name: str, default: int) -> int:
    return int(_ax_value(cfg, name, default))


def _ax_float(cfg: Config, name: str, default: float) -> float:
    return float(_ax_value(cfg, name, default))


def _ax_value(cfg: Config, name: str, default: object) -> object:
    ax_cfg = getattr(cfg, "ax", None)
    if ax_cfg is None:
        return default
    if isinstance(ax_cfg, dict):
        return ax_cfg.get(name, default)
    return getattr(ax_cfg, name, default)


def _is_chromium_bundle(bundle_id: str) -> bool:
    return bundle_id in _CHROMIUM_BUNDLES


def _escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


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
