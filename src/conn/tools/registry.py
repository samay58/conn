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
    computer_mutation: bool = False
    semantic_operation: str | None = None
    timeout_s: float = 10.0
    # Diagnostic tools keep their gates and allowlists but are hidden from
    # the default Realtime tool surface: the model describes goals, it does
    # not choose raw menu paths or key chords.
    diagnostic: bool = False
    good_examples: tuple[str, ...] = ()
    rejected_examples: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.computer_mutation != (self.semantic_operation is not None):
            raise ValueError(
                "computer mutation and semantic operation must be declared together"
            )


def _obj(properties: dict, required: list[str]) -> dict:
    return {"type": "object", "properties": properties, "required": required}


def _native_only(args: dict, ctx: ExecutionContext) -> dict:
    raise ToolError("native_app_unavailable: Conn.app is required for computer actions")


def build_registry() -> dict[str, ToolSpec]:
    specs = [
        ToolSpec(
            name="computer_get_context",
            description=(
                "Read the current foreground context: frontmost app and window. "
                "Selected text is excluded by default. Call this before acting "
                "when the target is ambiguous."
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
            executor=_native_only,
            good_examples=('{"name": "computer_screenshot", "arguments": {}}',),
            rejected_examples=(
                'Repeated calls to watch the screen continuously: screenshots are on-demand only.',
            ),
            diagnostic=True,
        ),
        ToolSpec(
            name="computer_visual_observe",
            description=(
                "Observe the current window visually when named Accessibility "
                "targets are unavailable. This reads one bounded current image."
            ),
            parameters=_obj({}, []),
            risk=RiskLevel.READ,
            preview=lambda a: "Observe current window visually",
            executor=_native_only,
        ),
        ToolSpec(
            name="app_open",
            description="Open an installed application by its exact visible name.",
            parameters=_obj({"app": {
                "type": "string", "minLength": 1, "maxLength": 128,
                "description": "Exact visible app name, e.g. 'Obsidian'",
            }}, ["app"]),
            risk=RiskLevel.ACT_LOW,
            preview=lambda a: f"Open app: {a.get('app', '?')}",
            executor=mac.open_app,
            computer_mutation=True,
            semantic_operation="open",
            good_examples=('{"name": "app_open", "arguments": {"app": "Obsidian"}}',),
        ),
        ToolSpec(
            name="app_switch",
            description="Switch focus to an installed app that is already running.",
            parameters=_obj({"app": {
                "type": "string", "minLength": 1, "maxLength": 128,
            }}, ["app"]),
            risk=RiskLevel.ACT_LOW,
            preview=lambda a: f"Switch to app: {a.get('app', '?')}",
            executor=mac.switch_app,
            computer_mutation=True,
            semantic_operation="switch",
            good_examples=('{"name": "app_switch", "arguments": {"app": "Google Chrome"}}',),
        ),
        ToolSpec(
            name="browser_search",
            description="Open a web search for a query in the default browser.",
            parameters=_obj({"query": {"type": "string"}}, ["query"]),
            risk=RiskLevel.ACT_LOW,
            preview=lambda a: f"Search the web: {a.get('query', '?')}",
            executor=mac.browser_search,
            computer_mutation=True,
            semantic_operation="open_url",
            good_examples=('{"name": "browser_search", "arguments": {"query": "openai realtime api docs"}}',),
        ),
        ToolSpec(
            name="browser_navigate",
            description=(
                "Open a literal URL or hostname supplied by the user. Never infer "
                "a site from an app or product name. Use browser_scope only when "
                "the user names a browser; otherwise Conn uses the current browser."
            ),
            parameters=_obj({
                "url": {"type": "string", "minLength": 1, "maxLength": 4096},
                "browser_scope": {
                    "type": "string", "minLength": 1, "maxLength": 128,
                    "description": "Exact visible browser name named by the user",
                },
            }, ["url"]),
            risk=RiskLevel.ACT_LOW,
            preview=lambda a: f"Open location: {a.get('url', '?')}",
            executor=_native_only,
            computer_mutation=True,
            semantic_operation="navigate",
            good_examples=(
                '{"name": "browser_navigate", "arguments": {"url": "example.com", "browser_scope": "Safari"}}',
            ),
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
            computer_mutation=True,
            semantic_operation="open_url",
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
            computer_mutation=True,
            semantic_operation="clipboard_write",
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
            description="Find bounded native candidates in the current app for grounded UI actions.",
            parameters=_obj({
                "query": {"type": "string"},
                "expected_roles": {"type": "array", "items": {"type": "string"}},
                "expected_actions": {"type": "array", "items": {"type": "string"}},
                "scope": {"type": "string", "enum": [
                    "current_window", "current_app", "descendant",
                ]},
                "ancestor_ref": {"type": "string"},
                "result_limit": {"type": "integer", "minimum": 1, "maximum": 20},
                "include_menu": {"type": "boolean"},
            }, []),
            risk=RiskLevel.READ,
            preview=lambda a: "Read accessibility snapshot",
            executor=_ax_snapshot,
            good_examples=('{"name": "computer_ax_snapshot", "arguments": {"query": "send"}}',),
        ),
        ToolSpec(
            name="computer_create",
            description=(
                "Create a new item in the current app: a tab, window, "
                "document, note, or folder. Conn discovers the native way to "
                "do it; name only what to create."
            ),
            parameters=_obj({
                "kind": {"type": "string",
                         "enum": ["tab", "window", "document", "note", "folder"]},
                "app": {"type": "string"},
            }, ["kind"]),
            risk=RiskLevel.ACT_LOW,
            preview=lambda a: f"Create a new {a.get('kind', 'item')}",
            executor=_native_only,
            computer_mutation=True,
            semantic_operation="semantic_intent",
            good_examples=('{"name": "computer_create", "arguments": {"kind": "tab"}}',),
            rejected_examples=(
                'Menu paths or shortcuts as arguments: Conn compiles the mechanism itself.',
            ),
        ),
        ToolSpec(
            name="computer_select_relative",
            description=(
                "Select the item next to the current selection: the next or "
                "previous tab, note, document, or list item."
            ),
            parameters=_obj({
                "relation": {"type": "string", "enum": ["next", "previous"]},
                "kind": {"type": "string",
                         "enum": ["tab", "document", "note", "item"]},
                "app": {"type": "string"},
            }, ["relation"]),
            risk=RiskLevel.ACT_LOW,
            preview=lambda a: (
                f"Select the {a.get('relation', 'next')} {a.get('kind', 'item')}"
            ),
            executor=_native_only,
            computer_mutation=True,
            semantic_operation="semantic_intent",
            good_examples=(
                '{"name": "computer_select_relative", "arguments": {"relation": "next", "kind": "note"}}',
            ),
        ),
        ToolSpec(
            name="computer_click",
            description="Click a UI element by grounded snapshot reference.",
            parameters=_obj({
                "snapshot_id": {"type": "string"},
                "ref": {"type": "string"},
            }, ["snapshot_id", "ref"]),
            risk=RiskLevel.ACT_CONFIRM,
            preview=lambda a: f"Click element: {a.get('ref', '?')}",
            executor=click,
            computer_mutation=True,
            semantic_operation="press",
            diagnostic=True,
        ),
        ToolSpec(
            name="computer_activate",
            description=(
                "Activate a reversible control such as Play, Pause, a link, "
                "or a tab. Use a semantic snapshot reference when available; "
                "otherwise use grounding from the current visual observation."
            ),
            parameters=_obj({
                "goal": {"type": "string", "minLength": 1, "maxLength": 160},
                "snapshot_id": {"type": "string"},
                "ref": {"type": "string"},
                "grounding": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "capture_id": {
                            "type": "string",
                            "minLength": 1,
                            "maxLength": 128,
                        },
                        "region": {
                            "type": "object",
                            "additionalProperties": False,
                            "properties": {
                                "x": {
                                    "type": "number",
                                    "minimum": 0,
                                    "maximum": 1,
                                },
                                "y": {
                                    "type": "number",
                                    "minimum": 0,
                                    "maximum": 1,
                                },
                                "width": {
                                    "type": "number",
                                    "exclusiveMinimum": 0,
                                    "maximum": 1,
                                },
                                "height": {
                                    "type": "number",
                                    "exclusiveMinimum": 0,
                                    "maximum": 1,
                                },
                            },
                            "required": ["x", "y", "width", "height"],
                        },
                        "label": {
                            "type": "string",
                            "minLength": 1,
                            "maxLength": 160,
                        },
                        "confidence": {
                            "type": "number",
                            "minimum": 0,
                            "maximum": 1,
                        },
                    },
                    "required": [
                        "capture_id",
                        "region",
                        "label",
                        "confidence",
                    ],
                },
            }, ["goal"]),
            risk=RiskLevel.ACT_LOW,
            preview=lambda a: f"Activate: {a.get('goal', '?')}",
            executor=_native_only,
            computer_mutation=True,
            semantic_operation="activate",
        ),
        ToolSpec(
            name="computer_key",
            description="Send one reversible navigation key to the foreground app.",
            parameters=_obj({
                "key": {"type": "string", "enum": [
                    "space", "escape", "tab", "left", "right", "up", "down",
                    "pageup", "pagedown", "home", "end",
                ]},
            }, ["key"]),
            risk=RiskLevel.ACT_LOW,
            preview=lambda a: f"Press key: {a.get('key', '?')}",
            executor=_native_only,
            computer_mutation=True,
            semantic_operation="key_chord",
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
            computer_mutation=True,
            semantic_operation="set_text",
        ),
        ToolSpec(
            name="computer_scroll",
            description="Scroll a grounded element into view or move its scroll value.",
            parameters=_obj({
                "snapshot_id": {"type": "string"},
                "ref": {"type": "string"},
                "direction": {"type": "string", "enum": ["up", "down", "left", "right"]},
                "amount": {"type": "number", "exclusiveMinimum": 0, "maximum": 10},
            }, ["snapshot_id", "ref"]),
            risk=RiskLevel.ACT_LOW,
            preview=lambda a: f"Scroll to element: {a.get('ref', '?')}",
            executor=scroll,
            computer_mutation=True,
            semantic_operation="scroll",
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
            parameters=_obj({
                "combo": {"type": "string"},
            }, ["combo"]),
            risk=RiskLevel.ACT_CONFIRM,
            preview=lambda a: f"Press keys: {a.get('combo', '?')}",
            executor=hotkey,
            computer_mutation=True,
            semantic_operation="key_chord",
            diagnostic=True,
        ),
        ToolSpec(
            name="app_focus_tab",
            description="Focus a tab-like element by fuzzy title match in the frontmost or named app.",
            parameters=_obj({"title": {"type": "string"}, "app": {"type": "string"}}, ["title"]),
            risk=RiskLevel.ACT_LOW,
            preview=lambda a: f"Focus tab: {a.get('title', '?')}",
            executor=focus_tab,
            computer_mutation=True,
            semantic_operation="focus_tab",
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
            computer_mutation=True,
            semantic_operation="invoke_menu",
            diagnostic=True,
        ),
    ]
    return {s.name: s for s in specs}


def export_openai(registry: dict[str, ToolSpec],
                  include_diagnostic: bool = False) -> list[dict]:
    return [
        {"type": "function", "name": s.name, "description": s.description, "parameters": s.parameters}
        for s in registry.values()
        if include_diagnostic or not s.diagnostic
    ]


def computer_mutation_names(registry: dict[str, ToolSpec]) -> frozenset[str]:
    return frozenset(name for name, spec in registry.items()
                     if spec.computer_mutation)
