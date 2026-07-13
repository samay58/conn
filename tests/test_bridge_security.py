import asyncio
import hashlib
import hmac

import pytest
from starlette.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from conn.ax_bridge import AxBridge
from conn.server.http import build_server, handle_client, origin_allowed


class _Phase:
    value = "idle"


class _Machine:
    phase = _Phase()


class _Adapter:
    connected = True


class _Budget:
    session_cap_usd = 1.0


class _Config:
    budget = _Budget()


class _ServerApp:
    def __init__(self, token: str = "correct") -> None:
        self.ax_bridge = AxBridge(expected_token=token)
        self.session_id = "test-session"
        self.machine = _Machine()
        self.adapter = _Adapter()
        self.cfg = _Config()
        self.publisher = lambda _message: None
        self.state_publications = 0
        self.approvals: list[tuple[str, bool]] = []

    def adapter_is_live(self) -> bool:
        return True

    def phase_age_s(self) -> float:
        return 0.0

    def publish_state(self) -> None:
        self.state_publications += 1
        self.publisher({"type": "state"})

    def publish(self, message: dict) -> None:
        self.publisher(message)

    async def publish_ax_grants(self) -> None:
        return

    async def on_approval(self, call_id: str, approved: bool, **_kwargs) -> None:
        self.approvals.append((call_id, approved))
        self.publish({"type": "approval_observed"})


def _proof(token: str, purpose: str, challenge: str) -> str:
    payload = f"{purpose}:{challenge}".encode()
    return hmac.new(token.encode(), payload, hashlib.sha256).hexdigest()


def test_app_health_proves_daemon_identity_without_receiving_raw_token() -> None:
    client = TestClient(build_server(_ServerApp()))
    challenge = "fresh-health-challenge"

    raw_bearer = client.get(
        "/app-healthz", headers={"X-Conn-Bridge-Token": "correct"}
    )
    assert raw_bearer.status_code == 401

    response = client.get(
        "/app-healthz", headers={"X-Conn-Challenge": challenge}
    )
    assert response.status_code == 200
    assert response.json()["bridge_proof"] == _proof(
        "correct", "conn-app-health-v1", challenge
    )
    assert "correct" not in response.text


def test_app_websocket_authenticates_before_private_bus_attachment() -> None:
    app = _ServerApp()
    client = TestClient(build_server(app))

    with client.websocket_connect("/ws") as websocket:
        challenge_message = websocket.receive_json()
        assert challenge_message["type"] == "auth_challenge"
        assert app.state_publications == 0

        challenge = challenge_message["challenge"]
        websocket.send_json({
            "type": "client_hello",
            "role": "app",
            "proof": _proof(
                "correct", "conn-app-websocket-v1", challenge
            ),
        })
        first_private_message = websocket.receive_json()
        assert first_private_message["type"] == "hello"
        assert first_private_message["server_proof"] == _proof(
            "correct", "conn-daemon-websocket-v1", challenge,
        )
        assert "correct" not in str(first_private_message)
        assert websocket.receive_json()["type"] == "state"
        assert app.state_publications == 1
        assert app.ax_bridge.app_present


def test_raw_bridge_token_cannot_authenticate_app_websocket() -> None:
    app = _ServerApp()
    client = TestClient(build_server(app))

    with client.websocket_connect("/ws") as websocket:
        challenge_message = websocket.receive_json()
        assert challenge_message["type"] == "auth_challenge"
        websocket.send_json({
            "type": "client_hello",
            "role": "app",
            "bridge_token": "correct",
        })
        try:
            websocket.receive_json()
        except WebSocketDisconnect as error:
            assert error.code == 1008
        else:
            raise AssertionError("raw bridge token was accepted")

    assert app.state_publications == 0
    assert not app.ax_bridge.app_present


def test_explicit_debug_capability_authenticates_read_only_console() -> None:
    app = _ServerApp()
    client = TestClient(build_server(
        app, console_capability="debug-console-capability"
    ))

    with client.websocket_connect(
        "/ws", headers={"origin": "http://127.0.0.1:8787"}
    ) as websocket:
        challenge_message = websocket.receive_json()
        challenge = challenge_message["challenge"]
        websocket.send_json({
            "type": "client_hello",
            "role": "console",
            "proof": _proof(
                "debug-console-capability",
                "conn-console-websocket-v1",
                challenge,
            ),
        })
        first_private_message = websocket.receive_json()
        assert first_private_message["type"] == "hello"
        assert "approval_nonce" not in first_private_message
        assert app.state_publications == 1


def test_console_websocket_ignores_approval_messages() -> None:
    app = _ServerApp()
    client = TestClient(build_server(
        app, console_capability="debug-console-capability"
    ))

    with client.websocket_connect(
        "/ws", headers={"origin": "http://127.0.0.1:8787"}
    ) as websocket:
        challenge = websocket.receive_json()["challenge"]
        websocket.send_json({
            "type": "client_hello",
            "role": "console",
            "proof": _proof(
                "debug-console-capability",
                "conn-console-websocket-v1",
                challenge,
            ),
        })
        hello = websocket.receive_json()
        assert hello["type"] == "hello"
        websocket.receive_json()

        websocket.send_json({
            "type": "approval", "call_id": "ignored", "approved": True,
        })
        app.publish({"type": "read_only_marker"})
        assert websocket.receive_json()["type"] == "read_only_marker"

    assert app.approvals == []


