"""--cost-report: replays trace files, so old traces without turn_cost work."""

from __future__ import annotations

import json
import sys
from datetime import date

from conn.__main__ import main
from conn.config import PricingCfg
from conn.cost_report import (
    days_report, replay, session_report, trace_paths_for_days,
)

PRICING = PricingCfg()


def usage(text=100, audio=0, cached=0, out_text=10, out_audio=0):
    return {
        "input_token_details": {
            "text_tokens": text, "audio_tokens": audio, "cached_tokens": cached,
            "cached_tokens_details": {"text_tokens": cached, "audio_tokens": 0},
        },
        "output_token_details": {"text_tokens": out_text, "audio_tokens": out_audio},
    }


def session_events(long_utterance=False):
    said = ("please " * 20 + "open the thing") if long_utterance else "open safari"
    return [
        {"ts": 1.0, "kind": "turn_context", "turn_id": "turn_a"},
        {"ts": 2.0, "kind": "ptt_up"},
        {"ts": 2.1, "kind": "response_created", "response_id": "r1", "turn_id": "turn_a"},
        {"ts": 2.5, "kind": "input", "mode": "voice", "text": said},
        {"ts": 2.6, "kind": "tool_proposed", "turn_id": "turn_a"},
        {"ts": 3.0, "kind": "response_done", "usage": usage(text=1000, out_audio=100)},
        {"ts": 3.1, "kind": "response_created", "response_id": "r2", "turn_id": "turn_a"},
        {"ts": 4.0, "kind": "response_done", "usage": usage(text=1000, cached=800, out_audio=50)},
        {"ts": 10.0, "kind": "turn_context", "turn_id": "turn_b"},
        {"ts": 10.1, "kind": "response_created", "response_id": "r3", "turn_id": "turn_b"},
        {"ts": 10.2, "kind": "input", "mode": "voice", "text": "thanks"},
        {"ts": 11.0, "kind": "response_done", "usage": usage(text=500)},
    ]


def write_trace(root, day, name, events):
    folder = root / "traces" / day
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{name}.jsonl"
    path.write_text("".join(json.dumps(e) + "\n" for e in events))
    return path


class TestSessionReport:
    def test_prints_the_headline_numbers(self, tmp_path):
        path = write_trace(tmp_path, "2026-11-12", "session_x", session_events())
        text = session_report(path, PRICING)

        assert "session_x  2026-11-12" in text
        assert "commands              2" in text
        assert "responses             3 (0 cancelled)" in text
        # input = 1000 + 1000 (800 cached, 200 uncached + 800 cached) ... total 2500
        assert "input tokens          2,500  cache hit rate 32.0%" in text
        assert "audio_out" in text and "text_in_uncached" in text

    def test_cost_per_command_stats_match_the_ledger(self, tmp_path):
        path = write_trace(tmp_path, "2026-11-12", "session_x", session_events())
        ledger = replay(path, PRICING)
        costs = sorted(a.usage.usd for a in ledger.accounts.values())
        text = session_report(path, PRICING)

        assert f"max ${costs[-1]:.4f}" in text
        assert f"mean ${sum(costs) / 2:.4f}" in text

    def test_category_shares_sum_to_one_hundred(self, tmp_path):
        path = write_trace(tmp_path, "2026-11-12", "session_x", session_events())
        lines = session_report(path, PRICING).splitlines()
        start = next(i for i, l in enumerate(lines) if l.strip().startswith("category"))
        shares = [float(l.split()[-1].rstrip("%")) for l in lines[start + 1:start + 7]]

        assert abs(sum(shares) - 100.0) < 0.3

    def test_top_commands_are_ranked_and_utterances_truncated(self, tmp_path):
        path = write_trace(tmp_path, "2026-11-12", "session_x",
                           session_events(long_utterance=True))
        text = session_report(path, PRICING)
        top = text.split("five most expensive commands")[1].splitlines()

        assert top[1].lstrip().startswith("#1")  # turn A costs more than B
        said = top[1].split("tools  ")[1]
        assert len(said) == 50 and said.endswith("...")

    def test_top_list_is_capped_at_five(self, tmp_path):
        events = []
        for n in range(8):
            events += [
                {"ts": n * 10 + 1, "kind": "turn_context", "turn_id": f"t{n}"},
                {"ts": n * 10 + 2, "kind": "response_created", "response_id": f"r{n}", "turn_id": f"t{n}"},
                {"ts": n * 10 + 3, "kind": "response_done", "usage": usage(text=100 * (n + 1))},
            ]
        path = write_trace(tmp_path, "2026-11-12", "session_many", events)
        top = session_report(path, PRICING).split("five most expensive commands")[1].splitlines()

        assert len([l for l in top if l.strip()]) == 5

    def test_old_trace_and_new_trace_with_turn_cost_report_identically(self, tmp_path):
        old = write_trace(tmp_path, "2026-11-12", "session_old", session_events())
        with_rows = session_events() + [
            {"ts": 12.0, "kind": "turn_cost", "turn": 1, "turn_id": "turn_a", "total_usd": 9.0},
        ]
        new = write_trace(tmp_path, "2026-11-12", "session_old2", with_rows)

        body = lambda p: session_report(p, PRICING).split("\n", 1)[1]
        assert body(old) == body(new)

    def test_trace_without_billed_responses(self, tmp_path):
        path = write_trace(tmp_path, "2026-11-12", "session_idle",
                           [{"ts": 1.0, "kind": "session_start"}])

        assert "no billed responses" in session_report(path, PRICING)

    def test_cancelled_responses_are_counted_and_billed(self, tmp_path):
        events = [
            {"ts": 1.0, "kind": "turn_context", "turn_id": "turn_a"},
            {"ts": 1.1, "kind": "response_created", "response_id": "r1", "turn_id": "turn_a"},
            {"ts": 2.0, "kind": "turn_context", "turn_id": "turn_b"},
            {"ts": 2.1, "kind": "stale_response_usage", "response_id": "r1", "usage": usage(text=400)},
            {"ts": 3.0, "kind": "response_created", "response_id": "r2", "turn_id": "turn_b"},
            {"ts": 4.0, "kind": "response_done", "usage": usage(text=100)},
        ]
        path = write_trace(tmp_path, "2026-11-12", "session_c", events)

        assert "responses             2 (1 cancelled)" in session_report(path, PRICING)


