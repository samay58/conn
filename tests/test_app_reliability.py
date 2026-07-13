"""App wiring reliability: adapter send failures during a turn must land the
machine in FAILED (not leave it wedged mid-transition), rejected input while
the machine cannot accept it must reach clients as a reject_input message,
healthz must report live phase staleness, and the stuck-phase watchdog timer
must be armed. Covers defects 3, 4, and 7 from the reliability ledger.
"""

from __future__ import annotations

import asyncio

import pytest
from starlette.testclient import TestClient

import conn.app as app_module
from conn.app import ConnApp, reconnect_delays
from conn.config import Config
from conn.events import (
    Gate, PttDown, PttUp, TextCommand, ToolCall, ToolProposed,
)
from conn.realtime.fake import FakeRealtimeAdapter
from conn.server.http import build_server
from conn.state import Phase
from conn.tools.fake_executors import FAKE_EXECUTORS
from conn.tools.harness import ToolHarness
from conn.tools.registry import build_registry


def build_app(cfg, ctx):
    cfg.data_dir = ctx.screenshot_dir.parent / "data"
    harness = ToolHarness(build_registry(), cfg, ctx, executors=FAKE_EXECUTORS)
    adapter = FakeRealtimeAdapter(pace_s=0.0)
    app = ConnApp(cfg, adapter, harness)
    messages = []
    app.publisher = messages.append
    return app, messages


async def fast_sleep(_delay=None) -> None:
    return


class BrokenAdapter:
    """Adapter double whose configured send method (and every reconnect
    attempt) always raises, so _handle_disconnect's reconnect loop exhausts
    and the machine is left in FAILED rather than bounced back to IDLE."""

    def __init__(self, break_method: str):
        self.connected = True
        self.break_method = break_method
        self.close_count = 0
        self.connect_count = 0

    async def connect(self):
        self.connect_count += 1
        raise RuntimeError("connect always fails in this stub")

    async def close(self):
        self.close_count += 1
        self.connected = False

    async def append_audio(self, pcm):
        pass

    async def clear_input(self):
        pass

    async def commit_input(self):
        if self.break_method == "commit_input":
            raise RuntimeError("commit_input boom")

    async def create_response(self):
        if self.break_method == "create_response":
            raise RuntimeError("create_response boom")

    async def cancel_response(self):
        pass

    async def send_text(self, text):
        if self.break_method == "send_text":
            raise RuntimeError("send_text boom")

    async def send_tool_result(self, call_id, output):
        if self.break_method == "send_tool_result":
            raise RuntimeError("send_tool_result boom")

    async def events(self):
        return
        yield  # pragma: no cover -- never reached, keeps this an async generator


class GatedReconnect(BrokenAdapter):
    def __init__(self):
        super().__init__("send_text")
        self.entered = asyncio.Event()
        self.release = asyncio.Event()

    async def connect(self):
        self.connect_count += 1
        self.entered.set()
        await self.release.wait()
        self.connected = True


class TestSendFailureDisconnect:
    @pytest.mark.parametrize("break_method", ["commit_input", "create_response"])
    def test_ptt_turn_send_failure_lands_in_failed_not_thinking(
            self, cfg, ctx, monkeypatch, break_method):
        monkeypatch.setattr(app_module.asyncio, "sleep", fast_sleep)

        async def run():
            harness = ToolHarness(build_registry(), cfg, ctx, executors=FAKE_EXECUTORS)
            adapter = BrokenAdapter(break_method)
            app = ConnApp(cfg, adapter, harness)
            app.publisher = lambda m: None
            app._loop = asyncio.get_running_loop()
            await app.dispatch(PttDown(ts_ms=1000))
            await app.dispatch(PttUp(ts_ms=2000))
            return app

        app = asyncio.run(run())
        assert app.machine.phase is Phase.FAILED
        assert app.machine.phase is not Phase.THINKING