def test_authenticated_console_never_receives_native_rpc_payloads() -> None:
    app = _ServerApp()
    client = TestClient(build_server(
        app, console_capability="debug-console-capability"
    ))

    with client.websocket_connect("/ws") as app_socket:
        app_challenge = app_socket.receive_json()["challenge"]
        app_socket.send_json({
            "type": "client_hello",
            "role": "app",
            "proof": _proof(
                "correct", "conn-app-websocket-v1", app_challenge,
            ),
        })
        assert app_socket.receive_json()["type"] == "hello"
        assert app_socket.receive_json()["type"] == "state"

        with client.websocket_connect(
            "/ws", headers={"origin": "http://127.0.0.1:8787"}
        ) as console_socket:
            console_challenge = console_socket.receive_json()["challenge"]
            console_socket.send_json({
                "type": "client_hello",
                "role": "console",
                "proof": _proof(
                    "debug-console-capability",
                    "conn-console-websocket-v1",
                    console_challenge,
                ),
            })
            assert console_socket.receive_json()["type"] == "hello"
            assert console_socket.receive_json()["type"] == "state"
            assert app_socket.receive_json()["type"] == "state"

            app.publish({
                "type": "ax_action",
                "request_id": "private-request",
                "turn_id": "turn-1",
                "observation_epoch": 4,
                "sequence": 9,
            })
            assert app_socket.receive_json()["request_id"] == "private-request"

            console_socket.send_json({
                "type": "approval",
                "call_id": "c1",
                "approved": False,
            })
            app.publish({"type": "read_only_marker"})
            assert console_socket.receive_json()["type"] == "read_only_marker"
            assert app.approvals == []


@pytest.mark.parametrize("origin", [None, "https://attacker.example", "null"])
def test_console_rejects_missing_or_nonlocal_origin(origin: str | None) -> None:
    app = _ServerApp()
    client = TestClient(build_server(
        app, console_capability="debug-console-capability"
    ))
    headers = {} if origin is None else {"origin": origin}

    with client.websocket_connect("/ws", headers=headers) as websocket:
        challenge_message = websocket.receive_json()
        challenge = challenge_message["challenge"]
        websocket.send_json({
            "type": "client_hello",
            "role": "console",
            "proof": _proof(
                "debug-console-capability",
                "conn-console-websocket-v1",
                challenge,
            ),
        })
        with pytest.raises(WebSocketDisconnect) as error:
            websocket.receive_json()
        assert error.value.code == 1008

    assert app.state_publications == 0


@pytest.mark.parametrize("capability", ["", "   ", "short"])
def test_console_rejects_empty_or_weak_capability(capability: str) -> None:
    app = _ServerApp()
    client = TestClient(build_server(app, console_capability=capability))

    with client.websocket_connect(
        "/ws", headers={"origin": "http://127.0.0.1:8787"}
    ) as websocket:
        challenge_message = websocket.receive_json()
        challenge = challenge_message["challenge"]
        websocket.send_json({
            "type": "client_hello",
            "role": "console",
            "proof": _proof(
                capability,
                "conn-console-websocket-v1",
                challenge,
            ),
        })
        with pytest.raises(WebSocketDisconnect) as error:
            websocket.receive_json()
        assert error.value.code == 1008

    assert app.state_publications == 0


def test_authenticated_console_cannot_initiate_or_approve_actions() -> None:
    class Stub:
        def __init__(self) -> None:
            self.calls: list[str] = []

        async def on_ptt_down(self, **_kwargs) -> None:
            self.calls.append("ptt_down")

        async def on_ptt_up(self, **_kwargs) -> None:
            self.calls.append("ptt_up")

        async def on_text(self, _text: str) -> None:
            self.calls.append("text")

        async def on_approval(self, *_args, **_kwargs) -> None:
            self.calls.append("approval")

        async def on_stop(self, **_kwargs) -> None:
            self.calls.append("stop")

        async def on_budget_override(self) -> None:
            self.calls.append("override_budget")

        async def new_session(self) -> None:
            self.calls.append("new_session")

        async def on_ui_ack(self, *_args) -> None:
            self.calls.append("ui_ack")

    async def scenario() -> list[str]:
        stub = Stub()
        messages = [
            {"type": "ptt_down"},
            {"type": "ptt_up"},
            {"type": "text", "text": "run a tool"},
            {"type": "approval", "call_id": "c1", "approved": True},
            {"type": "stop"},
            {"type": "override_budget"},
            {"type": "new_session"},
            {"type": "ui_ack", "moment": "thinking"},
        ]
        for message in messages:
            await handle_client(
                stub,
                message,
                authenticated_role="console",
            )
        await handle_client(
            stub,
            {
                "type": "approval",
                "call_id": "c1",
                "approved": True,
                "approval_nonce": "session-nonce",
            },
            authenticated_role="console",
        )
        return stub.calls

    assert asyncio.run(scenario()) == []


