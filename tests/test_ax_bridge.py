"""Context reads via the app's Accessibility grant (bug 2 / S2).

TCC grants bind to the binary: Conn.app holds Accessibility, the daemon's
python does not. The daemon publishes an ax_read request over the existing
websocket; the app answers with ax_read_result; executors reach the round
trip through a thread-safe bridge. No app attached means an immediate None
so the python fallback never pays a timeout.
"""

import asyncio
import threading
from unittest.mock import patch

from conn.ax_bridge import AxBridge
from conn.tools import mac


def run_loop_test(coro):
    return asyncio.run(coro)


class TestAxBridge:
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
            bridge = AxBridge(timeout_s=1.0)
            bridge.bind(loop, published.append)
            bridge.app_attached()

            def answer():
                while not published:
                    pass
                request_id = published[0]["request_id"]
                loop.call_soon_threadsafe(bridge.resolve, request_id, payload)

            threading.Thread(target=answer).start()
            return await asyncio.to_thread(bridge.request_context_sync)

        result = run_loop_test(scenario())
        assert result == payload
        assert published[0]["type"] == "ax_read"

    def test_timeout_returns_none(self):
        async def scenario():
            bridge = AxBridge(timeout_s=0.05)
            bridge.bind(asyncio.get_running_loop(), lambda msg: None)
            bridge.app_attached()
            return await asyncio.to_thread(bridge.request_context_sync)

        assert run_loop_test(scenario()) is None

    def test_detach_returns_bridge_to_fallback(self):
        published = []

        async def scenario():
            bridge = AxBridge(timeout_s=0.5)
            bridge.bind(asyncio.get_running_loop(), published.append)
            bridge.app_attached()
            bridge.app_detached()
            return await asyncio.to_thread(bridge.request_context_sync)

        assert run_loop_test(scenario()) is None
        assert published == []

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

                def resolve(self, request_id, data):
                    self.outer.resolved = (request_id, data)

            @property
            def ax_bridge(self):
                return AppStub._Bridge(self)

        stub = AppStub()
        asyncio.run(handle_client(stub, {"type": "ax_read_result",
                                         "request_id": "axread_1",
                                         "data": {"app": "Safari"}}))
        assert stub.resolved == ("axread_1", {"app": "Safari"})

    def test_client_hello_reports_role(self):
        from conn.server.http import client_role

        assert client_role({"type": "client_hello", "role": "app"}) == "app"
        assert client_role({"type": "client_hello"}) is None
        assert client_role({"type": "ptt_down"}) is None
