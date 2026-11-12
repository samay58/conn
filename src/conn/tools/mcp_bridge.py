"""Turns configured MCP tools into ordinary Conn tools. Every word the model
or a chip sees comes from Conn's config; a server's own descriptions and
error text are untrusted and never pass through. Writes are local actions:
they wait for a pointer click and count as done only when the server read
its own write back and said so.
"""

from __future__ import annotations

import copy
import json
import re
from datetime import date, datetime

from ..config import Config
from ..mcp_client import McpCallFailed, McpNotConnected, McpToolInfo
from .base import ExecutionContext, ToolError
from .mcp_names import conn_name
from .registry import ToolSpec
from .risk import RiskLevel

PREVIEW_VALUE_MAX = 40
WITHHELD_MESSAGE = "That result touched protected work content, so I left it out."


class _Preview(dict):
    def __missing__(self, key):
        return "?"


_LOCAL_STAMP = re.compile(r"^(\d{4}-\d{2}-\d{2})(?:[ T](\d{2}):(\d{2}))?$")


def _clock(hour: int, minute: int) -> str:
    suffix = "AM" if hour < 12 else "PM"
    hour12 = hour % 12 or 12
    return f"{hour12} {suffix}" if minute == 0 else f"{hour12}:{minute:02d} {suffix}"


def friendly_stamp(value: str, today: date | None = None) -> str:
    """A local date or date-time argument as a person reads it on a chip: "today 9 AM",
    "tomorrow 2:30 PM", "Fri 9 AM", "Nov 20 9 AM". Exact to the minute, so the click
    approves the same moment the server receives. Anything else comes back unchanged."""
    match = _LOCAL_STAMP.match(value.strip())
    if not match:
        return value
    try:
        day = date.fromisoformat(match.group(1))
    except ValueError:
        return value
    today = today or datetime.now().date()
    delta = (day - today).days
    if delta == 0:
        when = "today"
    elif delta == 1:
        when = "tomorrow"
    elif 1 < delta < 7:
        when = day.strftime("%a")
    elif day.year == today.year:
        when = f"{day.strftime('%b')} {day.day}"
    else:
        when = f"{day.strftime('%b')} {day.day} {day.year}"
    if match.group(2) is None:
        return when
    hour, minute = int(match.group(2)), int(match.group(3))
    if hour > 23 or minute > 59:
        return value
    return f"{when} {_clock(hour, minute)}"


def _preview_fn(template: str, default: str, exported: frozenset[str]):
    def preview(args: dict) -> str:
        if not template:
            return default
        values = _Preview({
            k: friendly_stamp(str(v))[:PREVIEW_VALUE_MAX] for k, v in args.items() if k in exported})
        try:
            return template.format_map(values)
        except (KeyError, IndexError, ValueError, AttributeError):
            return default
    return preview


def _hits_marker(markers: list[str], text: str, structured) -> bool:
    if not markers:
        return False
    haystack = text.lower()
    if structured is not None:
        haystack += "\n" + json.dumps(structured, default=str).lower()
    return any(m.lower() in haystack for m in markers)


