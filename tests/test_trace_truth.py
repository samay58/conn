"""R0 trace truth: session identity, exact assistant transcripts, PTT
provenance, and receipt counters that distinguish user turns from model
responses and include blocked proposals.
"""

from __future__ import annotations

import asyncio
import hashlib
import json

from conn.app import ConnApp
from conn.realtime.base import (
    RtResponseCreated, RtResponseDone, RtTextDelta, RtToolCall,
    RtTranscriptDelta,
)
from conn.realtime.fake import FakeRealtimeAdapter
from conn.state import Phase
from conn.tools.fake_executors import FAKE_EXECUTORS
from conn.tools.harness import ToolHarness
from conn.tools.registry import build_registry
from conn.trace import TRACE_SCHEMA_VERSION, runtime_identity


def build_app(cfg, ctx):
    cfg.data_dir = ctx.screenshot_dir.parent / "data"
    harness = ToolHarness(build_registry(), cfg, ctx, executors=FAKE_EXECUTORS)
    adapter = FakeRealtimeAdapter(pace_s=0.0)
    app = ConnApp(cfg, adapter, harness)
    app.publisher = lambda msg: None
    return app


def trace_events(app, kind):
    return [e for e in app.trace.read() if e.get("kind") == kind]


async def begin_response(app, response_id: str) -> None:
    """Open a turn and bind one upstream response to it the way live traffic
    does: turn context, response request, then response.created."""
    app._start_turn_context()
    app.machine.phase = Phase.THINKING
    await app._create_response_gated()
    await app._on_rt_event(RtResponseCreated(response_id=response_id))


class TestRuntimeIdentity:
    def test_identity_carries_process_and_schema_fields(self):
        identity = runtime_identity(None)
        assert identity["pid"] > 0
        assert identity["parent_pid"] > 0
        assert identity["trace_schema"] == TRACE_SCHEMA_VERSION
        assert identity["config_fingerprint"] is None

    def test_config_fingerprint_is_sha256_of_file_bytes(self, tmp_path):
        config_path = tmp_path / "config.toml"
        config_path.write_bytes(b"[budget]\nsession_cap_usd = 1.0\n")
        identity = runtime_identity(config_path)
        expected = hashlib.sha256(config_path.read_bytes()).hexdigest()
        assert identity["config_fingerprint"] == expected

    def test_commit_resolves_in_this_repository(self):
        identity = runtime_identity(None)
        commit = identity["commit"]
        assert commit is None or (
            len(commit) == 40 and all(c in "0123456789abcdef" for c in commit)
        )

    def test_session_start_trace_carries_identity(self, cfg, ctx):
        async def run():
            app = build_app(cfg, ctx)
            await app.start()
            await app.stop()
            return trace_events(app, "session_start")

        events = asyncio.run(run())
        assert len(events) == 1
        event = events[0]
        assert event["pid"] > 0
        assert event["parent_pid"] > 0
        assert event["trace_schema"] == TRACE_SCHEMA_VERSION
        assert "commit" in event
        assert "config_fingerprint" in event


