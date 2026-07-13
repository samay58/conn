"""Localhost console server. Binds 127.0.0.1 only. The browser talks to this
process alone; it never holds credentials and never reaches OpenAI.
"""

from __future__ import annotations

import asyncio
import json
import os
import secrets
from pathlib import Path
from urllib.parse import urlparse

import uvicorn
from starlette.applications import Starlette
from starlette.responses import FileResponse, JSONResponse
from starlette.routing import Route, WebSocketRoute
from starlette.websockets import WebSocket, WebSocketDisconnect

from ..app import ConnApp
from ..ax_bridge import (
    APP_HEALTH_PURPOSE,
    CONSOLE_WEBSOCKET_PURPOSE,
    DAEMON_WEBSOCKET_PURPOSE,
    hmac_proof,
    valid_challenge,
    verify_hmac_proof,
)
from ..events import now_ms

CONSOLE_DIR = Path(__file__).resolve().parents[3] / "console"
CLIENT_QUEUE_LIMIT = 256


class Broadcaster:
    """Per-client ordered queues: one writer task per client, so console
    state can never arrive out of order (a delta racing past the previous
    turn's trace event garbles the transcript)."""

    def __init__(self):
        self._clients: dict[
            WebSocket, tuple[asyncio.Queue[str], asyncio.Task, str]
        ] = {}

    @property
    def clients(self):
        return self._clients.keys()

    def attach(self, ws: WebSocket, role: str) -> None:
        queue: asyncio.Queue[str] = asyncio.Queue(maxsize=CLIENT_QUEUE_LIMIT)
        task = asyncio.ensure_future(self._writer(ws, queue))
        self._clients[ws] = (queue, task, role)

    def detach(self, ws: WebSocket) -> None:
        # Cancel the writer with its client, or loop teardown logs a
        # destroyed-but-pending task per client that ever connected.
        entry = self._clients.pop(ws, None)
        if entry is not None:
            entry[1].cancel()

    def publish(self, msg: dict) -> None:
        data = json.dumps(msg, default=str)
        native_rpc = msg.get("type") in {"ax_read", "ax_action"}
        for ws, (queue, _task, role) in list(self._clients.items()):
            if native_rpc and role != "app":
                continue
            try:
                queue.put_nowait(data)
            except asyncio.QueueFull:
                self.detach(ws)
                asyncio.ensure_future(ws.close(code=1013))

    async def _writer(self, ws: WebSocket, queue: asyncio.Queue[str]) -> None:
        try:
            while ws in self._clients:
                await ws.send_text(await queue.get())
        except asyncio.CancelledError:
            raise
        except Exception:
            self.detach(ws)


def build_server(app: ConnApp, *, console_capability: str | None = None) -> Starlette:
    bus = Broadcaster()
    app.publisher = bus.publish
    if console_capability is None:
        console_capability = os.environ.get("CONN_CONSOLE_CAPABILITY")
    if not valid_console_capability(console_capability):
        console_capability = None

    async def index(request):
        return FileResponse(CONSOLE_DIR / "index.html")

    async def static(request):
        name = request.path_params["name"]
        target = (CONSOLE_DIR / name).resolve()
        if target.parent != CONSOLE_DIR.resolve() or not target.exists():
            return JSONResponse({"error": "not found"}, status_code=404)
        return FileResponse(target)

    def health_payload() -> dict:
        return {
            "ok": True, "session_id": app.session_id,
            "phase": app.machine.phase.value,
            "live": app.adapter_is_live(),
            "phase_age_s": round(app.phase_age_s(), 3),
            "upstream_connected": app.adapter.connected,
        }

    async def healthz(request):
        return JSONResponse(health_payload())

    async def app_healthz(request):
        expected = app.ax_bridge.expected_token
        challenge = request.headers.get("x-conn-challenge")
        if not expected or not valid_challenge(challenge):
            return JSONResponse({"ok": False}, status_code=401)
        return JSONResponse({
            **health_payload(),
            "bridge_proof": hmac_proof(
                expected, APP_HEALTH_PURPOSE, challenge
            ),
        })

    async def ws_endpoint(ws: WebSocket):
        await ws.accept()
        challenge = secrets.token_urlsafe(32)
        await ws.send_json({
            "type": "auth_challenge",
            "challenge": challenge,
            "method": "hmac-sha256",
        })
        client_id = secrets.token_urlsafe(18)
        role: str | None = None
        try:
            raw = await asyncio.wait_for(ws.receive_text(), timeout=2.0)
            try:
                hello = json.loads(raw)
            except ValueError:
                await ws.close(code=1008)
                return
            role = client_role(hello)
            proof = hello.get("proof") if isinstance(hello.get("proof"), str) else None
            app_ok = role == "app" and app.ax_bridge.authenticate_app_proof(
                challenge, proof, client_id
            )
            console_ok = (
                role == "console"
                and origin_allowed(ws.headers.get("origin"))
                and console_capability is not None
                and verify_hmac_proof(
                    console_capability,
                    CONSOLE_WEBSOCKET_PURPOSE,
                    challenge,
                    proof,
                )
            )
            if not app_ok and not console_ok:
                await ws.close(code=1008)
                return

            hello = {
                "type": "hello", "live": app.adapter_is_live(),
                "cap_usd": app.cfg.budget.session_cap_usd,
                "server_ts_ms": now_ms(),
            }
            if role == "app":
                hello["server_proof"] = hmac_proof(
                    app.ax_bridge.expected_token,
                    DAEMON_WEBSOCKET_PURPOSE,
                    challenge,
                )
            await ws.send_json(hello)
            bus.attach(ws, role)
            app.publish_state()
            if role == "app":
                build = client_build(json.loads(raw))
                if build is not None:
                    app._app_build = build
                    if hasattr(app, "trace"):
                        app.trace.log("app_client", build=build)
                asyncio.ensure_future(app.publish_ax_grants())
            while True:
                raw = await ws.receive_text()
                try:
                    msg = json.loads(raw)
                except ValueError:
                    continue
                await handle_client(
                    app,
                    msg,
                    authenticated_role=role,
                    client_id=client_id,
                )
        except (asyncio.TimeoutError, WebSocketDisconnect):
            pass
        finally:
            if role == "app" and app.ax_bridge.app_present:
                app.ax_bridge.app_detached(client_id)
            bus.detach(ws)

    return Starlette(routes=[
        Route("/", index),
        Route("/healthz", healthz),
        Route("/app-healthz", app_healthz),
        Route("/{name}", static),
        WebSocketRoute("/ws", ws_endpoint),
    ])