def _make_executor(server: str, tool: str, tool_cfg, server_cfg, cfg: Config,
                   manager, exported: frozenset[str]):
    is_write = tool_cfg.kind == "write"
    timeout = tool_cfg.timeout_s or cfg.mcp.call_timeout_s
    fixed = dict(tool_cfg.fixed_args)

    def execute(args: dict, ctx: ExecutionContext) -> dict:
        merged = {k: v for k, v in args.items() if k in exported}
        merged.update(fixed)
        try:
            result = manager.call_blocking(server, tool, merged, timeout)
        except McpNotConnected:
            raise  # nothing was sent
        except (McpCallFailed, TimeoutError):
            if is_write:
                raise ToolError("mcp_write_unknown: I sent that but didn't hear back, "
                                "so I won't retry it.") from None
            raise ToolError("mcp_timeout: the service didn't answer in time") from None

        if _hits_marker(server_cfg.withhold_markers, result.text, result.structured):
            if ctx.trace is not None:
                ctx.trace("mcp_result_withheld", server=server, tool=tool)
            if is_write:
                # A withheld write result proves nothing, so it cannot read as done.
                raise ToolError("mcp_write_unconfirmed: I sent that but couldn't confirm it landed.")
            return {"withheld": True, "safe_user_message": WITHHELD_MESSAGE}
        if result.is_error:
            raise ToolError("mcp_tool_error: the service returned an error")

        if is_write:
            if result.structured is not None and result.structured.get("verified") is True:
                return {"status": "verified", "safe_user_message": tool_cfg.done_message}
            raise ToolError("mcp_write_unconfirmed: I sent that but couldn't confirm it landed.")

        # The MCP spec has a server repeat its structured result as JSON text, so sending
        # both doubled every read (Phoenix's today: 3,817 characters, 1,644 without the
        # copy). Structured wins when it fits; otherwise the text, cut to the limit.
        limit = tool_cfg.max_result_chars
        structured = result.structured
        if structured is not None and len(json.dumps(structured, default=str)) <= limit:
            return {"structured": structured}
        return {"text": result.text[:limit]}

    return execute


def register_mcp_tools(
    registry: dict[str, ToolSpec],
    infos: list[McpToolInfo],
    cfg: Config,
    manager,
) -> list[tuple[str, str]]:
    refusals: list[tuple[str, str]] = []
    servers = {s.name: s for s in cfg.mcp.servers}
    registered = 0
    for info in infos:
        server_cfg = servers.get(info.server)
        tool_cfg = server_cfg.tools.get(info.tool) if server_cfg else None
        label = f"{info.server}/{info.tool}"
        if tool_cfg is None:
            refusals.append((label, "not_configured"))
            continue
        if not tool_cfg.description.strip():
            refusals.append((label, "description_required"))
            continue
        if tool_cfg.kind == "read" and (info.read_only_hint is False or info.destructive_hint is True):
            refusals.append((label, "kind_conflict"))
            continue
        name = conn_name(info.server, info.tool, tool_cfg.alias)
        if name in registry:
            raise ValueError(f"mcp_name_collision: {name}")

        parameters = copy.deepcopy(info.input_schema)
        props = parameters.setdefault("properties", {})
        for key in tool_cfg.fixed_args:
            props.pop(key, None)
        parameters["required"] = [r for r in parameters.get("required", [])
                                  if r in props and r not in tool_cfg.fixed_args]
        for key, prop in props.items():
            prop.pop("description", None)
            if key in tool_cfg.param_descriptions:
                prop["description"] = tool_cfg.param_descriptions[key]
        exported = frozenset(props)

        is_write = tool_cfg.kind == "write"
        registry[name] = ToolSpec(
            name=name,
            description=tool_cfg.description,
            parameters=parameters,
            risk=RiskLevel.ACT_CONFIRM if is_write else RiskLevel.READ,
            # The island shows a read's preview while it runs, so an unconfigured read says
            # "Checking Granola"; a write keeps "server: tool", which names exactly what is approved.
            preview=_preview_fn(tool_cfg.preview,
                                f"{info.server}: {info.tool}" if is_write
                                else f"Checking {info.server.replace('_', ' ').title()}",
                                exported),
            executor=_make_executor(info.server, info.tool, tool_cfg, server_cfg, cfg,
                                    manager, exported),
            computer_mutation=False,
            timeout_s=(tool_cfg.timeout_s or cfg.mcp.call_timeout_s) + 2,
            card=tool_cfg.card,
        )
        registered += 1
    if registered > cfg.mcp.max_tools:
        raise ValueError(f"mcp_too_many_tools: {registered} exposed, max {cfg.mcp.max_tools}")
    return refusals
