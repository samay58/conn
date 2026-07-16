"""Context reads via the app's Accessibility grant (bug 2 / S2).

TCC grants bind to the binary: Conn.app holds Accessibility, the daemon's
python does not. The daemon publishes an ax_read request over the existing
websocket; the app answers with ax_read_result; executors reach the round
trip through a thread-safe bridge. No app attached means an immediate None
so the python fallback never pays a timeout.
"""

import asyncio
import os
import threading
from unittest.mock import patch

from conn.ax_bridge import APP_WEBSOCKET_PURPOSE, AxBridge, hmac_proof
from conn.observations import ObservationQuery
from conn.tools import mac


def run_loop_test(coro):
    return asyncio.run(coro)


def attach_app(bridge: AxBridge, client_id: str = "test-app") -> str:
    challenge = "test-websocket-challenge"
    assert bridge.expected_token is not None
    proof = hmac_proof(bridge.expected_token, APP_WEBSOCKET_PURPOSE, challenge)
    assert bridge.authenticate_app_proof(challenge, proof, client_id)
    return client_id


class TestAxBridge:
    def test_visual_observation_uses_authenticated_native_rpc(self):
        async def scenario():
            published = []
            bridge = AxBridge(timeout_s=1.0, expected_token="test-token")
            bridge.bind(asyncio.get_running_loop(), published.append)
            client_id = attach_app(bridge)
            task = asyncio.create_task(bridge.observe_visual(
                turn_id="turn_visual",
                observation_epoch=7,
                enabled=True,
                denied_bundles=["com.apple.keychainaccess"],
            ))
            while not published:
                await asyncio.sleep(0)
            request = published[0]
            bridge.resolve(
                request["request_id"], {"ok": True},
                client_id=client_id,
                sequence=request["sequence"],
                turn_id=request["turn_id"],
                observation_epoch=request["observation_epoch"],
            )
            return request, await task

        request, result = run_loop_test(scenario())
        assert request["type"] == "ax_action"
        assert request["op"] == "observe_visual"
        assert request["params"] == {
            "enabled": True,
            "denied_bundles": ["com.apple.keychainaccess"],
            "turn_id": "turn_visual",
            "observation_epoch": 7,
        }
        assert result.data == {"ok": True}

    def test_candidate_query_fields_reach_the_native_wire(self):
        async def scenario():
            published = []
            bridge = AxBridge(timeout_s=1.0, expected_token="test-token")
            bridge.bind(asyncio.get_running_loop(), published.append)
            client_id = attach_app(bridge)
            task = asyncio.create_task(bridge.observe(
                turn_id="turn_1",
                observation_epoch=4,
                query=ObservationQuery.from_tool_arguments({
                    "query": "play video",
                    "expected_roles": ["AXButton"],
                    "expected_actions": ["AXPress"],
                    "scope": "descendant",
                    "ancestor_ref": "player",
                    "result_limit": 20,
                    "include_menu": True,
                }),
                denied_bundles=["com.apple.keychainaccess"],
            ))
            while not published:
                await asyncio.sleep(0)
            request = published[0]
            bridge.resolve(
                request["request_id"], {"candidates": []},
                client_id=client_id,
                sequence=request["sequence"],
                turn_id=request["turn_id"],
                observation_epoch=request["observation_epoch"],
            )
            await task
            return request

        request = run_loop_test(scenario())
        assert request["params"]["query"] == {
            "search_terms": ["play", "video"],
            "expected_roles": ["AXButton"],
            "expected_actions": ["AXPress"],
            "scope": "descendant",
            "ancestor_ref": "player",
            "result_limit": 20,
            "include_menu": True,
            "denied_bundles": ["com.apple.keychainaccess"],
        }

    def test_environment_token_is_captured_then_removed(self):
        with patch.dict(os.environ, {"CONN_BRIDGE_TOKEN": "environment-token"}):
            bridge = AxBridge()
            assert bridge.expected_token == "environment-token"
            assert "CONN_BRIDGE_TOKEN" not in os.environ

    def test_no_app_attached_returns_none_without_publishing(self):
        published = []

        async def scenario():
            bridge = AxBridge(timeout_s=0.5)
            bridge.bind(asyncio.get_running_loop(), published.append)
            return await asyncio.to_thread(bridge.request_context_sync)

        assert run_loop_test(scenario()) is None
        assert published == []

    def test_unbound_bridge_returns_none(self):
        bridge = AxBridge()
        assert bridge.request_context_sync() is None

    def test_round_trip_resolves_with_app_payload(self):
        published = []
        payload = {"app": "Safari", "bundle_id": "com.apple.Safari",
                   "window_title": "Apple", "selected_text": None,
                   "accessibility": "granted"}

        async def scenario():
            loop = asyncio.get_running_loop()
            bridge = AxBridge(timeout_s=1.0, expected_token="test-token")
            bridge.bind(loop, published.append)
            client_id = attach_app(bridge)

            def answer():
                while not published:
                    pass
                request_id = published[0]["request_id"]
                sequence = published[0]["sequence"]
                turn_id = published[0]["turn_id"]
                observation_epoch = published[0]["observation_epoch"]
                loop.call_soon_threadsafe(
                    lambda: bridge.resolve(
                        request_id,
                        payload,
                        client_id=client_id,
                        sequence=sequence,
                        turn_id=turn_id,
                        observation_epoch=observation_epoch,
                    )
                )

            threading.Thread(target=answer).start()
            return await asyncio.to_thread(bridge.request_context_sync)

        result = run_loop_test(scenario())
        assert result == payload
        assert published[0]["type"] == "ax_read"

    def test_timeout_returns_none(self):
        async def scenario():
            bridge = AxBridge(timeout_s=0.05, expected_token="test-token")
            bridge.bind(asyncio.get_running_loop(), lambda msg: None)
            attach_app(bridge)
            return await asyncio.to_thread(bridge.request_context_sync)

        assert run_loop_test(scenario()) is None

    def test_detach_returns_bridge_to_fallback(self):
        published = []

        async def scenario():
            bridge = AxBridge(timeout_s=0.5, expected_token="test-token")
            bridge.bind(asyncio.get_running_loop(), published.append)
            client_id = attach_app(bridge)
            bridge.app_detached(client_id)
            return await asyncio.to_thread(bridge.request_context_sync)

        assert run_loop_test(scenario()) is None
        assert published == []

    def test_reply_must_match_turn_observation_and_sequence(self):
        async def scenario():
            published = []
            bridge = AxBridge(timeout_s=1.0, expected_token="test-token")
            bridge.bind(asyncio.get_running_loop(), published.append)
            client_id = attach_app(bridge)
            request_task = asyncio.create_task(bridge.request())
            while not published:
                await asyncio.sleep(0)
            request = published[0]

            bridge.resolve(
                request["request_id"],
                {"app": "wrong turn"},
                client_id=client_id,
                turn_id="wrong-turn",
                observation_epoch=request["observation_epoch"],
                sequence=request["sequence"],
            )
            await asyncio.sleep(0)
            assert not request_task.done()

            bridge.resolve(
                request["request_id"],
                {"app": "wrong observation"},
                client_id=client_id,
                turn_id=request["turn_id"],
                observation_epoch=request["observation_epoch"] + 1,
                sequence=request["sequence"],
            )
            await asyncio.sleep(0)
            assert not request_task.done()

            bridge.resolve(
                request["request_id"],
                {"app": "Safari"},
                client_id=client_id,
                turn_id=request["turn_id"],
                observation_epoch=request["observation_epoch"],
                sequence=request["sequence"],
            )
            return await request_task, bridge.rejected_replies

        result, rejected = run_loop_test(scenario())
        assert result == {"app": "Safari"}
        assert rejected == 2

    def test_replayed_sequence_cannot_resolve_next_request(self):
        async def scenario():
            published = []
            bridge = AxBridge(timeout_s=1.0, expected_token="test-token")
            bridge.bind(asyncio.get_running_loop(), published.append)
            client_id = attach_app(bridge)

            first_task = asyncio.create_task(bridge.request())
            while len(published) < 1:
                await asyncio.sleep(0)
            first = published[0]
            bridge.resolve(
                first["request_id"], {"app": "Safari"},
                client_id=client_id,
                turn_id=first["turn_id"],
                observation_epoch=first["observation_epoch"],
                sequence=first["sequence"],
            )
            await first_task

            second_task = asyncio.create_task(bridge.request())
            while len(published) < 2:
                await asyncio.sleep(0)
            second = published[1]
            bridge.resolve(
                second["request_id"], {"app": "stale"},
                client_id=client_id,
                turn_id=second["turn_id"],
                observation_epoch=second["observation_epoch"],
                sequence=first["sequence"],
            )
            await asyncio.sleep(0)
            assert not second_task.done()

            bridge.resolve(
                second["request_id"], {"app": "Notes"},
                client_id=client_id,
                turn_id=second["turn_id"],
                observation_epoch=second["observation_epoch"],
                sequence=second["sequence"],
            )
            return await second_task, bridge.rejected_replies

        result, rejected = run_loop_test(scenario())
        assert result == {"app": "Notes"}
        assert rejected == 1

    def test_detach_resolves_pending_request_fail_closed(self):
        async def scenario():
            published = []
            bridge = AxBridge(timeout_s=1.0, expected_token="test-token")
            bridge.bind(asyncio.get_running_loop(), published.append)
            client_id = attach_app(bridge)
            request_task = asyncio.create_task(bridge.request())
            while not published:
                await asyncio.sleep(0)

            bridge.app_detached(client_id)
            return await asyncio.wait_for(request_task, timeout=0.1)

        assert run_loop_test(scenario()) is None

    def test_resolve_unknown_request_is_a_no_op(self):
        bridge = AxBridge()
        bridge.resolve("axread_ghost", {"app": "Safari"})  # must not raise


