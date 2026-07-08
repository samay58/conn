"""Per-call fresh frontmost-application source.

NSWorkspace.frontmostApplication() is KVO-cached and never updates in a
process whose main thread does not pump a runloop. The daemon is exactly
that process: asyncio owns the main thread and executors run on harness
threads, so the old source served whatever was frontmost at daemon spawn,
forever (the 2026-07-07 live drive read Kaku for ten minutes across four
app switches). Pumping CFRunLoopRunInMode from an executor thread does not
help; the KVO updates are delivered to the main thread's runloop.

The window server is the one per-call fresh source available to a
background thread, so frontmost is derived from the front layer-0
on-screen window, with owners filtered to regular-activation-policy apps
so accessory overlays (the Kaku/WindowManager class) never win.
"""

from __future__ import annotations

POLICY_REGULAR = 0    # NSApplicationActivationPolicyRegular
POLICY_ACCESSORY = 1  # NSApplicationActivationPolicyAccessory


def _front_window_owner_pids() -> list[int]:
    """Owner pids of on-screen layer-0 windows, front to back."""
    from Quartz import (
        CGWindowListCopyWindowInfo,
        kCGNullWindowID,
        kCGWindowListExcludeDesktopElements,
        kCGWindowListOptionOnScreenOnly,
    )

    windows = CGWindowListCopyWindowInfo(
        kCGWindowListOptionOnScreenOnly | kCGWindowListExcludeDesktopElements,
        kCGNullWindowID,
    )
    pids: list[int] = []
    for window in windows or []:
        if window.get("kCGWindowLayer") != 0:
            continue
        pid = window.get("kCGWindowOwnerPID")
        if pid is not None and pid not in pids:
            pids.append(int(pid))
    return pids


def _running_app(pid: int):
    from AppKit import NSRunningApplication

    return NSRunningApplication.runningApplicationWithProcessIdentifier_(pid)


def _workspace_frontmost():
    from AppKit import NSWorkspace

    return NSWorkspace.sharedWorkspace().frontmostApplication()


def frontmost_application():
    """The frontmost regular-activation-policy app, or None.

    Front layer-0 window owner first; NSWorkspace as a last resort for the
    windowless edge (its staleness is then the best information available).
    Accessory and prohibited apps never win on either path.
    """
    for pid in _front_window_owner_pids():
        app = _running_app(pid)
        if app is not None and app.activationPolicy() == POLICY_REGULAR:
            return app
    app = _workspace_frontmost()
    if app is not None and app.activationPolicy() == POLICY_REGULAR:
        return app
    return None
