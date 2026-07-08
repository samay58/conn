"""The tool contract. Every tool declares its schema, risk level, a preview
renderer for approval chips, and good/rejected call examples (which double as
spec documentation and test fixtures).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from . import mac, phoenix
from .ax_input import click, focus_tab, hotkey, menu, scroll, type_text
from .base import ExecutionContext, ToolError
from .risk import RiskLevel

Executor = Callable[[dict, ExecutionContext], dict]


def _never_runs(args: dict, ctx: ExecutionContext) -> dict:
    raise AssertionError("blocked tool reached an executor; the gate is broken")


def _ax_snapshot(args: dict, ctx: ExecutionContext) -> dict:
    if ctx.ax is None:
        raise ToolError("ax_unavailable")
    query = args.get("query")
    snapshot = ctx.ax.take(query)
    return {"snapshot_id": snapshot.snapshot_id, "render": snapshot.render(query)}


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    parameters: dict
    risk: RiskLevel
    preview: Callable[[dict], str]
    executor: Executor
    timeout_s: float = 10.0
    good_examples: tuple[str, ...] = ()
    rejected_examples: tuple[str, ...] = ()


def _obj(properties: dict, required: list[str]) -> dict:
    return {"type": "object", "properties": properties, "required": required}


def build_registry() -> dict[str, ToolSpec]:
    specs = [
        ToolSpec(
            name="computer_get_context",
            description=(
                "Read the current foreground context: frontmost app, window title, "
                "and selected text when accessibility access is granted. Call this "
                "before acting when the target is ambiguous."
            ),
            parameters=_obj({}, []),
            risk=RiskLevel.READ,
            preview=lambda a: "Read current app and window",
            executor=mac.get_context,
            good_examples=('{"name": "computer_get_context", "arguments": {}}',),
        ),
        ToolSpec(
            name="computer_screenshot",
            description=(
                "Capture one screenshot for visual grounding. Use only when the "
                "accessible context is not enough. The image stays local and is "
                "deleted at session end by default."
            ),
            parameters=_obj({}, []),
            risk=RiskLevel.READ,
            preview=lambda a: "Take a screenshot",
            executor=mac.screenshot,
            good_examples=('{"name": "computer_screenshot", "arguments": {}}',),
            rejected_examples=(
                'Repeated calls to watch the screen continuously: screenshots are on-demand only.',
            ),
        ),
        ToolSpec(
            name="app_open",
            description="Open an application by name. Only allowlisted apps succeed.",
            parameters=_obj({"app": {"type": "string", "description": "Exact app name, e.g. 'Obsidian'"}}, ["app"]),
            risk=RiskLevel.ACT_LOW,
            preview=lambda a: f"Open app: {a.get('app', '?')}",
            executor=mac.open_app,
            good_examples=('{"name": "app_open", "arguments": {"app": "Obsidian"}}',),
            rejected_examples=('{"app": "Disk Utility"} when Disk Utility is not on the allowlist',),
        ),
        ToolSpec(
            name="app_switch",
            description="Switch focus to an app that is already running. Only allowlisted apps succeed.",
            parameters=_obj({"app": {"type": "string"}}, ["app"]),
            risk=RiskLevel.ACT_LOW,
            preview=lambda a: f"Switch to app: {a.get('app', '?')}",
            executor=mac.switch_app,
            good_examples=('{"name": "app_switch", "arguments": {"app": "Google Chrome"}}',),
        ),
        ToolSpec(
            name="browser_search",
            description="Open a web search for a query in the default browser.",
            parameters=_obj({"query": {"type": "string"}}, ["query"]),
            risk=RiskLevel.ACT_LOW,
            preview=lambda a: f"Search the web: {a.get('query', '?')}",
            executor=mac.browser_search,
            good_examples=('{"name": "browser_search", "arguments": {"query": "openai realtime api docs"}}',),
        ),
        ToolSpec(
            name="phoenix_search",
            description=(
                "Search Samay's Phoenix vault (markdown knowledge base) by keyword. "
                "Returns paths, titles, scores, and snippets. Use before opening notes."
            ),
            parameters=_obj(
                {"query": {"type": "string"}, "limit": {"type": "integer", "description": "max results, default 5"}},
                ["query"],
            ),
            risk=RiskLevel.READ,
            preview=lambda a: f"Search Phoenix: {a.get('query', '?')}",
            executor=phoenix.phoenix_search,
            timeout_s=25.0,
            good_examples=('{"name": "phoenix_search", "arguments": {"query": "transformer paper"}}',),
        ),
        ToolSpec(
            name="phoenix_open_note",
            description="Open a vault note in Obsidian by vault-relative path (from phoenix_search results).",
            parameters=_obj({"path": {"type": "string"}}, ["path"]),
            risk=RiskLevel.ACT_LOW,
            preview=lambda a: f"Open note: {a.get('path', '?')}",
            executor=phoenix.open_note,
            good_examples=('{"name": "phoenix_open_note", "arguments": {"path": "01-active/tasks.md"}}',),
            rejected_examples=('{"path": "../../etc/hosts"} resolves outside the vault and is blocked',),
        ),
        ToolSpec(
            name="clipboard_set",
            description="Copy text to the clipboard.",
            parameters=_obj({"text": {"type": "string"}}, ["text"]),
            risk=RiskLevel.ACT_LOW,
            preview=lambda a: "Copy to clipboard",
            executor=mac.clipboard_set,
            good_examples=('{"name": "clipboard_set", "arguments": {"text": "qmd search ..."}}',),
        ),
        ToolSpec(
            name="wait_for_user",
            description=(
                "No-op. Call when audio was unclear or silent, or when you need the "
                "user to speak again before doing anything."
            ),
            parameters=_obj({}, []),
            risk=RiskLevel.READ,
            preview=lambda a: "Wait for you to speak",
            executor=mac.wait_for_user,
        ),
        ToolSpec(
            name="computer_ax_snapshot",
            description="Capture a bounded accessibility snapshot of the frontmost window for grounded UI actions.",
            parameters=_obj({"query": {"type": "string"}}, []),
            risk=RiskLevel.READ,
            preview=lambda a: "Read accessibility snapshot",
            executor=_ax_snapshot,
            good_examples=('{"name": "computer_ax_snapshot", "arguments": {"query": "send"}}',),
        ),
        ToolSpec(
            name="computer_click",
            description="Click a UI element by grounded snapshot reference.",
            parameters=_obj({"snapshot_id": {"type": "string"}, "ref": {"type": "string"}}, ["snapshot_id", "ref"]),
            risk=RiskLevel.ACT_CONFIRM,
            preview=lambda a: f"Click element: {a.get('ref', '?')}",
            executor=click,
        ),
        ToolSpec(
            name="computer_type_text",
            description="Type into a grounded field reference, with optional submit.",
            parameters=_obj(
                {
                    "snapshot_id": {"type": "string"},
                    "ref": {"type": "string"},
                    "text": {"type": "string"},
                    "submit": {"type": "boolean"},
                },
                ["snapshot_id", "ref", "text"],
            ),
            risk=RiskLevel.ACT_CONFIRM,
            preview=lambda a: "Type text",
            executor=type_text,
        ),
        ToolSpec(
            name="computer_scroll",
            description="Scroll a grounded element into view.",
            parameters=_obj({"snapshot_id": {"type": "string"}, "ref": {"type": "string"}}, ["snapshot_id", "ref"]),
            risk=RiskLevel.ACT_LOW,
            preview=lambda a: f"Scroll to element: {a.get('ref', '?')}",
            executor=scroll,
        ),
        ToolSpec(
            name="computer_hotkey",
            description=(
                "Press an allowlisted keyboard shortcut. Combo grammar: "
                "modifiers then one key, joined by '+', e.g. 'cmd+t' or "
                "'cmd+shift+t'. Modifiers: cmd, ctrl, alt, shift (meta and "
                "super mean cmd). Non-allowlisted combos are refused; use "
                "app_menu for menu actions instead."
            ),
            parameters=_obj({"combo": {"type": "string"}}, ["combo"]),
            risk=RiskLevel.ACT_CONFIRM,
            preview=lambda a: f"Press keys: {a.get('combo', '?')}",
            executor=hotkey,
        ),
        ToolSpec(
            name="app_focus_tab",
            description="Focus a tab-like element by fuzzy title match in the frontmost or named app.",
            parameters=_obj({"title": {"type": "string"}, "app": {"type": "string"}}, ["title"]),
            risk=RiskLevel.ACT_LOW,
            preview=lambda a: f"Focus tab: {a.get('title', '?')}",
            executor=focus_tab,
        ),
        ToolSpec(
            name="app_menu",
            description="Walk the app menu bar by path and press the terminal item.",
            parameters=_obj(
                {
                    "path": {"type": "array", "items": {"type": "string"}, "minItems": 1},
                    "app": {"type": "string"},
                },
                ["path"],
            ),
            risk=RiskLevel.ACT_CONFIRM,
            preview=lambda a: f"Use menu: {' > '.join(a.get('path', [])) or '?'}",
            executor=menu,
        ),
    ]
    return {s.name: s for s in specs}


def export_openai(registry: dict[str, ToolSpec]) -> list[dict]:
    return [
        {"type": "function", "name": s.name, "description": s.description, "parameters": s.parameters}
        for s in registry.values()
    ]
