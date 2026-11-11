"""Every billed token reaches the cost meter: completed, cancelled and
unbound (stale) responses alike."""

from __future__ import annotations

import asyncio

from conn.app import ConnApp
from conn.config import Config
from conn.events import ResponseProvenance
from conn.realtime.base import RtResponseCancelled, RtResponseDone
from conn.realtime.fake import FakeRealtimeAdapter
from conn.realtime.openai_ws import OpenAIRealtimeAdapter
from conn.tools.fake_executors import FAKE_EXECUTORS
from conn.tools.harness import ToolHarness
from conn.tools.registry import build_registry

USAGE = {
    "input_tokens": 640, "output_tokens": 62,
    "input_token_details": {"text_tokens": 480, "audio_tokens": 160, "cached_tokens": 320,
                            "cached_tokens_details": {"text_tokens": 320, "audio_tokens": 0}},
    "output_token_details": {"text_tokens": 22, "audio_tokens": 40},
}


def build_app(cfg, ctx):
    cfg.data_dir = ctx.screenshot_dir.parent / "data"
    harness = ToolHarness(build_registry(), cfg, ctx, executors=FAKE_EXECUTORS)
    adapter = FakeRealtimeAdapter(pace_s=0.0)
    app = ConnApp(cfg, adapter, harness)
    messages = []
    app.publisher = messages.append
    return app, messages


def bind(app, response_id):
    app._response_provenance.request(
        ResponseProvenance("turn_1", response_epoch=1, observation_epoch=1))
    app._response_provenance.created(response_id)


def kinds(app):
    return [e["kind"] for e in app.trace.read()]


def test_cancelled_response_done_carries_usage():
    adapter = OpenAIRealtimeAdapter(Config(), tools=[], instructions="")
    adapter._normalize({"type": "response.created", "response": {"id": "r1"}})
    events = adapter._normalize({"type": "response.done", "response": {
        "id": "r1", "status": "cancelled", "usage": USAGE}})
    assert len(events) == 1
    assert isinstance(events[0], RtResponseCancelled)
    assert events[0].usage == USAGE


def test_cancelled_response_usage_is_ingested(cfg, ctx):
    app, _ = build_app(cfg, ctx)

    async def run():
        bind(app, "r_cancel")
        await app._on_rt_event(RtResponseCancelled(response_id="r_cancel", usage=USAGE))

    asyncio.run(run())
    assert app.cost.spent_usd > 0
    assert len(app.cost.turns) == 1
    assert "stale_realtime_event" not in kinds(app)


def test_unbound_response_usage_is_ingested(cfg, ctx):
    app, _ = build_app(cfg, ctx)

    async def run():
        await app._on_rt_event(RtResponseDone(usage=USAGE, response_id="r_unbound"))

    asyncio.run(run())
    assert app.cost.spent_usd > 0
    assert len(app.cost.turns) == 1
    assert "stale_realtime_event" in kinds(app)


def test_bound_response_usage_is_counted_once(cfg, ctx):
    app, _ = build_app(cfg, ctx)

    async def run():
        bind(app, "r1")
        await app._on_rt_event(RtResponseDone(usage=USAGE, response_id="r1"))

    asyncio.run(run())
    assert len(app.cost.turns) == 1
    assert kinds(app).count("response_done") == 1