class FakeReader:
    def __init__(self, payload):
        self.payload = payload

    def request_context_sync(self):
        return self.payload


class TestGetContextLanes:
    def test_app_lane_wins_when_it_answers(self, ctx):
        ctx.ax_reader = FakeReader({
            "app": "Safari", "bundle_id": "com.apple.Safari",
            "window_title": "Apple", "selected_text": "hello",
            "accessibility": "granted",
        })
        data = mac.get_context({}, ctx)
        assert data["source"] == "app"
        assert data["app"] == "Safari"
        assert data["window_title"] == "Apple"
        assert data["selected_text"] == "hello"
        assert data["accessibility"] == "granted"

    def test_app_payload_is_normalized(self, ctx):
        ctx.ax_reader = FakeReader({
            "app": "Safari", "bundle_id": "com.apple.Safari",
            "window_title": None, "selected_text": "x" * 5000,
            "accessibility": "weird_value", "extra_key": "dropped",
        })
        data = mac.get_context({}, ctx)
        assert len(data["selected_text"]) == 2000
        assert data["accessibility"] == "not_granted"
        assert "extra_key" not in data

    def test_python_fallback_when_app_lane_silent(self, ctx):
        from conn.tools import frontmost

        ctx.ax_reader = FakeReader(None)
        with patch.object(frontmost, "frontmost_application", return_value=None):
            data = mac.get_context({}, ctx)
        assert data["source"] == "daemon"
        assert data["app"] is None

    def test_python_fallback_without_reader(self, ctx):
        from conn.tools import frontmost

        assert ctx.ax_reader is None
        with patch.object(frontmost, "frontmost_application", return_value=None):
            data = mac.get_context({}, ctx)
        assert data["source"] == "daemon"


class TestServerRouting:
    def test_ax_read_result_resolves_the_bridge(self):
        from conn.server.http import handle_client

        class AppStub:
            def __init__(self):
                self.resolved = None

            class _Bridge:
                def __init__(self, outer):
                    self.outer = outer

                def resolve(self, request_id, data, **metadata):
                    self.outer.resolved = (request_id, data)

            @property
            def ax_bridge(self):
                return AppStub._Bridge(self)

        stub = AppStub()
        asyncio.run(handle_client(stub, {"type": "ax_read_result",
                                         "request_id": "axread_1",
                                         "data": {"app": "Safari"}},
                                  authenticated_role="app", client_id="app"))
        assert stub.resolved == ("axread_1", {"app": "Safari"})

    def test_client_hello_reports_role(self):
        from conn.server.http import client_role

        assert client_role({"type": "client_hello", "role": "app"}) == "app"
        assert client_role({"type": "client_hello"}) is None
        assert client_role({"type": "ptt_down"}) is None