class TestReconnectBackoff:
    @pytest.mark.parametrize("field", ["reconnect_window_s",
                                        "reconnect_max_delay_s"])
    def test_reconnect_timings_must_be_positive(self, field):
        with pytest.raises(ValueError):
            Config(session={field: 0})

    def test_schedule_retries_for_five_minutes_with_a_thirty_second_cap(self):
        delays = list(reconnect_delays(window_s=300.0, initial_s=0.5,
                                       max_delay_s=30.0))

        assert delays[:7] == [0.5, 1.0, 2.0, 4.0, 8.0, 16.0, 30.0]
        assert max(delays) == 30.0
        assert sum(delays) == pytest.approx(300.0)

    def test_machine_stays_failed_until_a_late_reconnect_succeeds(
            self, cfg, ctx, monkeypatch):
        sleeps = []

        async def record_sleep(delay):
            sleeps.append(delay)

        monkeypatch.setattr(app_module.asyncio, "sleep", record_sleep)

        class EventuallyConnects(BrokenAdapter):
            def __init__(self):
                super().__init__("send_text")
                self.phase_during_connect = []
                self.app = None

            async def connect(self):
                self.connect_count += 1
                self.phase_during_connect.append(self.app.machine.phase)
                if self.connect_count < 8:
                    raise RuntimeError("network still unavailable")
                self.connected = True

        async def run():
            harness = ToolHarness(build_registry(), cfg, ctx,
                                  executors=FAKE_EXECUTORS)
            adapter = EventuallyConnects()
            app = ConnApp(cfg, adapter, harness)
            adapter.app = app
            app.publisher = lambda m: None
            app._loop = asyncio.get_running_loop()
            await app._handle_disconnect("socket closed")
            if app._pump_task:
                app._pump_task.cancel()
            return app, adapter

        app, adapter = asyncio.run(run())
        assert adapter.connect_count == 8
        assert sleeps == [0.5, 1.0, 2.0, 4.0, 8.0, 16.0, 30.0]
        assert set(adapter.phase_during_connect) == {Phase.FAILED}
        assert app.machine.phase is Phase.IDLE

    def test_concurrent_disconnect_paths_share_one_reconnect(self, cfg, ctx):
        async def run():
            harness = ToolHarness(build_registry(), cfg, ctx,
                                  executors=FAKE_EXECUTORS)
            adapter = GatedReconnect()
            app = ConnApp(cfg, adapter, harness)
            app.publisher = lambda m: None
            app._loop = asyncio.get_running_loop()
            first = asyncio.create_task(app._handle_disconnect("socket closed"))
            await adapter.entered.wait()
            second = asyncio.create_task(app._handle_disconnect("send failed"))
            await asyncio.sleep(0)
            adapter.release.set()
            await asyncio.gather(first, second)
            if app._pump_task:
                app._pump_task.cancel()
            return app, adapter

        app, adapter = asyncio.run(run())
        assert adapter.connect_count == 1
        assert app.machine.phase is Phase.IDLE

    def test_ptt_during_reconnect_uses_the_existing_connection_attempt(
            self, cfg, ctx):
        async def run():
            harness = ToolHarness(build_registry(), cfg, ctx,
                                  executors=FAKE_EXECUTORS)
            adapter = GatedReconnect()
            app = ConnApp(cfg, adapter, harness)
            app.publisher = lambda m: None
            app._loop = asyncio.get_running_loop()
            reconnect = asyncio.create_task(
                app._handle_disconnect("socket closed"))
            await adapter.entered.wait()
            ptt = asyncio.create_task(app.on_ptt_down())
            await asyncio.sleep(0)
            adapter.release.set()
            await asyncio.gather(reconnect, ptt)
            await app.stop()
            return adapter

        adapter = asyncio.run(run())
        assert adapter.connect_count == 1

    def test_exhausted_reconnect_tells_the_user_to_relaunch(
            self, cfg, ctx, monkeypatch):
        monkeypatch.setattr(app_module.asyncio, "sleep", fast_sleep)
        cfg.session.reconnect_window_s = 0.5

        async def run():
            harness = ToolHarness(build_registry(), cfg, ctx,
                                  executors=FAKE_EXECUTORS)
            adapter = BrokenAdapter("send_text")
            app = ConnApp(cfg, adapter, harness)
            messages = []
            app.publisher = messages.append
            app._loop = asyncio.get_running_loop()
            await app._handle_disconnect("socket closed")
            return messages

        messages = asyncio.run(run())
        assert messages[-1] == {
            "type": "toast",
            "level": "error",
            "text": "Conn is still offline. Quit and reopen Conn.",
        }


