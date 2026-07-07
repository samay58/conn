"""Latency span computation over a v2 trace file, per the budget table in
docs/2026-07-05-ux-craft-spec.md. Fixtures are synthetic JSONL trace lines
built directly (matching the exact event shapes app.py emits, per trace.py's
schema v2 docstring) so span math is checked against known values rather
than depending on real wall-clock timing from a live or demo session.
"""

from __future__ import annotations

import asyncio
import json

from conn import evals, latency


def write_trace(tmp_path, events, name="trace.jsonl") -> "Path":
    path = tmp_path / name
    path.write_text("\n".join(json.dumps(e) for e in events) + "\n")
    return path


# One full turn plus a belay (kill switch) at the end, so every v2 kind that
# feeds a span appears at least once. Timestamps chosen so every span comes
# out to a clean number.
FULL_TRACE = [
    {"ts": 1000.000, "kind": "session_start", "session_id": "s1",
     "model": "gpt-realtime-2", "demo": True},
    {"ts": 1000.000, "kind": "ptt_down", "client_ts_ms": 1000, "source": "hotkey"},
    {"ts": 1000.050, "kind": "phase_change", "from_phase": "idle",
     "to_phase": "listening", "turn": 1},
    {"ts": 1000.050, "kind": "ui_ack", "moment": "listening", "client_ts_ms": 1080},
    {"ts": 1000.500, "kind": "ptt_up", "client_ts_ms": 1500, "source": "hotkey"},
    {"ts": 1000.520, "kind": "phase_change", "from_phase": "listening",
     "to_phase": "thinking", "turn": 1},
    {"ts": 1000.550, "kind": "ui_ack", "moment": "thinking", "client_ts_ms": 1560},
    {"ts": 1000.700, "kind": "tool_proposed", "call_id": "call_1",
     "name": "phoenix_search", "gate": "auto", "preview": "Search vault: test",
     "arguments": {"query": "test"}, "block_reason": None},
    {"ts": 1000.760, "kind": "ui_ack", "moment": "chip", "client_ts_ms": 1840},
    {"ts": 1000.800, "kind": "phase_change", "from_phase": "thinking",
     "to_phase": "acting", "turn": 1},
    {"ts": 1000.850, "kind": "tool_exec", "call_id": "call_1", "name": "phoenix_search"},
    {"ts": 1000.900, "kind": "model_delta", "response_id": "response_1", "modality": "text"},
    {"ts": 1000.950, "kind": "phase_change", "from_phase": "acting",
     "to_phase": "speaking", "turn": 1},
    {"ts": 1001.100, "kind": "audio_silent", "after": "drain"},
    {"ts": 1001.150, "kind": "phase_change", "from_phase": "speaking",
     "to_phase": "done", "turn": 1},
    {"ts": 1002.000, "kind": "kill_switch", "client_ts_ms": 6000},
    {"ts": 1002.130, "kind": "audio_silent", "after": "flush"},
]

EXPECTED_FULL = {
    "keydown_to_listening_ms": 80,
    "release_to_ack_ms": 60,
    "release_to_first_token_ms": 400.0,
    "release_to_first_tool_ms": 350.0,
    "proposal_to_chip_ms": 60.0,
    "stop_to_silence_ms": 130.0,
}


class TestSpans:
    def test_all_six_spans_compute_from_full_v2_trace(self, tmp_path):
        path = write_trace(tmp_path, FULL_TRACE)
        assert latency.spans(path) == EXPECTED_FULL

    def test_stop_to_silence_uses_the_flush_audio_silent_not_the_drain_one(self, tmp_path):
        # FULL_TRACE has an earlier audio_silent(after=drain) from the natural
        # end of the turn, before the belay's audio_silent(after=flush). If
        # spans() grabbed the first audio_silent regardless of `after`, this
        # span would come out wrong (or negative).
        path = write_trace(tmp_path, FULL_TRACE)
        assert latency.spans(path)["stop_to_silence_ms"] == 130.0

    def test_missing_kinds_yield_none_not_crash(self, tmp_path):
        sparse = [
            {"ts": 1000.0, "kind": "session_start", "session_id": "s1",
             "model": "gpt-realtime-2", "demo": True},
            {"ts": 1000.0, "kind": "ptt_down", "client_ts_ms": 1000, "source": "hotkey"},
        ]
        path = write_trace(tmp_path, sparse)
        result = latency.spans(path)
        assert set(result) == set(EXPECTED_FULL)
        assert all(v is None for v in result.values())

    def test_partial_trace_computes_only_the_spans_it_can(self, tmp_path):
        partial = [
            {"ts": 1000.0, "kind": "ptt_down", "client_ts_ms": 1000, "source": "hotkey"},
            {"ts": 1000.05, "kind": "ui_ack", "moment": "listening", "client_ts_ms": 1075},
        ]
        path = write_trace(tmp_path, partial)
        result = latency.spans(path)
        assert result["keydown_to_listening_ms"] == 75
        assert result["release_to_ack_ms"] is None
        assert result["release_to_first_token_ms"] is None
        assert result["release_to_first_tool_ms"] is None
        assert result["proposal_to_chip_ms"] is None
        assert result["stop_to_silence_ms"] is None

    def test_empty_trace_file_returns_all_none(self, tmp_path):
        path = tmp_path / "empty.jsonl"
        path.write_text("")
        result = latency.spans(path)
        assert set(result) == set(EXPECTED_FULL)
        assert all(v is None for v in result.values())

    def test_nonexistent_trace_path_returns_all_none_not_crash(self, tmp_path):
        result = latency.spans(tmp_path / "does-not-exist.jsonl")
        assert all(v is None for v in result.values())

    def test_blank_lines_in_trace_are_skipped(self, tmp_path):
        path = tmp_path / "blanks.jsonl"
        lines = [json.dumps(e) for e in FULL_TRACE]
        path.write_text("\n\n".join(lines) + "\n\n")
        assert latency.spans(path) == EXPECTED_FULL


