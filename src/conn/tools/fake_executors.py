"""Canned executors for demo mode: the full loop runs with zero side effects
and zero credentials. Keyed by tool name; anything not listed falls through to
the real executor.
"""

from __future__ import annotations

from .base import ExecutionContext


def _get_context(args: dict, ctx: ExecutionContext) -> dict:
    return {"app": "Obsidian", "bundle_id": "md.obsidian",
            "window_title": "tasks.md - phoenix", "selected_text": None,
            "accessibility": "granted", "simulated": True}


def _screenshot(args: dict, ctx: ExecutionContext) -> dict:
    return {"path": str(ctx.screenshot_dir / "demo.png"), "bytes": 0, "simulated": True}


def _open_app(args: dict, ctx: ExecutionContext) -> dict:
    return {"app": args.get("app"), "activated": True, "simulated": True}


def _browser_search(args: dict, ctx: ExecutionContext) -> dict:
    return {"url": f"https://www.google.com/search?q={args.get('query', '')}",
            "simulated": True}


def _phoenix_search(args: dict, ctx: ExecutionContext) -> dict:
    return {
        "query": args.get("query"),
        "results": [
            {"path": "04-knowledge-base/reading-notes/transformer-paper-2017.md",
             "line": 1, "docid": "ac709a",
             "title": "Attention Is All You Need - reading notes",
             "score": 0.89, "snippet": "# Attention Is All You Need - reading notes"},
            {"path": "01-active/tasks.md", "line": 480, "docid": "b2f01c",
             "title": "Tasks", "score": 0.71,
             "snippet": "### Agent Tinkering - Learning by Osmosis + GPT Realtime 2"},
        ],
        "count": 2,
        "simulated": True,
    }


def _open_note(args: dict, ctx: ExecutionContext) -> dict:
    return {"path": args.get("path"), "opened_via": "obsidian_url", "simulated": True}


def _clipboard_set(args: dict, ctx: ExecutionContext) -> dict:
    return {"chars": len(str(args.get("text", ""))), "simulated": True}


def _ax_snapshot(args: dict, ctx: ExecutionContext) -> dict:
    snapshot_id = "demo1234"
    return {
        "snapshot_id": snapshot_id,
        "render": (
            f'snapshot {snapshot_id} app=md.obsidian window="tasks.md - phoenix" elements=3\n'
            'e1 AXWindow "tasks.md - phoenix"\n'
            '  e2 AXTextField "Search"\n'
            '  e3 AXButton "Open"'
        ),
        "simulated": True,
    }


def _click(args: dict, ctx: ExecutionContext) -> dict:
    return {"ref": args.get("ref"), "via": "ax_press", "simulated": True}


def _type_text(args: dict, ctx: ExecutionContext) -> dict:
    text = str(args.get("text", ""))
    return {
        "ref": args.get("ref"),
        "typed": len(text),
        "submitted": bool(args.get("submit", False)),
        "simulated": True,
    }


def _scroll(args: dict, ctx: ExecutionContext) -> dict:
    return {"ref": args.get("ref"), "via": "ax_scroll", "simulated": True}


def _hotkey(args: dict, ctx: ExecutionContext) -> dict:
    return {"combo": args.get("combo"), "simulated": True}


def _focus_tab(args: dict, ctx: ExecutionContext) -> dict:
    return {"focused": args.get("title"), "simulated": True}


def _menu(args: dict, ctx: ExecutionContext) -> dict:
    return {"pressed": list(args.get("path", [])), "simulated": True}


FAKE_EXECUTORS = {
    "computer_get_context": _get_context,
    "computer_screenshot": _screenshot,
    "app_open": _open_app,
    "app_switch": _open_app,
    "browser_search": _browser_search,
    "phoenix_search": _phoenix_search,
    "phoenix_open_note": _open_note,
    "clipboard_set": _clipboard_set,
    "computer_ax_snapshot": _ax_snapshot,
    "computer_click": _click,
    "computer_type_text": _type_text,
    "computer_scroll": _scroll,
    "computer_hotkey": _hotkey,
    "app_focus_tab": _focus_tab,
    "app_menu": _menu,
}
