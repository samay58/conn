"""Localhost console server. Binds 127.0.0.1 only. The browser talks to this
process alone; it never holds credentials and never reaches OpenAI.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import uvicorn
from starlette.applications import Starlette
from starlette.responses import FileResponse, JSONResponse
from starlette.routing import Route, WebSocketRoute
from starlette.websockets import WebSocket, WebSocketDisconnect

from ..app import ConnApp
from ..events import now_ms

CONSOLE_DIR = Path(__file__).resolve().parents[3] / "console"


class Broadcaster:
    """Per-client ordered queues: one writer task per client, so console
    messages can never arrive out of order (a delta racing past the previous
    turn's trace event garbles the transcript)."""

    def __init__(self):
        self._clients: dict[WebSocket, tuple[asyncio.Queue[str], asyncio.Task]] = {}

    @property
    def clients(self):
        return self._clients.keys()

    def attach(self, ws: WebSocket) -> None:
        queue: asyncio.Queue[str] = asyncio.Queue()
        task = asyncio.ensure_future(self._writer(ws, queue))
        self._clients[ws] = (queue, task)

    def detach(self, ws: WebSocket) -> None:
        # Cancel the writer with its client, or loop teardown logs a
        # destroyed-but-pending task per client that ever connected.
        entry = self._clients.pop(ws, None)
        if entry is not None:
            entry[1].cancel()

    def publish(self, msg: dict) -> None:
        data = json.dumps(msg, default=str)
        for queue, _task in self._clients.values():
            queue.put_nowait(data)

    async def _writer(self, ws: WebSocket, queue: asyncio.Queue[str]) -> None:
        try:
            while ws in self._clients:
                await ws.send_text(await queue.get())
        except asyncio.CancelledError:
            raise
        except Exception:
            self.detach(ws)


def build_server(app: ConnApp) -> Starlette:
    bus = Broadcaster()
    app.publisher = bus.publish

    async def index(request):
        return FileResponse(CONSOLE_DIR / "index.html")

    async def static(request):
        name = request.path_params["name"]
        target = (CONSOLE_DIR / name).resolve()
        if target.parent != CONSOLE_DIR.resolve() or not target.exists():
            return JSONResponse({"error": "not found"}, status_code=404)
        return FileResponse(target)

    async def healthz(request):
        return JSONResponse({
            "ok": True, "session_id": app.session_id,
            "phase": app.machine.phase.value,
            "live": app.adapter_is_live(),
            "phase_age_s": round(app.phase_age_s(), 3),
            "upstream_connected": app.adapter.connected,
        })

    async def ws_endpoint(ws: WebSocket):
        await ws.accept()
        bus.attach(ws)
        app.publish_state()
        app.publish({"type": "hello", "live": app.adapter_is_live(),
                     "cap_usd": app.cfg.budget.session_cap_usd,
                     "server_ts_ms": now_ms()})
        is_app_client = False
        try:
            while True:
                raw = await ws.receive_text()
                try:
                    msg = json.loads(raw)
                except ValueError:
                    continue
                if client_role(msg) == "app" and not is_app_client:
                    is_app_client = True
                    app.ax_bridge.app_attached()
                    asyncio.ensure_future(app.publish_ax_grants())
                    continue
                await handle_client(app, msg)
        except WebSocketDisconnect:
            pass
        finally:
            if is_app_client:
                app.ax_bridge.app_detached()
            bus.detach(ws)

    return Starlette(routes=[
        Route("/", index),
        Route("/healthz", healthz),
        Route("/{name}", static),
        WebSocketRoute("/ws", ws_endpoint),
    ])


def client_role(msg: dict) -> str | None:
    """A client_hello names the connection's role; the native app registers
    as "app" so ax_read requests have a known answerer."""
    if msg.get("type") == "client_hello":
        role = msg.get("role")
        return role if isinstance(role, str) else None
    return None


async def handle_client(app: ConnApp, msg: dict) -> None:
    match msg.get("type"):
        case "ax_read_result" | "ax_action_result":
            app.ax_bridge.resolve(str(msg.get("request_id", "")), msg.get("data"))
        case "ptt_down":
            await app.on_ptt_down(client_ts_ms=msg.get("client_ts_ms"),
                                  source=str(msg.get("source", "console")))
        case "ptt_up":
            await app.on_ptt_up(client_ts_ms=msg.get("client_ts_ms"),
                                source=str(msg.get("source", "console")))
        case "text":
            await app.on_text(str(msg.get("text", "")))
        case "approval":
            await app.on_approval(str(msg.get("call_id", "")),
                                  bool(msg.get("approved", False)),
                                  client_ts_ms=msg.get("client_ts_ms"))
        case "stop":
            await app.on_stop(client_ts_ms=msg.get("client_ts_ms"))
        case "override_budget":
            await app.on_budget_override()
        case "new_session":
            await app.new_session()
        case "ui_ack":
            await app.on_ui_ack(str(msg.get("moment", "")), msg.get("client_ts_ms"))


async def serve(app: ConnApp) -> None:
    server = uvicorn.Server(uvicorn.Config(
        build_server(app), host=app.cfg.server.host, port=app.cfg.server.port,
        log_level="warning",
    ))
    await server.serve()
