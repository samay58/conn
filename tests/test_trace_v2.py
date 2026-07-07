"""Trace schema v2: new event kinds and client-timestamped PttDown/PttUp.

Exercises the trace layer directly (trace.log(kind, **payload)) since the
daemon call sites that emit these kinds land in a later packet.
"""

from __future__ import annotations

import dataclasses

from conn.events import PttDown, PttUp, mono_ms, now_ms
from conn.trace import TraceWriter


def test_ptt_down_serializes_exact_fields(tmp_path):
    t = TraceWriter(tmp_path, "s1")
    t.log("ptt_down", client_ts_ms=123, source="hotkey")
    event = t.read()[0]
    assert set(event.keys()) == {"ts", "kind", "client_ts_ms", "source"}
    assert event["kind"] == "ptt_down"
    assert event["client_ts_ms"] == 123
    assert event["source"] == "hotkey"


def test_ptt_up_serializes_exact_fields_with_none_client_ts(tmp_path):
    t = TraceWriter(tmp_path, "s1")
    t.log("ptt_up", client_ts_ms=None, source="console")
    event = t.read()[0]
    assert set(event.keys()) == {"ts", "kind", "client_ts_ms", "source"}
    assert event["kind"] == "ptt_up"
    assert event["client_ts_ms"] is None
    assert event["source"] == "console"


def test_ptt_source_accepts_panel(tmp_path):
    t = TraceWriter(tmp_path, "s1")
    t.log("ptt_down", client_ts_ms=1, source="panel")
    event = t.read()[0]
    assert event["source"] == "panel"


def test_phase_change_serializes_exact_fields(tmp_path):
    t = TraceWriter(tmp_path, "s1")
    t.log("phase_change", from_phase="idle", to_phase="listening", turn=3)
    event = t.read()[0]
    assert set(event.keys()) == {"ts", "kind", "from_phase", "to_phase", "turn"}
    assert event["kind"] == "phase_change"
    assert event["from_phase"] == "idle"
    assert event["to_phase"] == "listening"
    assert event["turn"] == 3


def test_model_delta_serializes_exact_fields(tmp_path):
    t = TraceWriter(tmp_path, "s1")
    t.log("model_delta", response_id="resp_1", modality="audio")
    event = t.read()[0]
    assert set(event.keys()) == {"ts", "kind", "response_id", "modality"}
    assert event["kind"] == "model_delta"
    assert event["response_id"] == "resp_1"
    assert event["modality"] == "audio"


def test_model_delta_modality_text(tmp_path):
    t = TraceWriter(tmp_path, "s1")
    t.log("model_delta", response_id="resp_2", modality="text")
    event = t.read()[0]
    assert event["modality"] == "text"


def test_audio_silent_serializes_exact_fields(tmp_path):
    t = TraceWriter(tmp_path, "s1")
    t.log("audio_silent", after="flush")
    event = t.read()[0]
    assert set(event.keys()) == {"ts", "kind", "after"}
    assert event["kind"] == "audio_silent"
    assert event["after"] == "flush"


def test_audio_silent_after_drain(tmp_path):
    t = TraceWriter(tmp_path, "s1")
    t.log("audio_silent", after="drain")
    event = t.read()[0]
    assert event["after"] == "drain"


def test_ui_ack_serializes_exact_fields(tmp_path):
    t = TraceWriter(tmp_path, "s1")
    t.log("ui_ack", moment="listening", client_ts_ms=456)
    event = t.read()[0]
    assert set(event.keys()) == {"ts", "kind", "moment", "client_ts_ms"}
    assert event["kind"] == "ui_ack"
    assert event["moment"] == "listening"
    assert event["client_ts_ms"] == 456


def test_ui_ack_moments_thinking_and_chip(tmp_path):
    t = TraceWriter(tmp_path, "s1")
    t.log("ui_ack", moment="thinking", client_ts_ms=1)
    t.log("ui_ack", moment="chip", client_ts_ms=2)
    events = t.read()
    assert [e["moment"] for e in events] == ["thinking", "chip"]


def test_ptt_down_client_ts_ms_defaults_to_none():
    p = PttDown()
    assert p.client_ts_ms is None


def test_ptt_down_client_ts_ms_roundtrips():
    p = PttDown(client_ts_ms=123)
    assert p.client_ts_ms == 123
    d = dataclasses.asdict(p)
    assert PttDown(**d) == p


def test_ptt_up_client_ts_ms_roundtrips():
    p = PttUp(client_ts_ms=789)
    assert p.client_ts_ms == 789
    d = dataclasses.asdict(p)
    assert PttUp(**d) == p


def test_mono_ms_is_monotonic_int():
    a = mono_ms()
    b = mono_ms()
    assert isinstance(a, int)
    assert isinstance(b, int)
    assert b >= a


def test_mono_ms_distinct_from_now_ms():
    # both exist independently as int-returning clocks; now_ms is wall clock,
    # mono_ms is monotonic and used for span math.
    assert isinstance(now_ms(), int)
    assert isinstance(mono_ms(), int)
