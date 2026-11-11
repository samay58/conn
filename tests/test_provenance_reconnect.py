"""A new upstream socket is a new server session; the response-provenance
ledger must not carry requests from the old one."""
import asyncio

import conn.app as app_module
from conn.app import ConnApp
from conn.events import ResponseProvenance
from conn.realtime.fake import FakeRealtimeAdapter
from conn.state import ResponseProvenanceLedger
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


def stale_request(app):
    app._response_provenance.request(
        ResponseProvenance("turn_old", response_epoch=1, observation_epoch=1))
    app._response_provenance.cancel_current()


def test_ledger_reset_forgets_everything():
    ledger = ResponseProvenanceLedger()
    old = ResponseProvenance("turn_old", response_epoch=1, observation_epoch=1)
    new = ResponseProvenance("turn_new", response_epoch=1, observation_epoch=2)
    ledger.request(old)
    ledger.cancel_current()
    ledger.reset()
    ledger.request(new)
    assert ledger.created("response_new") == new
    assert ledger.resolve("response_new") == new
    assert ledger.active_response_id == "response_new"


def test_reconnect_drops_requests_from_the_old_socket(cfg, ctx, monkeypatch):
    monkeypatch.setattr(app_module.asyncio, "sleep", fast_sleep)

    async def run():
        app, _messages = build_app(cfg, ctx)
        app._loop = asyncio.get_running_loop()
        stale_request(app)
        await app._handle_disconnect("socket closed")
        if app._pump_task:
            app._pump_task.cancel()
        return app._response_provenance

    ledger = asyncio.run(run())
    assert ledger.pending == []
    assert ledger.bindings == {}
    assert ledger.active_response_id is None


def test_lazy_connect_drops_requests_from_the_old_socket(cfg, ctx):
    async def run():
        app, _messages = build_app(cfg, ctx)
        await app.adapter.connect()
        await app.adapter.close()
        assert app.adapter.connected is False
        stale_request(app)
        await app._ensure_connected()
        if app._pump_task:
            app._pump_task.cancel()
        return app._response_provenance

    ledger = asyncio.run(run())
    assert ledger.pending == []
