"""T2 grant preflight: ax_grants is traced and published at session start and
on app attach, with honest lane states, and accessibility refusals name the
lane plus the exact artifact to grant.
"""

from __future__ import annotations

import asyncio

import pytest

import conn.identity as identity_module
from conn.app import ConnApp
from conn.realtime.fake import FakeRealtimeAdapter
from conn.tools.ax_input import FakeInputBackend, hotkey
from conn.tools.base import ToolError
from conn.tools.fake_executors import FAKE_EXECUTORS
from conn.tools.harness import ToolHarness
from conn.tools.registry import build_registry


def build_app(cfg, ctx):
    cfg.data_dir = ctx.screenshot_dir.parent / "data"
    harness = ToolHarness(build_registry(), cfg, ctx, executors=FAKE_EXECUTORS)
    app = ConnApp(cfg, FakeRealtimeAdapter(pace_s=0.0), harness)
    messages = []
    app.publisher = messages.append
    return app, messages


def grant_events(messages):
    return [m for m in messages if m.get("type") == "ax_grants"]


def test_session_start_publishes_ax_grants(cfg, ctx, monkeypatch):
    monkeypatch.setattr(identity_module, "python_ax_trusted", lambda: False)
    monkeypatch.setattr(identity_module, "grant_target", lambda image_path=None: "/x/Python.app")
    app, messages = build_app(cfg, ctx)

    async def run():
        await app.start()
        await app.stop()

    asyncio.run(run())
    events = grant_events(messages)
    assert len(events) == 1
    assert events[0]["python_ax"] == "not_granted"
    assert events[0]["app_ax"] == "unattached"
    assert events[0]["python_grant_target"] == "/x/Python.app"


def test_app_attach_reports_app_lane(cfg, ctx, monkeypatch):
    monkeypatch.setattr(identity_module, "python_ax_trusted", lambda: True)
    app, messages = build_app(cfg, ctx)

    async def run():
        await app.start()
        app.ax_bridge.app_attached()

        async def fake_request():
            return {"accessibility": "not_granted"}

        monkeypatch.setattr(app.ax_bridge, "request", fake_request)
        await app.publish_ax_grants()
        await app.stop()

    asyncio.run(run())
    events = grant_events(messages)
    assert events[-1]["python_ax"] == "granted"
    assert events[-1]["app_ax"] == "not_granted"


def test_ax_grants_traced(cfg, ctx, monkeypatch):
    monkeypatch.setattr(identity_module, "python_ax_trusted", lambda: None)
    app, _messages = build_app(cfg, ctx)

    async def run():
        await app.start()
        await app.stop()

    asyncio.run(run())
    lines = app.trace.path.read_text().splitlines()
    assert any('"kind": "ax_grants"' in line and '"python_ax": "unknown"' in line
               for line in lines)


def test_untrusted_refusal_names_lane_and_target(ctx, monkeypatch):
    monkeypatch.setattr(identity_module, "grant_target", lambda image_path=None: "/x/Python.app")
    ctx.input_backend = FakeInputBackend(posting_ok=False)
    with pytest.raises(ToolError, match="python lane") as excinfo:
        hotkey({"combo": "cmd+t"}, ctx)
    assert "/x/Python.app" in str(excinfo.value)
    assert "accessibility_untrusted" in str(excinfo.value)