def client_build(msg: dict) -> str | None:
    build = msg.get("app_build")
    if isinstance(build, str) and 0 < len(build) <= 64 and build.isprintable():
        return build
    return None


def _safe_gesture_id(msg: dict) -> str | None:
    gesture = msg.get("gesture_id")
    if (isinstance(gesture, str) and 0 < len(gesture) <= 64
            and all(c.isascii() and (c.isalnum() or c in "-_") for c in gesture)):
        return gesture
    return None


def client_role(msg: dict) -> str | None:
    """A client_hello names the connection's role; the native app registers
    as "app" so ax_read requests have a known answerer."""
    if msg.get("type") == "client_hello":
        role = msg.get("role")
        return role if isinstance(role, str) else None
    return None


def origin_allowed(origin: str | None) -> bool:
    if origin is None:
        return False
    try:
        parsed = urlparse(origin)
    except ValueError:
        return False
    return (
        parsed.scheme == "http"
        and parsed.hostname in {"127.0.0.1", "localhost", "::1"}
        and parsed.username is None
        and parsed.password is None
        and parsed.path in {"", "/"}
        and not parsed.query
        and not parsed.fragment
    )


def valid_console_capability(capability: object) -> bool:
    return (
        isinstance(capability, str)
        and 16 <= len(capability) <= 256
        and all(
            character.isascii()
            and (character.isalnum() or character in "-_")
            for character in capability
        )
    )


async def handle_client(app: ConnApp, msg: dict, *, authenticated_role: str | None = None,
                        client_id: str | None = None) -> None:
    if authenticated_role == "console":
        return
    if authenticated_role != "app":
        return
    match msg.get("type"):
        case "ax_read_result" | "ax_action_result":
            app.ax_bridge.resolve(
                str(msg.get("request_id", "")),
                msg.get("data"),
                client_id=client_id,
                turn_id=msg.get("turn_id") if isinstance(msg.get("turn_id"), str) else None,
                observation_epoch=(
                    msg.get("observation_epoch")
                    if isinstance(msg.get("observation_epoch"), int)
                    else None
                ),
                sequence=msg.get("sequence") if isinstance(msg.get("sequence"), int) else None,
            )
        case "ptt_down":
            await app.on_ptt_down(client_ts_ms=msg.get("client_ts_ms"),
                                  source=str(msg.get("source", "app_hotkey")),
                                  gesture_id=_safe_gesture_id(msg))
        case "ptt_up":
            await app.on_ptt_up(client_ts_ms=msg.get("client_ts_ms"),
                                source=str(msg.get("source", "app_hotkey")),
                                gesture_id=_safe_gesture_id(msg))
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
        case "report_last_command":
            await app.on_report_last_command()
        case "shutdown":
            await app.on_shutdown_request("app_quit")


async def serve(app: ConnApp, shutdown_event: asyncio.Event | None = None) -> None:
    server = uvicorn.Server(uvicorn.Config(
        build_server(app, console_capability=app.console_capability),
        host=app.cfg.server.host, port=app.cfg.server.port,
        log_level="warning",
    ))
    stopper = None
    if shutdown_event is not None:
        async def stop_when_signalled() -> None:
            await shutdown_event.wait()
            server.should_exit = True
        stopper = asyncio.ensure_future(stop_when_signalled())
    try:
        await server.serve()
    finally:
        if stopper is not None:
            stopper.cancel()
