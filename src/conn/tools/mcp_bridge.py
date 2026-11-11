"""Turns configured MCP tools into ordinary Conn tools. Every word the model
or a chip sees comes from Conn's config; a server's own descriptions and
error text are untrusted and never pass through. Writes are local actions:
they wait for a pointer click and count as done only when the server read
its own write back and said so.
"""

from __future__ import annotations

import copy
import json

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


def _preview_fn(template: str, default: str, exported: frozenset[str]):
    def preview(args: dict) -> str:
        if not template:
            return default
        values = _Preview({
            k: str(v)[:PREVIEW_VALUE_MAX] for k, v in args.items() if k in exported})
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

        limit = tool_cfg.max_result_chars
        structured = result.structured
        if structured is not None and len(json.dumps(structured, default=str)) > limit:
            structured = None
        return {"text": result.text[:limit], "structured": structured}

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
            preview=_preview_fn(tool_cfg.preview, f"{info.server}: {info.tool}", exported),
            executor=_make_executor(info.server, info.tool, tool_cfg, server_cfg, cfg,
                                    manager, exported),
            computer_mutation=False,
            timeout_s=(tool_cfg.timeout_s or cfg.mcp.call_timeout_s) + 2,
        )
        registered += 1
    if registered > cfg.mcp.max_tools:
        raise ValueError(f"mcp_too_many_tools: {registered} exposed, max {cfg.mcp.max_tools}")
    return refusals
