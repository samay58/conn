"""MCP client manager: connects to configured servers, lists their exposed
tools, calls them, and shuts them down. It exposes nothing to the model;
plan 015 turns the listing into model-visible tools under Conn's gates.

Each server connection lives inside one owner task because anyio requires an
`async with Client(...)` block to be entered and exited in the same task.
No client-side request handlers are ever passed to the SDK, so a server that
asks Conn's model for text or asks Samay for input gets the SDK's default refusal.
"""

from __future__ import annotations

import asyncio
import contextlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from mcp import Client
from mcp.client.stdio import StdioServerParameters
from mcp.shared.exceptions import MCPError

from .config import McpCfg, McpServerCfg
from .tools.base import ToolError

_JSON_TYPES = {"string", "number", "integer", "boolean", "array", "object", "null"}
_ENUM_VALUE_MAX = 64
_DESCRIPTION_MAX = 200


class McpNotConnected(ToolError):
    """The server is not connected, so nothing was sent."""


class McpCallFailed(ToolError):
    """The request was sent and then failed or timed out; the server may have acted."""


@dataclass(frozen=True)
class McpToolInfo:
    server: str
    tool: str                       # the server's own tool name
    input_schema: dict              # sanitized, object root
    read_only_hint: bool | None
    destructive_hint: bool | None
    server_description: str         # capped at 200 chars; never shown to the model


@dataclass(frozen=True)
class McpCallResult:
    text: str                       # text blocks joined with "\n"; non-text blocks become "[<type> content]"
    structured: dict | None
    is_error: bool


@dataclass
class _Conn:
    cfg: McpServerCfg
    ready: asyncio.Event = field(default_factory=asyncio.Event)
    stop: asyncio.Event = field(default_factory=asyncio.Event)
    task: asyncio.Task | None = None
    client: Any = None
    tools: list = field(default_factory=list)
    error: BaseException | None = None


def _json_type(value: Any) -> Any:
    if isinstance(value, str) and value in _JSON_TYPES:
        return value
    if isinstance(value, list) and value and all(isinstance(v, str) and v in _JSON_TYPES for v in value):
        return list(value)
    return "string"


def _enum_ok(values: Any) -> bool:
    if not isinstance(values, list) or not values:
        return False
    for v in values:
        if isinstance(v, bool):
            return False
        if isinstance(v, str):
            if len(v) > _ENUM_VALUE_MAX:
                return False
        elif not isinstance(v, (int, float)):
            return False
    return True


def _reduce(prop: Any, *, allow_items: bool) -> dict:
    prop = prop if isinstance(prop, dict) else {}
    out: dict[str, Any] = {"type": _json_type(prop.get("type"))}
    if _enum_ok(prop.get("enum")):
        out["enum"] = list(prop["enum"])
    if allow_items and out["type"] == "array":
        out["items"] = _reduce(prop.get("items"), allow_items=False)
    return out


def sanitize_schema(schema: Any) -> dict:
    """Rebuild a tool schema from structure only. Descriptions, titles,
    defaults, examples and every reference or combinator are server-written
    text or indirection and never reach the model."""
    schema = schema if isinstance(schema, dict) else {}
    raw_props = schema.get("properties")
    raw_props = raw_props if isinstance(raw_props, dict) else {}
    properties = {
        name: _reduce(prop, allow_items=True)
        for name, prop in raw_props.items()
        if isinstance(name, str)
    }
    raw_required = schema.get("required")
    required = [r for r in raw_required if r in properties] if isinstance(raw_required, list) else []
    return {"type": "object", "properties": properties, "required": required}


def _stdio_params(server_cfg: McpServerCfg) -> StdioServerParameters:
    # env holds only the config entries; the SDK merges them over a safe
    # default (PATH-like variables), so Conn's own secrets never pass through.
    argv = server_cfg.command
    return StdioServerParameters(
        command=argv[0], args=list(argv[1:]),
        env=dict(server_cfg.env) or None, cwd=server_cfg.cwd or None)


def _default_factory(server_cfg: McpServerCfg, auth: Any = None):
    if server_cfg.command:
        return Client(_stdio_params(server_cfg))
    if auth is None:
        return Client(server_cfg.url)
    return _auth_http_client(server_cfg.url, auth)


@contextlib.asynccontextmanager
async def _auth_http_client(url: str, auth: Any):
    from mcp.client.streamable_http import streamable_http_client
    from mcp.shared._httpx_utils import create_mcp_http_client

    # The SDK does not close an http client it was handed, so close it here.
    async with create_mcp_http_client(auth=auth) as http, \
            Client(streamable_http_client(url, http_client=http)) as client:
        yield client


