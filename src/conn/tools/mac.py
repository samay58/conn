"""macOS executors. Zero osascript: LaunchServices, AX, and small CLIs only,
so v0 never triggers an Automation (Apple Events) prompt.

Executors are sync functions (dict args, ExecutionContext) -> dict data; the
harness runs them on a thread with a timeout and wraps errors.
"""

from __future__ import annotations

import subprocess
import time
from urllib.parse import quote_plus

from .base import ExecutionContext, ToolError


def get_context(args: dict, ctx: ExecutionContext) -> dict:
    from . import frontmost

    app = frontmost.frontmost_application()
    data: dict = {
        "app": str(app.localizedName()) if app else None,
        "bundle_id": str(app.bundleIdentifier()) if app else None,
        "window_title": None,
        "selected_text": None,
        "accessibility": "not_granted",
    }
    if app is None:
        return data
    try:
        from ApplicationServices import (
            AXIsProcessTrusted,
            AXUIElementCopyAttributeValue,
            AXUIElementCreateApplication,
            kAXFocusedUIElementAttribute,
            kAXFocusedWindowAttribute,
            kAXSelectedTextAttribute,
            kAXTitleAttribute,
        )

        if not AXIsProcessTrusted():
            return data
        data["accessibility"] = "granted"
        el = AXUIElementCreateApplication(app.processIdentifier())
        err, win = AXUIElementCopyAttributeValue(el, kAXFocusedWindowAttribute, None)
        if err == 0 and win is not None:
            err, title = AXUIElementCopyAttributeValue(win, kAXTitleAttribute, None)
            if err == 0 and title:
                data["window_title"] = str(title)
        err, focused = AXUIElementCopyAttributeValue(el, kAXFocusedUIElementAttribute, None)
        if err == 0 and focused is not None:
            err, sel = AXUIElementCopyAttributeValue(focused, kAXSelectedTextAttribute, None)
            if err == 0 and sel:
                data["selected_text"] = str(sel)[:2000]
    except Exception:
        pass  # AX is best-effort by design; app name alone is still useful
    return data


def screenshot(args: dict, ctx: ExecutionContext) -> dict:
    ctx.screenshot_dir.mkdir(parents=True, exist_ok=True)
    path = ctx.screenshot_dir / f"shot-{int(time.time() * 1000)}.png"
    proc = subprocess.run(
        ["/usr/sbin/screencapture", "-x", "-t", "png", str(path)],
        capture_output=True, timeout=10,
    )
    if proc.returncode != 0 or not path.exists():
        raise ToolError(f"screencapture failed: {proc.stderr.decode().strip() or proc.returncode}")
    return {"path": str(path), "bytes": path.stat().st_size,
            "note": "deleted at session end unless screenshots.keep is set"}


def open_app(args: dict, ctx: ExecutionContext) -> dict:
    return _open_dash_a(args["app"])


def switch_app(args: dict, ctx: ExecutionContext) -> dict:
    # LaunchServices activates a running app and launches it otherwise, so
    # open and switch share one safe mechanism.
    return _open_dash_a(args["app"])


def _open_dash_a(app: str) -> dict:
    proc = subprocess.run(["/usr/bin/open", "-a", app], capture_output=True, timeout=10)
    if proc.returncode != 0:
        raise ToolError(f"could not open {app!r}: {proc.stderr.decode().strip()}")
    return {"app": app, "activated": True}


def browser_search(args: dict, ctx: ExecutionContext) -> dict:
    url = ctx.cfg.browser.search_url.format(q=quote_plus(args["query"]))
    proc = subprocess.run(["/usr/bin/open", url], capture_output=True, timeout=10)
    if proc.returncode != 0:
        raise ToolError(f"could not open browser: {proc.stderr.decode().strip()}")
    return {"url": url}


def clipboard_set(args: dict, ctx: ExecutionContext) -> dict:
    text = str(args["text"])
    proc = subprocess.run(["/usr/bin/pbcopy"], input=text.encode(), timeout=10)
    if proc.returncode != 0:
        raise ToolError("pbcopy failed")
    return {"chars": len(text)}


def wait_for_user(args: dict, ctx: ExecutionContext) -> dict:
    return {"standing_by": True}
