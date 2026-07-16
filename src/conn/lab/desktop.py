from __future__ import annotations

from dataclasses import asdict, dataclass
import json


@dataclass(frozen=True, slots=True)
class WindowRecord:
    number: int
    owner: str
    layer: int
    x: float
    y: float
    width: float
    height: float

    @property
    def center(self) -> tuple[int, int]:
        return (
            round(self.x + self.width / 2),
            round(self.y + self.height / 2),
        )


def select_new_window(
    before: list[WindowRecord],
    after: list[WindowRecord],
    *,
    owner: str,
    layer: int,
) -> WindowRecord:
    existing = {window.number for window in before}
    matches = [
        window for window in after
        if (
            window.number not in existing
            and window.owner == owner
            and window.layer == layer
        )
    ]
    if not matches:
        raise ValueError("expected lab window is missing")
    if len(matches) != 1:
        raise ValueError("expected lab window is ambiguous")
    return matches[0]


def navigation_menu_point(menu: WindowRecord) -> tuple[int, int]:
    if (
        menu.owner != "Conn"
        or menu.layer != 101
        or not 240 <= menu.width <= 520
        or not 240 <= menu.height <= 360
    ):
        raise ValueError("unexpected Conn navigation menu shape")
    return menu.center


def approval_point(panel: WindowRecord) -> tuple[int, int]:
    if (
        panel.owner != "Conn"
        or panel.layer != 25
        or panel.width != 424
        or panel.height != 196
    ):
        raise ValueError("unexpected Conn approval panel shape")
    return (
        round(panel.x + panel.width - 58),
        round(panel.y + 125),
    )


def notes_new_note_point(window: WindowRecord) -> tuple[int, int]:
    if (
        window.owner != "Notes"
        or window.layer != 0
        or window.width != 1000
        or window.height != 660
    ):
        raise ValueError("unexpected Notes golden window shape")
    return (
        round(window.x + 537),
        round(window.y + 28),
    )


def snapshot() -> dict:
    import AppKit
    import Quartz

    records = []
    raw_windows = Quartz.CGWindowListCopyWindowInfo(
        Quartz.kCGWindowListOptionOnScreenOnly,
        Quartz.kCGNullWindowID,
    )
    for value in raw_windows:
        bounds = value.get("kCGWindowBounds")
        owner = value.get("kCGWindowOwnerName")
        number = value.get("kCGWindowNumber")
        layer = value.get("kCGWindowLayer")
        if (
            bounds is None
            or not isinstance(owner, str)
            or not isinstance(number, int)
            or not isinstance(layer, int)
        ):
            continue
        records.append(WindowRecord(
            number=number,
            owner=owner,
            layer=layer,
            x=float(bounds["X"]),
            y=float(bounds["Y"]),
            width=float(bounds["Width"]),
            height=float(bounds["Height"]),
        ))
    frame = AppKit.NSScreen.mainScreen().frame()
    frontmost = AppKit.NSWorkspace.sharedWorkspace().frontmostApplication()
    return {
        "frontmost_bundle": (
            frontmost.bundleIdentifier() if frontmost is not None else None
        ),
        "screen": {
            "width": float(frame.size.width),
            "height": float(frame.size.height),
        },
        "windows": [asdict(record) for record in records],
    }


def main() -> None:
    print(json.dumps(snapshot(), separators=(",", ":"), sort_keys=True))


if __name__ == "__main__":
    main()