class TestModelTranscript:
    def test_full_assistant_transcript_lands_in_trace(self, cfg, ctx):
        async def run():
            app = build_app(cfg, ctx)
            app._loop = asyncio.get_running_loop()
            await app.adapter.connect()
            await begin_response(app, "resp_a")
            await app._on_rt_event(
                RtTranscriptDelta(text="Opening ", response_id="resp_a"))
            await app._on_rt_event(
                RtTranscriptDelta(text="Safari.", response_id="resp_a"))
            await app._on_rt_event(
                RtResponseDone(usage={}, had_tool_calls=False,
                               response_id="resp_a"))
            await app.stop()
            return trace_events(app, "model_transcript")

        events = asyncio.run(run())
        assert len(events) == 1
        assert events[0]["response_id"] == "resp_a"
        assert events[0]["text"] == "Opening Safari."
        assert events[0]["modality"] == "audio"

    def test_text_modality_transcript_recorded(self, cfg, ctx):
        async def run():
            app = build_app(cfg, ctx)
            app._loop = asyncio.get_running_loop()
            await app.adapter.connect()
            await begin_response(app, "resp_b")
            await app._on_rt_event(RtTextDelta(text="Done.", response_id="resp_b"))
            await app._on_rt_event(
                RtResponseDone(usage={}, had_tool_calls=False,
                               response_id="resp_b"))
            await app.stop()
            return trace_events(app, "model_transcript")

        events = asyncio.run(run())
        assert len(events) == 1
        assert events[0]["text"] == "Done."
        assert events[0]["modality"] == "text"

    def test_silent_response_writes_no_transcript_event(self, cfg, ctx):
        async def run():
            app = build_app(cfg, ctx)
            app._loop = asyncio.get_running_loop()
            await app.adapter.connect()
            await begin_response(app, "resp_c")
            await app._on_rt_event(
                RtResponseDone(usage={}, had_tool_calls=False,
                               response_id="resp_c"))
            await app.stop()
            return trace_events(app, "model_transcript")

        assert asyncio.run(run()) == []


class TestPttProvenance:
    def test_ptt_edges_trace_source_and_gesture(self, cfg, ctx):
        async def run():
            app = build_app(cfg, ctx)
            app._loop = asyncio.get_running_loop()
            await app.adapter.connect()
            await app.on_ptt_down(client_ts_ms=100, source="app_hotkey",
                                  gesture_id="g-1")
            await app.on_ptt_up(client_ts_ms=600, source="app_hotkey",
                                gesture_id="g-1")
            await app.stop()
            return app.trace.read()

        events = asyncio.run(run())
        down = [e for e in events if e["kind"] == "ptt_down"][0]
        up = [e for e in events if e["kind"] == "ptt_up"][0]
        assert down["source"] == "app_hotkey"
        assert up["source"] == "app_hotkey"
        assert down["gesture_id"] == "g-1"
        assert up["gesture_id"] == "g-1"


class TestReceiptCounters:
    def test_receipt_separates_responses_proposals_and_blocked(self, cfg, ctx):
        async def run():
            app = build_app(cfg, ctx)
            app._loop = asyncio.get_running_loop()
            await app.adapter.connect()
            await begin_response(app, "resp_r")
            await app._on_rt_event(RtToolCall(
                call_id="c1", name="computer_get_context",
                arguments_json="{}", response_id="resp_r"))
            await app._on_rt_event(RtToolCall(
                call_id="c2", name="computer_hotkey",
                arguments_json=json.dumps({"combo": "cmd+q"}),
                response_id="resp_r"))
            await app._quiesce_tool_tasks()
            receipt = app.cost.receipt()
            await app.stop()
            return receipt

        receipt = asyncio.run(run())
        assert receipt["model_responses"] == 0  # usage not ingested here
        assert receipt["tool_proposals"] == 2
        assert receipt["blocked_proposals"] == 1
        assert receipt["tool_calls"] == 1
        assert "user_turns" in receipt


class TestToolResultArtifacts:
    def test_full_output_lands_in_linked_artifact(self, cfg, ctx):
        from conn.events import Gate, ToolCall
        from pathlib import Path

        async def run():
            app = build_app(cfg, ctx)
            app._loop = asyncio.get_running_loop()
            await app.adapter.connect()
            app._start_turn_context()
            context = app._turn_context
            call = ToolCall(
                call_id="artifact-1", name="phoenix_search",
                arguments={"query": "x" * 900}, gate=Gate.AUTO,
                preview="Search Phoenix", turn_id=context.turn_id,
                response_epoch=context.response_epoch,
                observation_epoch=context.observation_epoch,
                execution_id=1,
            )
            await app._run_tool(call)
            await app.stop()
            return app.trace.read()

        events = asyncio.run(run())
        result = [e for e in events if e["kind"] == "tool_result"][0]
        artifact = result.get("output_artifact")
        assert artifact, "tool_result must link its full output artifact"
        payload = json.loads(Path(artifact).read_text())
        assert payload["call_id"] == "artifact-1"
        assert payload["name"] == "phoenix_search"
        assert isinstance(payload["output"], str) and payload["output"]
        assert len(result["output"]) <= 500

    def test_upstream_call_id_cannot_escape_artifact_directory(
            self, cfg, ctx, tmp_path):
        from conn.events import Gate, ToolCall, ToolFinished
        from pathlib import Path

        app = build_app(cfg, ctx)
        call_ids = ["../../outside-session", str(tmp_path / "absolute")]
        for call_id in call_ids:
            call = ToolCall(
                call_id=call_id, name="phoenix_search", arguments={"query": "x"},
                gate=Gate.AUTO, preview="Search Phoenix",
            )
            artifact = app._write_tool_result_artifact(
                call, ToolFinished(call_id=call_id, ok=True, output="{}"))
            path = Path(artifact).resolve()
            assert path.parent.name == app.session_id
            assert path.is_relative_to(cfg.data_dir.resolve())
            assert json.loads(path.read_text())["call_id"] == call_id

        assert not (tmp_path / "absolute.json").exists()