def test_public_console_page_contains_no_approval_credential() -> None:
    client = TestClient(build_server(_ServerApp(), console_capability=""))

    response = client.get("/")
    assert response.status_code == 200
    assert "CONN_APPROVAL_NONCE" not in response.text
    assert "approval_nonce" not in response.text


def test_console_assets_are_capability_authenticated_and_read_only() -> None:
    client = TestClient(build_server(_ServerApp(), console_capability=""))

    page = client.get("/").text
    script = client.get("/app.js").text
    assert "auth_challenge" in script
    assert "conn-console-websocket-v1" in script
    assert "crypto.subtle" in script
    assert 'type: "approval"' not in script
    assert "approval_nonce" not in script
    assert "Approve in Conn" in script
    for control in (
        'type: "ptt_down"',
        'type: "ptt_up"',
        'type: "text"',
        'type: "stop"',
        'type: "override_budget"',
        'type: "new_session"',
        'type: "ui_ack"',
    ):
        assert control not in script
    for control_id in (
        'id="stop"', 'id="new-session"', 'id="text-form"', 'id="text-input"'
    ):
        assert control_id not in page


def test_app_auth_rejects_missing_wrong_and_second_client() -> None:
    bridge = AxBridge(expected_token="correct")
    challenge = "fresh-websocket-challenge"
    correct = _proof("correct", "conn-app-websocket-v1", challenge)
    wrong = _proof("wrong", "conn-app-websocket-v1", challenge)

    assert bridge.authenticate_app_proof(challenge, None, "client-1") is False
    assert bridge.authenticate_app_proof(challenge, wrong, "client-1") is False
    assert bridge.authenticate_app_proof(challenge, correct, "client-1") is True
    assert bridge.authenticate_app_proof(challenge, correct, "client-2") is False


def test_only_authenticated_app_can_resolve_native_rpc() -> None:
    bridge = AxBridge(expected_token="correct")
    challenge = "fresh-websocket-challenge"
    bridge.authenticate_app_proof(
        challenge,
        _proof("correct", "conn-app-websocket-v1", challenge),
        "app-client",
    )
    bridge.resolve("request", {"ok": True}, client_id="console", sequence=1)
    assert bridge.rejected_replies == 1


def test_native_rpc_reply_requires_authenticated_client_identity() -> None:
    bridge = AxBridge(expected_token="correct")
    challenge = "fresh-websocket-challenge"
    bridge.authenticate_app_proof(
        challenge,
        _proof("correct", "conn-app-websocket-v1", challenge),
        "app-client",
    )

    bridge.resolve("request", {"ok": True}, sequence=1)
    assert bridge.rejected_replies == 1


def test_cross_origin_console_is_rejected() -> None:
    assert not origin_allowed(None)
    assert origin_allowed("http://127.0.0.1:8787")
    assert origin_allowed("http://localhost:8787")
    assert not origin_allowed("https://attacker.example")
    assert not origin_allowed("null")


def test_console_cannot_approve_with_any_message_shape() -> None:
    class Stub:
        def __init__(self):
            self.approvals = []

        async def on_approval(self, *args, **kwargs):
            self.approvals.append((args, kwargs))

    stub = Stub()
    for message in (
        {"type": "approval", "call_id": "c1", "approved": True},
        {
            "type": "approval",
            "call_id": "c1",
            "approved": True,
            "approval_nonce": "legacy-session-nonce",
        },
    ):
        asyncio.run(handle_client(
            stub,
            message,
            authenticated_role="console",
        ))

    assert stub.approvals == []


def test_console_unverified_outcomes_have_explicit_non_green_styles() -> None:
    client = TestClient(build_server(_ServerApp(), console_capability=""))
    stylesheet = client.get("/style.css").text

    for outcome in ("no_effect", "ambiguous", "failed", "blocked"):
        selector = f'.ptt[data-phase="done"][data-outcome="{outcome}"]'
        assert selector in stylesheet
    assert "background: var(--red-soft);" in stylesheet


def test_app_hello_build_identity_is_traced() -> None:
    app = _ServerApp()
    logged: list[tuple[str, dict]] = []

    class _Trace:
        def log(self, kind, **payload):
            logged.append((kind, payload))

    app.trace = _Trace()
    client = TestClient(build_server(app))
    with client.websocket_connect("/ws") as websocket:
        challenge = websocket.receive_json()["challenge"]
        websocket.send_json({
            "type": "client_hello",
            "role": "app",
            "app_build": "2026-07-13T01:00:00Z",
            "proof": _proof("correct", "conn-app-websocket-v1", challenge),
        })
        assert websocket.receive_json()["type"] == "hello"

    kinds = dict(logged)
    assert "app_client" in kinds
    assert kinds["app_client"]["build"] == "2026-07-13T01:00:00Z"