class TestBudgetStatus:
    def test_pass_when_under_budget(self):
        assert latency.budget_status("keydown_to_listening_ms", 80) == "pass"

    def test_fail_when_over_budget(self):
        assert latency.budget_status("keydown_to_listening_ms", 150) == "fail"

    def test_pass_at_exact_budget_boundary(self):
        assert latency.budget_status("release_to_ack_ms", 90) == "pass"

    def test_n_a_when_span_is_none(self):
        assert latency.budget_status("proposal_to_chip_ms", None) == "n/a"

    def test_two_threshold_span_checks_against_p50(self):
        assert latency.budget_status("release_to_first_token_ms", 1000) == "fail"
        assert latency.budget_status("release_to_first_token_ms", 800) == "pass"


class TestFormatReport:
    def test_report_lists_all_six_span_names(self):
        report = latency.format_report(EXPECTED_FULL)
        for name in EXPECTED_FULL:
            assert name in report

    def test_report_marks_pass_and_fail(self):
        values = dict(EXPECTED_FULL)
        values["keydown_to_listening_ms"] = 250  # over the 100ms budget
        report = latency.format_report(values)
        lines = {line.split()[0]: line for line in report.splitlines() if line.strip()}
        assert "FAIL" in lines["keydown_to_listening_ms"].upper()
        assert "PASS" in lines["release_to_ack_ms"].upper()

    def test_report_shows_n_a_for_missing_spans(self, tmp_path):
        path = tmp_path / "empty.jsonl"
        path.write_text("")
        report = latency.format_report(latency.spans(path))
        assert "n/a" in report.lower()


class TestCliWiring:
    def test_main_latency_report_flag_prints_spans(self, tmp_path, capsys, monkeypatch):
        from conn import __main__ as conn_main

        path = write_trace(tmp_path, FULL_TRACE)
        monkeypatch.setattr("sys.argv", ["conn", "--latency-report", str(path)])
        conn_main.main()
        out = capsys.readouterr().out
        for name in EXPECTED_FULL:
            assert name in out


class TestEvalTraceKindsAssertion:
    def test_eval_case_passes_when_expected_trace_kinds_present(self, cfg, tmp_path):
        cfg.data_dir = tmp_path / "data"
        case = {
            "id": "trace-kinds-present",
            "input": "open obsidian",
            "expect": {
                "tools": ["app_open"],
                "gates": {"app_open": "auto"},
                "end_phase": ["done", "idle"],
                "approvals_asked": 0,
                "trace_kinds": ["phase_change", "model_delta", "audio_silent"],
            },
        }
        result = asyncio.run(evals._run_case(case, cfg))
        assert result["passed"], result["failures"]

    def test_eval_case_fails_when_expected_trace_kind_missing(self, cfg, tmp_path):
        cfg.data_dir = tmp_path / "data"
        case = {
            "id": "trace-kinds-missing",
            "input": "open obsidian",
            "expect": {
                "tools": ["app_open"],
                "gates": {"app_open": "auto"},
                "end_phase": ["done", "idle"],
                "approvals_asked": 0,
                # ptt_down never fires on the text-driven eval path.
                "trace_kinds": ["phase_change", "ptt_down"],
            },
        }
        result = asyncio.run(evals._run_case(case, cfg))
        assert not result["passed"]
        assert any("ptt_down" in f for f in result["failures"])


class TestTasksJsonCase:
    def test_tasks_json_has_a_trace_kinds_eval_case(self):
        spec = json.loads(evals.EVAL_TASKS.read_text())
        cases = spec["cases"]
        assert len(cases) == 7
        with_trace_kinds = [c for c in cases if "trace_kinds" in c.get("expect", {})]
        assert len(with_trace_kinds) == 1
        assert with_trace_kinds[0]["expect"]["trace_kinds"]