class TestActionOutcomeCounters:
    def test_receipt_counts_action_outcomes(self, cfg, ctx):
        from conn.events import Gate, ToolCall

        async def run():
            app = build_app(cfg, ctx)
            app._loop = asyncio.get_running_loop()
            await app.adapter.connect()
            app._start_turn_context()
            context = app._turn_context
            call = ToolCall(
                call_id="oc-1", name="app_open",
                arguments={"app": "Obsidian"}, gate=Gate.AUTO,
                preview="Open app: Obsidian", turn_id=context.turn_id,
                response_epoch=context.response_epoch,
                observation_epoch=context.observation_epoch,
                execution_id=1,
            )
            await app._run_tool(call)
            receipt = app.cost.receipt()
            await app.stop()
            return receipt

        receipt = asyncio.run(run())
        outcomes = receipt["action_outcomes"]
        assert sum(outcomes.values()) == 1
        assert set(outcomes) <= {"verified", "dispatch_only", "no_effect",
                                 "blocked", "ambiguous", "failed"}


class TestTranscriptIsolation:
    def test_new_session_never_bleeds_a_partial_transcript(self, cfg, ctx):
        async def run():
            app = build_app(cfg, ctx)
            app._loop = asyncio.get_running_loop()
            await app.adapter.connect()
            await begin_response(app, "resp_old")
            await app._on_rt_event(RtTranscriptDelta(
                text="Deleting all your files", response_id="resp_old"))
            await app.new_session()
            await begin_response(app, "resp_fresh")
            await app._on_rt_event(RtTranscriptDelta(
                text="Opening Safari.", response_id="resp_fresh"))
            await app._on_rt_event(RtResponseDone(
                usage={}, had_tool_calls=False, response_id="resp_fresh"))
            events = trace_events(app, "model_transcript")
            await app.stop()
            return events

        events = asyncio.run(run())
        fresh = [e for e in events if e["response_id"] == "resp_fresh"]
        assert len(fresh) == 1
        assert fresh[0]["text"] == "Opening Safari."


class TestLatencySlicing:
    def test_duplicate_ptt_down_does_not_create_a_false_turn_boundary(self, cfg, ctx):
        from conn.latency import per_turn_spans

        async def run():
            app = build_app(cfg, ctx)
            app._loop = asyncio.get_running_loop()
            await app.adapter.connect()
            await app.on_ptt_down(client_ts_ms=0, source="app_hotkey",
                                  gesture_id="g1")
            # duplicate modifier edge for the same gesture, mid-listening
            await app.on_ptt_down(client_ts_ms=50, source="app_hotkey",
                                  gesture_id="g1")
            await app.on_ui_ack("listening", 80)
            await app.on_ptt_up(client_ts_ms=2000, source="app_hotkey",
                                gesture_id="g1")
            path = app.trace.path
            await app.stop()
            return path

        path = asyncio.run(run())
        turns = per_turn_spans(path)
        assert len(turns) == 1, f"expected one turn, got {len(turns)}"
        assert turns[0]["keydown_to_listening_ms"] == 80
