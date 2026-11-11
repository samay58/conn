"""Stop must not hold the app socket loop while tools wait on results that
arrive on that same socket."""
from __future__ import annotations

import asyncio

from conn.app import ConnApp
from conn.realtime.fake import FakeRealtimeAdapter
from conn.server.http import handle_client
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


def add_tool(app):
    tool_done = asyncio.Event()
    tool = asyncio.create_task(tool_done.wait())
    app._tool_tasks.add(tool)
    tool.add_done_callback(app._tool_tasks.discard)
    return tool_done


def test_stop_message_does_not_block_the_socket_loop():
    class Stub:
        def __init__(self):
            self.release = asyncio.Event()
            self.stops = []

        async def on_stop(self, client_ts_ms=None):
            self.stops.append(client_ts_ms)
            await self.release.wait()

        def on_stop_soon(self, client_ts_ms=None):
            self.task = asyncio.create_task(self.on_stop(client_ts_ms=client_ts_ms))

    async def run():
        stub = Stub()
        await asyncio.wait_for(
            handle_client(stub, {"type": "stop", "client_ts_ms": 7},
                          authenticated_role="app", client_id="c"),
            timeout=0.5,
        )
        await asyncio.sleep(0)
        stub.release.set()
        await stub.task
        return stub.stops

    assert asyncio.run(run()) == [7]


def test_stop_waits_for_an_in_flight_tool_without_holding_the_loop(cfg, ctx):
    async def run():
        app, _messages = build_app(cfg, ctx)
        app._loop = asyncio.get_running_loop()
        tool_done = add_tool(app)

        await asyncio.wait_for(
            handle_client(app, {"type": "stop"}, authenticated_role="app",
                          client_id="c"),
            timeout=0.5,
        )
        await asyncio.sleep(0)
        stopping_while_tool_runs = app._stopping
        tool_done.set()
        await app._quiesce_stop_tasks()
        kinds = [e["kind"] for e in app.trace.read()]
        stopping_after = app._stopping
        await app.stop()
        return stopping_while_tool_runs, stopping_after, kinds

    during, after, kinds = asyncio.run(run())
    assert during is True
    assert after is False
    assert "kill_switch" in kinds


def test_session_stop_waits_for_a_pending_stop_task(cfg, ctx):
    async def run():
        app, _messages = build_app(cfg, ctx)
        app._loop = asyncio.get_running_loop()
        tool_done = add_tool(app)
        app.on_stop_soon()
        asyncio.get_running_loop().call_later(0.05, tool_done.set)
        await asyncio.wait_for(app.stop(), timeout=2)
        return app

    app = asyncio.run(run())
    assert not app._stop_tasks


def test_second_stop_press_is_coalesced(cfg, ctx):
    async def run():
        app, _messages = build_app(cfg, ctx)
        app._loop = asyncio.get_running_loop()
        tool_done = add_tool(app)
        app.on_stop_soon()
        app.on_stop_soon()
        await asyncio.sleep(0)
        count = len(app._stop_tasks)
        kinds = [e["kind"] for e in app.trace.read()]
        tool_done.set()
        await app._quiesce_stop_tasks()
        stopping = app._stopping
        await app.stop()
        return count, kinds, stopping

    count, kinds, stopping = asyncio.run(run())
    assert count == 1
    assert "kill_switch_coalesced" in kinds
    assert stopping is False
