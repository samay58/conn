"""R0 failure foundry: last-turn report artifact and pipeline-stage
classification. The report is local, sanitized by construction (trace events
already hash text payloads and never carry secrets), and one keypress away.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

from conn.report import classify_failure, last_turn_events


def ev(kind, **payload):
    return {"ts": 0.0, "kind": kind, **payload}


class TestLastTurnEvents:
    def test_slices_from_the_last_turn_context(self):
        events = [
            ev("session_start"),
            ev("turn_context", turn_id="t1"),
            ev("input", mode="voice", text="open safari"),
            ev("turn_context", turn_id="t2"),
            ev("input", mode="voice", text="new tab"),
            ev("tool_proposed", name="app_menu", block_reason="x"),
        ]
        turn = last_turn_events(events)
        assert turn[0]["turn_id"] == "t2"
        assert len(turn) == 3

    def test_no_turn_returns_tail_events(self):
        events = [ev("session_start"), ev("upstream_error", message="boom")]
        assert last_turn_events(events) == events


class TestClassifyFailure:
    def test_upstream_errors_classify_as_transport(self):
        events = [ev("turn_context", turn_id="t"),
                  ev("upstream_error", message="Invalid 'item.id'", fatal=False)]
        assert classify_failure(events) == "turn_or_context_transport"

    def test_silent_accepted_turn_classifies_as_voice_capture(self):
        events = [ev("turn_context", turn_id="t"),
                  ev("ptt_down", source="app_hotkey"),
                  ev("ptt_up", source="app_hotkey"),
                  ev("low_signal", peak_rms=12.0)]
        assert classify_failure(events) == "voice_capture"

    def test_invalid_effect_target_classifies_as_plan_compilation(self):
        events = [ev("turn_context", turn_id="t"),
                  ev("input", mode="voice", text="new tab"),
                  ev("tool_proposed", name="app_menu",
                     block_reason="invalid_effect_target")]
        assert classify_failure(events) == "plan_compilation"

    def test_denied_approval_classifies_as_risk_or_approval(self):
        events = [ev("turn_context", turn_id="t"),
                  ev("input", mode="voice", text="copy this"),
                  ev("approval_decision", call_id="c", approved=False)]
        assert classify_failure(events) == "risk_or_approval"

    def test_ambiguous_target_classifies_as_target_resolution(self):
        events = [ev("turn_context", turn_id="t"),
                  ev("input", mode="voice", text="press save"),
                  ev("tool_result", name="computer_click", ok=False,
                     output='{"outcome": "ambiguous"}')]
        assert classify_failure(events) == "target_resolution"

    def test_no_effect_classifies_as_verification(self):
        events = [ev("turn_context", turn_id="t"),
                  ev("input", mode="voice", text="press save"),
                  ev("tool_result", name="computer_click", ok=False,
                     output='{"outcome": "no_effect"}')]
        assert classify_failure(events) == "verification"

    def test_clean_verified_turn_classifies_as_none(self):
        events = [ev("turn_context", turn_id="t"),
                  ev("input", mode="voice", text="open safari"),
                  ev("tool_result", name="app_open", ok=True,
                     output='{"outcome": "verified"}')]
        assert classify_failure(events) is None


class TestReportEndpoint:
    def test_report_last_command_writes_artifact(self, cfg, ctx):
        from tests.test_trace_truth import build_app

        async def run():
            app = build_app(cfg, ctx)
            app._loop = asyncio.get_running_loop()
            await app.adapter.connect()
            await app.on_ptt_down(client_ts_ms=1, source="app_hotkey",
                                  gesture_id="g-r")
            await app.on_ptt_up(client_ts_ms=900, source="app_hotkey",
                                gesture_id="g-r")
            path = await app.on_report_last_command()
            await app.stop()
            return path

        path = asyncio.run(run())
        assert path is not None
        payload = json.loads(Path(path).read_text())
        assert payload["session_id"]
        assert payload["trace_schema"]
        assert isinstance(payload["events"], list) and payload["events"]
        assert "failure_category" in payload
        assert "CONN_BRIDGE_TOKEN" not in Path(path).read_text()
