"""Canned executors for demo mode: the full loop runs with zero side effects
and zero credentials. Keyed by tool name; anything not listed falls through to
the real executor.
"""

from __future__ import annotations

from ..actions import simulated_verified_receipt
from .base import ExecutionContext


def _get_context(args: dict, ctx: ExecutionContext) -> dict:
    return {"app": "Obsidian", "bundle_id": "md.obsidian",
            "window_title": "tasks.md - phoenix", "selected_text": None,
            "accessibility": "granted", "simulated": True}


def _screenshot(args: dict, ctx: ExecutionContext) -> dict:
    return {"path": str(ctx.screenshot_dir / "demo.png"), "bytes": 0, "simulated": True}


def _open_app(args: dict, ctx: ExecutionContext) -> dict:
    data = {"app": args.get("app"), "activated": True, "simulated": True}
    return simulated_verified_receipt(
        target=str(args.get("app")), effect="frontmost app matches requested app", data=data)


def _browser_search(args: dict, ctx: ExecutionContext) -> dict:
    data = {"url": f"https://www.google.com/search?q={args.get('query', '')}",
            "simulated": True}
    return simulated_verified_receipt(
        target="browser search", effect="browser search URL opened", data=data)


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
    data = {"path": args.get("path"), "opened_via": "obsidian_url", "simulated": True}
    return simulated_verified_receipt(
        target=str(args.get("path")), effect="requested note opened", data=data)


def _clipboard_set(args: dict, ctx: ExecutionContext) -> dict:
    data = {"chars": len(str(args.get("text", ""))), "simulated": True}
    return simulated_verified_receipt(
        target="clipboard", effect="clipboard hash matches payload hash", data=data)


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
    data = {"ref": args.get("ref"), "via": "ax_press", "simulated": True}
    return simulated_verified_receipt(
        target=str(args.get("ref")), effect="fixture target state changed", data=data)


def _type_text(args: dict, ctx: ExecutionContext) -> dict:
    text = str(args.get("text", ""))
    data = {
        "ref": args.get("ref"),
        "typed": len(text),
        "submitted": bool(args.get("submit", False)),
        "simulated": True,
    }
    return simulated_verified_receipt(
        target=str(args.get("ref")), effect="field value matches text", data=data)


def _scroll(args: dict, ctx: ExecutionContext) -> dict:
    data = {"ref": args.get("ref"), "via": "ax_scroll", "simulated": True}
    return simulated_verified_receipt(
        target=str(args.get("ref")), effect="scroll position changed", data=data)


def _hotkey(args: dict, ctx: ExecutionContext) -> dict:
    data = {"combo": args.get("combo"), "simulated": True}
    return simulated_verified_receipt(
        target=str(args.get("combo")), effect="fixture effect predicate matched", data=data)


def _focus_tab(args: dict, ctx: ExecutionContext) -> dict:
    data = {"focused": args.get("title"), "simulated": True}
    return simulated_verified_receipt(
        target=str(args.get("title")), effect="selected tab matches target", data=data)


def _menu(args: dict, ctx: ExecutionContext) -> dict:
    data = {"pressed": list(args.get("path", [])), "simulated": True}
    return simulated_verified_receipt(
        target=" > ".join(args.get("path", [])), effect="fixture menu effect matched", data=data)


def _create(args: dict, ctx: ExecutionContext) -> dict:
    data = {"created": args.get("kind"), "simulated": True}
    return simulated_verified_receipt(
        target=f"new {args.get('kind', 'item')}",
        effect="simulated create effect", data=data)


def _select_relative(args: dict, ctx: ExecutionContext) -> dict:
    data = {"selected": f"{args.get('relation')} {args.get('kind', 'item')}",
            "simulated": True}
    return simulated_verified_receipt(
        target=str(data["selected"]),
        effect="simulated selection change", data=data)


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
    "computer_create": _create,
    "computer_select_relative": _select_relative,
}