class TestDaysReport:
    def test_groups_traces_by_day_inside_the_window(self, tmp_path):
        write_trace(tmp_path, "2026-11-12", "session_a", session_events())
        write_trace(tmp_path, "2026-11-11", "session_b", session_events())
        write_trace(tmp_path, "2026-10-01", "session_old", session_events())

        grouped = trace_paths_for_days(tmp_path, 3, today=date(2026, 11, 12))

        assert list(grouped) == ["2026-11-11", "2026-11-12"]

    def test_rollup_lists_each_day_and_a_total_row(self, tmp_path):
        write_trace(tmp_path, "2026-11-12", "session_a", session_events())
        write_trace(tmp_path, "2026-11-12", "session_b", session_events())
        write_trace(tmp_path, "2026-11-11", "session_c", session_events())
        text = days_report(tmp_path, 7, PRICING, today=date(2026, 11, 12))
        rows = {l.split()[0]: l.split() for l in text.splitlines() if l.strip()[:2] in ("20", "al")}

        assert rows["2026-11-12"][1:4] == ["2", "4", "6"]   # sessions, commands, responses
        assert rows["2026-11-11"][1:4] == ["1", "2", "3"]
        assert rows["all"][1:4] == ["3", "6", "9"]

    def test_empty_window(self, tmp_path):
        text = days_report(tmp_path, 7, PRICING, today=date(2026, 11, 12))

        assert "no traces" in text


class TestCli:
    def test_cost_report_path_prints_the_report(self, tmp_path, monkeypatch, capsys):
        path = write_trace(tmp_path, "2026-11-12", "session_cli", session_events())
        monkeypatch.setattr(sys, "argv", ["conn", "--cost-report", str(path)])
        try:
            main()
        except SystemExit as exit_:
            assert exit_.code == 0

        assert "conn cost report  session_cli" in capsys.readouterr().out

    def test_missing_trace_exits_nonzero(self, tmp_path, monkeypatch, capsys):
        monkeypatch.setattr(sys, "argv", ["conn", "--cost-report", str(tmp_path / "nope.jsonl")])
        try:
            main()
        except SystemExit as exit_:
            assert exit_.code == 1

        assert "no such trace" in capsys.readouterr().err

    def test_days_flag_rolls_up_the_data_dir(self, tmp_path, monkeypatch, capsys):
        today = date.today().isoformat()
        write_trace(tmp_path, today, "session_d", session_events())
        monkeypatch.setenv("CONN_DATA_DIR", str(tmp_path))
        monkeypatch.setattr(sys, "argv", ["conn", "--cost-report", "--days", "2"])
        try:
            main()
        except SystemExit as exit_:
            assert exit_.code == 0

        out = capsys.readouterr().out
        assert "last 2 day(s)" in out and today in out

    def test_days_zero_is_an_error_not_a_live_start(self, monkeypatch, capsys):
        # `--days 0` once fell through the flag check and started the billed daemon.
        monkeypatch.setattr(sys, "argv", ["conn", "--days", "0"])
        try:
            main()
            raise AssertionError("main() returned instead of exiting")
        except SystemExit as exit_:
            assert exit_.code == 2

        assert "positive number" in capsys.readouterr().err
