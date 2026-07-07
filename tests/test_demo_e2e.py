"""Full loop through the composition root with the fake adapter and fake
executors: text command in, transcript out, tool proposals gated, approval
chip honored, continuation discipline held, trace and receipt written.
No credentials, no network, no audio hardware.
"""

import asyncio
import json

import pytest

from conn.app import ConnApp
from conn.realtime.fake import FakeRealtimeAdapter, load_scenarios
from conn.state import Phase
from conn.tools.fake_executors import FAKE_EXECUTORS
from conn.tools.harness import ToolHarness
from conn.tools.registry import build_registry


def build_app(cfg, ctx, risk_overrides=None):
    if risk_overrides:
        cfg.risk_overrides.update(risk_overrides)
    cfg.data_dir = ctx.screenshot_dir.parent / "data"
    harness = ToolHarness(build_registry(), cfg, ctx, executors=FAKE_EXECUTORS)
    adapter = FakeRealtimeAdapter(pace_s=0.0)
    app = ConnApp(cfg, adapter, harness)
    messages = []
    app.publisher = messages.append
    return app, messages


async def wait_for_phase(app, phase, timeout=3.0):
    async def poll():
        while app.machine.phase is not phase:
            await asyncio.sleep(0.01)
    await asyncio.wait_for(poll(), timeout)


async def wait_for_chip(app, timeout=3.0):
    async def poll():
        while not app.approvals.pending:
            await asyncio.sleep(0.01)
    await asyncio.wait_for(poll(), timeout)


class TestDemoLoop:
    def test_search_and_open_note_full_turn(self, cfg, ctx):
        async def run():
            app, messages = build_app(cfg, ctx)
            await app.start()
            await app.on_text("find the transformer paper notes in my vault and open it")
            await wait_for_phase(app, Phase.DONE)
            await app.stop()
            return app, messages

        app, messages = asyncio.run(run())

        kinds = [e["kind"] for e in app.trace.read()]
        assert kinds.count("tool_proposed") == 2
        assert kinds.count("tool_result") == 2
        assert "session_end" in kinds

        proposed = [e for e in app.trace.read() if e["kind"] == "tool_proposed"]
        assert proposed[0]["name"] == "phoenix_search"
        assert proposed[1]["name"] == "phoenix_open_note"
        assert all(p["gate"] == "auto" for p in proposed)

        receipt = app.cost.receipt()
        assert receipt["turns"] == 3
        assert receipt["tool_calls"] == 2
        assert receipt["estimated_usd"] > 0

        transcript = "".join(m["text"] for m in messages if m["type"] == "transcript_delta")
        assert "Searching the vault" in transcript
        assert "Done" in transcript

    def test_approval_flow_approve(self, cfg, ctx):
        async def run():
            app, messages = build_app(cfg, ctx, {"clipboard_set": "confirm"})
            await app.start()
            await app.on_text("copy the qmd search command to my clipboard")
            await wait_for_chip(app)
            assert app.machine.phase is Phase.AWAITING_APPROVAL
            call_id = next(iter(app.approvals.pending))
            preview = app.approvals.pending[call_id].call.preview
            await app.on_approval(call_id, approved=True)
            await wait_for_phase(app, Phase.DONE)
            await app.stop()
            return app, preview

        app, preview = asyncio.run(run())
        assert "clipboard" in preview
        kinds = [e["kind"] for e in app.trace.read()]
        assert "approval_asked" in kinds and "approval_decision" in kinds
        results = [e for e in app.trace.read() if e["kind"] == "tool_result"]
        assert results[0]["ok"] is True

    def test_approval_flow_deny_still_continues(self, cfg, ctx):
        async def run():
            app, _ = build_app(cfg, ctx, {"clipboard_set": "confirm"})
            await app.start()
            await app.on_text("copy the qmd search command to my clipboard")
            await wait_for_chip(app)
            call_id = next(iter(app.approvals.pending))
            await app.on_approval(call_id, approved=False)
            await wait_for_phase(app, Phase.DONE)
            await app.stop()
            return app

        app = asyncio.run(run())
        sent = [e for e in app.trace.read() if e["kind"] == "tool_result_sent"]
        assert any(e["ok"] is False for e in sent)
        # Denial still produced a continuation and a clean finish: no hang.
        assert app.machine.phase is Phase.DONE or app.machine.phase is Phase.IDLE

    def test_blocked_tool_feeds_reason_to_model(self, cfg, ctx):
        async def run():
            app, _ = build_app(cfg, ctx)
            await app.start()
            # Force a blocked proposal by injecting a raw adapter event.
            from conn.realtime.base import RtToolCall
            await app.on_text("click the search field")
            await asyncio.sleep(0.05)
            await app._on_rt_event(RtToolCall(call_id="c_blocked",
                                              name="computer_click",
                                              arguments_json='{"selector": "Search"}'))
            await asyncio.sleep(0.05)
            await app.stop()
            return app

        app = asyncio.run(run())
        proposed = [e for e in app.trace.read() if e["kind"] == "tool_proposed"]
        blocked = [p for p in proposed if p["name"] == "computer_click"]
        assert blocked and blocked[0]["gate"] == "blocked"
        assert "tool_disabled_in_v0" in blocked[0]["block_reason"]

    def test_budget_hold_blocks_next_response(self, cfg, ctx):
        async def run():
            cfg.budget.session_cap_usd = 0.000001
            app, messages = build_app(cfg, ctx)
            await app.start()
            await app.on_text("open obsidian")
            # First segment plays; after usage lands the cap is exceeded, so the
            # continuation after the tool result must hold instead of spending.
            await wait_for_phase(app, Phase.BUDGET_HOLD)
            await app.stop()
            return app, messages

        app, messages = asyncio.run(run())
        kinds = [e["kind"] for e in app.trace.read()]
        assert "budget_hold" in kinds
        toasts = [m for m in messages if m["type"] == "toast"]
        assert any("Budget hold" in t["text"] for t in toasts)

    def test_receipt_written_on_stop(self, cfg, ctx):
        async def run():
            app, messages = build_app(cfg, ctx)
            await app.start()
            await app.on_text("open obsidian")
            await wait_for_phase(app, Phase.DONE)
            await app.stop()
            return app, messages

        app, messages = asyncio.run(run())
        receipts = [m for m in messages if m["type"] == "receipt"]
        assert receipts and receipts[0]["receipt"]["turns"] >= 1
        day_dirs = list((app.cfg.data_dir / "receipts").iterdir())
        assert day_dirs and list(day_dirs[0].glob("session_*.json"))


class TestScenarios:
    def test_scenarios_load_and_have_valid_tools(self):
        registry = build_registry()
        scenarios = load_scenarios()
        assert len(scenarios) >= 3
        for sc in scenarios:
            for seg in sc["segments"]:
                for t in seg.get("tools", []):
                    assert t["name"] in registry, f"{sc['id']} uses unknown tool {t['name']}"
                    json.dumps(t.get("arguments", {}))