class TestSendFailureDisconnectContinued:
    def test_send_text_failure_lands_in_failed(self, cfg, ctx, monkeypatch):
        monkeypatch.setattr(app_module.asyncio, "sleep", fast_sleep)

        async def run():
            harness = ToolHarness(build_registry(), cfg, ctx, executors=FAKE_EXECUTORS)
            adapter = BrokenAdapter("send_text")
            app = ConnApp(cfg, adapter, harness)
            app.publisher = lambda m: None
            app._loop = asyncio.get_running_loop()
            await app.dispatch(TextCommand(text="hello there"))
            return app

        app = asyncio.run(run())
        assert app.machine.phase is Phase.FAILED

    def test_send_failure_closes_stale_adapter_before_reconnect(self, cfg, ctx, monkeypatch):
        monkeypatch.setattr(app_module.asyncio, "sleep", fast_sleep)

        async def run():
            harness = ToolHarness(build_registry(), cfg, ctx, executors=FAKE_EXECUTORS)
            adapter = BrokenAdapter("send_text")
            app = ConnApp(cfg, adapter, harness)
            app.publisher = lambda m: None
            app._loop = asyncio.get_running_loop()
            await app.dispatch(TextCommand(text="hello there"))
            return adapter

        adapter = asyncio.run(run())
        assert adapter.close_count == 1
        assert adapter.connected is False

    def test_send_tool_result_failure_lands_in_failed(self, cfg, ctx, monkeypatch):
        monkeypatch.setattr(app_module.asyncio, "sleep", fast_sleep)

        async def run():
            harness = ToolHarness(build_registry(), cfg, ctx, executors=FAKE_EXECUTORS)
            adapter = BrokenAdapter("send_tool_result")
            app = ConnApp(cfg, adapter, harness)
            app.publisher = lambda m: None
            app._loop = asyncio.get_running_loop()
            await app.dispatch(PttDown(ts_ms=1000))
            await app.dispatch(PttUp(ts_ms=2000))
            assert app.machine.phase is Phase.THINKING
            call = ToolCall(call_id="c1", name="app_open", arguments={"app": "Obsidian"},
                            gate=Gate.AUTO, preview="Open app: Obsidian")
            await app.dispatch(ToolProposed(call=call))
            for _ in range(200):
                if app.machine.phase is Phase.FAILED:
                    break
                await asyncio.sleep(0.01)
            return app

        app = asyncio.run(run())
        assert app.machine.phase is Phase.FAILED


class TestFixtureDataIsolation:
    def test_shared_config_writes_only_below_pytest_tmp(self, cfg, tmp_path):
        assert cfg.data_dir.is_relative_to(tmp_path)


class TestRejectInputPublished:
    def test_ptt_down_while_thinking_publishes_reject_input(self, cfg, ctx):
        async def run():
            app, messages = build_app(cfg, ctx)
            app._loop = asyncio.get_running_loop()
            app.machine.handle(PttDown(ts_ms=1000))
            app.machine.handle(PttUp(ts_ms=2000))
            assert app.machine.phase is Phase.THINKING
            await app.dispatch(PttDown(ts_ms=3000))
            return messages

        messages = asyncio.run(run())
        rejects = [m for m in messages if m.get("type") == "reject_input"]
        assert rejects and rejects[0]["reason"] == "thinking"


class TestHealthz:
    def test_healthz_reports_phase_age_and_upstream_connected(self, cfg, ctx, monkeypatch):
        fake_time = [100.0]
        monkeypatch.setattr(app_module.time, "monotonic", lambda: fake_time[0])

        harness = ToolHarness(build_registry(), cfg, ctx, executors=FAKE_EXECUTORS)
        adapter = FakeRealtimeAdapter(pace_s=0.0)
        app = ConnApp(cfg, adapter, harness)

        starlette_app = build_server(app)
        client = TestClient(starlette_app)

        r1 = client.get("/healthz")
        assert r1.status_code == 200
        data1 = r1.json()
        assert "phase_age_s" in data1
        assert "upstream_connected" in data1
        assert data1["upstream_connected"] is False
        assert data1["phase_age_s"] == pytest.approx(0.0)

        fake_time[0] += 5.0
        data2 = client.get("/healthz").json()
        assert data2["phase_age_s"] == pytest.approx(5.0)

        fake_time[0] += 12.5
        data3 = client.get("/healthz").json()
        assert data3["phase_age_s"] == pytest.approx(17.5)


class TestWatchdogArmed:
    def test_start_arms_the_watchdog_timer(self, cfg, ctx):
        async def run():
            app, _ = build_app(cfg, ctx)
            await app.start()
            armed = app._watchdog_timer is not None
            await app.stop()
            return armed

        assert asyncio.run(run())