class McpManager:
    def __init__(self, cfg: McpCfg, *, data_dir: Path | None = None,
                 client_factory=None, auth_for=None):
        self.cfg = cfg
        self.data_dir = data_dir
        self._factory = client_factory
        self._auth_for = auth_for
        self._conns: dict[str, _Conn] = {}
        self._events: list[tuple[str, dict]] = []
        self._loop: asyncio.AbstractEventLoop | None = None
        self.status: dict[str, str] = {}

    # -- trace buffering (Conn's trace does not exist yet when this starts) --
    def _emit(self, event: str, **fields: Any) -> None:
        self._events.append((event, fields))

    def drain_events(self) -> list[tuple[str, dict]]:
        events, self._events = self._events, []
        return events

    def _make_client(self, server_cfg: McpServerCfg):
        if self._factory is not None:
            return self._factory(server_cfg)
        auth = self._auth_for(server_cfg) if self._auth_for else None
        return _default_factory(server_cfg, auth)

    async def _owner(self, conn: _Conn) -> None:
        name = conn.cfg.name
        try:
            async with self._make_client(conn.cfg) as client:
                tools: list = []
                cursor = None
                while True:
                    page = await client.list_tools(cursor=cursor)
                    tools.extend(page.tools)
                    cursor = page.next_cursor
                    if cursor is None:
                        break
                conn.client, conn.tools = client, tools
                conn.ready.set()
                await conn.stop.wait()
        except asyncio.CancelledError:
            raise
        except Exception as error:  # noqa: BLE001 - reported through status
            if not conn.ready.is_set():
                conn.error = error
                conn.ready.set()
            else:
                self._mark_down(name, error)
        finally:
            conn.client = None

    def _mark_down(self, name: str, error: BaseException) -> None:
        if self.status.get(name, "").startswith("connected"):
            kind = type(error).__name__
            self.status[name] = f"down: {kind}"
            self._emit("mcp_server_down", server=name, reason=kind)

    async def _await_ready(self, conn: _Conn) -> None:
        name = conn.cfg.name
        timeout = conn.cfg.connect_timeout_s or self.cfg.connect_timeout_s
        try:
            await asyncio.wait_for(conn.ready.wait(), timeout)
        except TimeoutError:
            await self._cancel(conn)
            self._skip(name, "timeout")
            return
        if conn.error is not None:
            await self._cancel(conn)
            self._skip(name, type(conn.error).__name__)
            return
        self.status[name] = "connected"

    def _skip(self, name: str, reason: str) -> None:
        self.status[name] = f"skipped: {reason}"
        self._emit("mcp_server_skipped", server=name, reason=reason)

    @staticmethod
    async def _cancel(conn: _Conn) -> None:
        if conn.task is not None and not conn.task.done():
            conn.task.cancel()
        if conn.task is not None:
            await asyncio.gather(conn.task, return_exceptions=True)

    async def start(self) -> list[McpToolInfo]:
        self._loop = asyncio.get_running_loop()
        for server_cfg in self.cfg.servers:
            conn = _Conn(cfg=server_cfg)
            self._conns[server_cfg.name] = conn
            conn.task = asyncio.create_task(self._owner(conn), name=f"mcp-{server_cfg.name}")
        await asyncio.gather(*(self._await_ready(c) for c in self._conns.values()))

        infos: list[McpToolInfo] = []
        for name, conn in self._conns.items():
            if self.status.get(name) != "connected":
                continue
            offered = {t.name: t for t in conn.tools}
            missing = [t for t in conn.cfg.tools if t not in offered]
            if missing:
                self.status[name] = f"connected; missing_tools: {', '.join(missing)}"
            exposed = 0
            for tool_name in conn.cfg.tools:
                tool = offered.get(tool_name)
                if tool is None:
                    continue
                ann = tool.annotations
                infos.append(McpToolInfo(
                    server=name, tool=tool_name,
                    input_schema=sanitize_schema(tool.input_schema),
                    read_only_hint=getattr(ann, "read_only_hint", None),
                    destructive_hint=getattr(ann, "destructive_hint", None),
                    server_description=(tool.description or "")[:_DESCRIPTION_MAX],
                ))
                exposed += 1
            self._emit("mcp_server_connected", server=name, tools=exposed)

        if len(infos) > self.cfg.max_tools:
            count = len(infos)
            await self.stop()
            raise ValueError(f"mcp_too_many_tools: {count} exposed, max {self.cfg.max_tools}")
        return infos

    def _connected(self, server: str) -> _Conn:
        conn = self._conns.get(server)
        if (conn is None or conn.client is None
                or not self.status.get(server, "").startswith("connected")):
            raise McpNotConnected(f"mcp_server_unavailable: {server}")
        return conn

    async def call(self, server: str, tool: str, args: dict, timeout_s: float) -> McpCallResult:
        conn = self._connected(server)
        try:
            result = await asyncio.wait_for(
                conn.client.call_tool(tool, args, read_timeout_seconds=timeout_s), timeout_s)
        except (TimeoutError, MCPError) as error:
            raise McpCallFailed(f"mcp_call_failed: {server}: {type(error).__name__}") from error
        except asyncio.CancelledError:
            raise
        except Exception as error:  # noqa: BLE001 - transport failure after sending
            self._mark_down(server, error)
            raise McpCallFailed(f"mcp_call_failed: {server}: {type(error).__name__}") from error
        parts = [
            block.text if getattr(block, "type", None) == "text" else f"[{getattr(block, 'type', 'unknown')} content]"
            for block in result.content
        ]
        return McpCallResult(text="\n".join(parts), structured=result.structured_content,
                             is_error=bool(result.is_error))

    def call_blocking(self, server: str, tool: str, args: dict, timeout_s: float) -> McpCallResult:
        """For the harness's worker threads. Raises RuntimeError on the loop's own thread."""
        loop = self._loop
        if loop is None:
            raise McpNotConnected(f"mcp_server_unavailable: {server}")
        try:
            running = asyncio.get_running_loop()
        except RuntimeError:
            running = None
        if running is loop:
            raise RuntimeError("call_blocking would deadlock on the event loop thread")
        future = asyncio.run_coroutine_threadsafe(self.call(server, tool, args, timeout_s), loop)
        return future.result(timeout=timeout_s + 1)

    async def stop(self) -> None:
        for conn in self._conns.values():
            conn.stop.set()
        tasks = [c.task for c in self._conns.values() if c.task is not None]
        if tasks:
            _, pending = await asyncio.wait(tasks, timeout=5)
            for task in pending:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
        for name in self._conns:
            self.status[name] = "stopped"
            self._conns[name].client = None
