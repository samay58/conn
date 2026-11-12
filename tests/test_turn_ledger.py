"""Per-command accounting: every billed response lands on the user command that
caused it, turn_cost is emitted when the turn ends, and the ledger's dollars
equal what the session meter charged."""

from __future__ import annotations

import json

from conn.config import PricingCfg
from conn.cost import CostMeter, price_usage
from conn.config import BudgetCfg
from conn.trace import TraceWriter
from conn.turn_ledger import TurnLedger

PRICING = PricingCfg()


def usage(text=100, audio=0, cached=0, out_text=10, out_audio=0):
    return {
        "input_tokens": text + audio,
        "input_token_details": {
            "text_tokens": text, "audio_tokens": audio, "cached_tokens": cached,
            "cached_tokens_details": {"text_tokens": cached, "audio_tokens": 0},
        },
        "output_token_details": {"text_tokens": out_text, "audio_tokens": out_audio},
    }


def ev(kind, ts=0.0, **fields):
    return {"kind": kind, "ts": ts, **fields}


def feed(ledger, events):
    for e in events:
        ledger.observe(e)


def two_turn_session():
    """Turn A: two responses and a tool. Turn B: one response."""
    return [
        ev("turn_context", 1.0, turn_id="turn_a"),
        ev("ptt_up", 2.0),
        ev("response_created", 2.1, response_id="r1", turn_id="turn_a"),
        ev("model_delta", 2.6, modality="audio"),
        ev("input", 2.7, mode="voice", text="open safari"),
        ev("tool_proposed", 3.0, turn_id="turn_a", name="app_open"),
        ev("response_done", 3.1, usage=usage(text=1000, audio=50, out_audio=40)),
        ev("response_created", 3.2, response_id="r2", turn_id="turn_a"),
        ev("response_done", 4.0, usage=usage(text=1100, audio=50, cached=800, out_audio=20)),
        ev("turn_context", 10.0, turn_id="turn_b"),
        ev("ptt_up", 11.0),
        ev("response_created", 11.1, response_id="r3", turn_id="turn_b"),
        ev("input", 11.5, mode="voice", text="thanks"),
        ev("response_done", 12.0, usage=usage(text=1200, audio=70, cached=900)),
    ]


class TestAttribution:
    def test_responses_and_tools_land_on_their_turn(self):
        ledger = TurnLedger(PRICING)
        feed(ledger, two_turn_session())
        a, b = ledger.accounts["turn_a"], ledger.accounts["turn_b"]

        assert (a.turn_no, a.responses, a.tools) == (1, 2, 1)
        assert (b.turn_no, b.responses, b.tools) == (2, 1, 0)

    def test_dollars_equal_the_meter_total(self):
        ledger = TurnLedger(PRICING)
        events = two_turn_session()
        feed(ledger, events)
        meter = CostMeter(pricing=PRICING, budget=BudgetCfg())
        for e in events:
            if e["kind"] == "response_done":
                meter.ingest(e["usage"])

        assert abs(ledger.category_totals()["total_usd"] - meter.spent_usd) < 1e-6

    def test_voice_utterance_is_attached_to_the_turn(self):
        ledger = TurnLedger(PRICING)
        feed(ledger, two_turn_session())

        assert ledger.accounts["turn_a"].utterance == "open safari"
        assert ledger.accounts["turn_b"].utterance == "thanks"

    def test_typed_input_before_the_response_still_attaches(self):
        ledger = TurnLedger(PRICING)
        feed(ledger, [
            ev("turn_context", 1.0, turn_id="turn_t"),
            ev("input", 1.1, mode="text", text="hello there"),
            ev("response_created", 1.2, response_id="r1", turn_id="turn_t"),
            ev("response_done", 2.0, usage=usage()),
        ])

        assert ledger.accounts["turn_t"].utterance == "hello there"

    def test_a_tap_turn_with_no_response_creates_no_account(self):
        ledger = TurnLedger(PRICING)
        feed(ledger, [ev("turn_context", 1.0, turn_id="turn_tap"), ev("ptt_up", 1.1)])

        assert ledger.accounts == {}

    def test_cancelled_usage_is_billed_to_the_cancelled_responses_turn(self):
        ledger = TurnLedger(PRICING)
        feed(ledger, [
            ev("turn_context", 1.0, turn_id="turn_a"),
            ev("response_created", 1.1, response_id="r1", turn_id="turn_a"),
            ev("turn_context", 2.0, turn_id="turn_b"),  # barge-in
            ev("stale_response_usage", 2.1, response_id="r1", usage=usage(text=500)),
            ev("response_created", 3.0, response_id="r2", turn_id="turn_b"),
            ev("response_done", 3.5, usage=usage(text=700)),
        ])

        a, b = ledger.accounts["turn_a"], ledger.accounts["turn_b"]
        assert (a.responses, a.cancelled) == (1, 1)
        assert (b.responses, b.cancelled) == (1, 0)
        assert a.usage.text_in == 500 and b.usage.text_in == 700

    def test_response_done_without_id_takes_the_latest_unresolved_response(self):
        ledger = TurnLedger(PRICING)
        feed(ledger, [
            ev("response_created", 1.0, response_id="r1", turn_id="turn_a"),
            # r1 is cancelled with no usage row; r2 is the one that finishes.
            ev("response_created", 2.0, response_id="r2", turn_id="turn_b"),
            ev("response_done", 3.0, usage=usage(text=300)),
        ])

        assert ledger.accounts["turn_b"].usage.text_in == 300
        assert ledger.accounts["turn_a"].responses == 0

    def test_response_done_with_id_matches_exactly(self):
        ledger = TurnLedger(PRICING)
        feed(ledger, [
            ev("response_created", 1.0, response_id="r1", turn_id="turn_a"),
            ev("response_created", 2.0, response_id="r2", turn_id="turn_b"),
            ev("response_done", 3.0, response_id="r1", usage=usage(text=300)),
        ])

        assert ledger.accounts["turn_a"].usage.text_in == 300

    def test_usage_for_an_unseen_response_is_kept_not_dropped(self):
        ledger = TurnLedger(PRICING)
        feed(ledger, [ev("response_done", 1.0, usage=usage(text=300))])

        assert ledger.category_totals()["tokens"]["text_in_uncached"] == 300

    def test_empty_usage_is_ignored(self):
        ledger = TurnLedger(PRICING)
        feed(ledger, [
            ev("response_created", 1.0, response_id="r1", turn_id="turn_a"),
            ev("response_done", 2.0, usage={}),
        ])

        assert ledger.accounts["turn_a"].responses == 0


class TestFirstAudioSpan:
    def test_release_to_first_audio_ms(self):
        ledger = TurnLedger(PRICING)
        feed(ledger, two_turn_session())

        assert ledger.accounts["turn_a"].release_to_first_audio_ms == 600.0

    def test_text_modality_delta_does_not_count_as_audio(self):
        ledger = TurnLedger(PRICING)
        feed(ledger, [
            ev("turn_context", 1.0, turn_id="turn_a"),
            ev("ptt_up", 2.0),
            ev("response_created", 2.1, response_id="r1", turn_id="turn_a"),
            ev("model_delta", 2.5, modality="text"),
        ])

        assert ledger.accounts["turn_a"].release_to_first_audio_ms is None

    def test_no_release_means_no_span(self):
        ledger = TurnLedger(PRICING)
        feed(ledger, [
            ev("turn_context", 1.0, turn_id="turn_t"),
            ev("response_created", 1.1, response_id="r1", turn_id="turn_t"),
            ev("model_delta", 1.5, modality="audio"),
        ])

        assert ledger.accounts["turn_t"].release_to_first_audio_ms is None

    def test_only_the_first_release_counts(self):
        ledger = TurnLedger(PRICING)
        feed(ledger, [
            ev("turn_context", 1.0, turn_id="turn_a"),
            ev("ptt_up", 2.0),
            ev("ptt_up", 5.0),  # a second edge in the same turn
            ev("response_created", 5.1, response_id="r1", turn_id="turn_a"),
            ev("model_delta", 5.5, modality="audio"),
        ])

        assert ledger.accounts["turn_a"].release_to_first_audio_ms == 3500.0


class TestEmission:
    def test_turn_cost_is_emitted_when_the_next_turn_starts_billing(self):
        emitted = []
        ledger = TurnLedger(PRICING, emit=lambda kind, **p: emitted.append((kind, p)))
        events = two_turn_session()
        feed(ledger, events[:9])  # turn A only, both responses done
        assert emitted == []

        feed(ledger, events[9:12])  # turn B creates its first response
        assert [k for k, _ in emitted] == ["turn_cost"]
        payload = emitted[0][1]
        assert payload["turn"] == 1
        assert payload["responses"] == 2
        assert payload["tool_count"] == 1
        assert payload["utterance_chars"] == len("open safari")
        assert payload["release_to_first_audio_ms"] == 600.0

    def test_flush_closes_the_last_turn_once(self):
        emitted = []
        ledger = TurnLedger(PRICING, emit=lambda kind, **p: emitted.append(p))
        feed(ledger, two_turn_session())
        ledger.flush()
        ledger.flush()

        assert [p["turn"] for p in emitted] == [1, 2]

    def test_payload_has_lengths_not_text(self):
        emitted = []
        ledger = TurnLedger(PRICING, emit=lambda kind, **p: emitted.append(p))
        feed(ledger, two_turn_session())
        ledger.flush()

        assert "open safari" not in json.dumps(emitted)
        assert "utterance" not in emitted[0]

    def test_payload_categories_and_total(self):
        emitted = []
        ledger = TurnLedger(PRICING, emit=lambda kind, **p: emitted.append(p))
        feed(ledger, two_turn_session())
        ledger.flush()
        a = emitted[0]

        assert set(a["tokens"]) == {
            "text_in_uncached", "cached_in", "audio_in_uncached",
            "audio_out", "text_out", "image_in"}
        assert set(a["usd"]) == set(a["tokens"])
        assert abs(sum(a["usd"].values()) - a["total_usd"]) < 1e-5
        assert a["tokens"]["cached_in"] == 800
        assert a["tokens"]["audio_out"] == 60

    def test_late_usage_on_a_closed_turn_re_emits_with_a_revision(self):
        emitted = []
        ledger = TurnLedger(PRICING, emit=lambda kind, **p: emitted.append(p))
        feed(ledger, [
            ev("response_created", 1.0, response_id="r1", turn_id="turn_a"),
            ev("response_created", 2.0, response_id="r2", turn_id="turn_b"),  # closes A
            ev("stale_response_usage", 3.0, response_id="r1", usage=usage(text=400)),
        ])

        assert [p["turn"] for p in emitted] == [1, 1]
        assert emitted[-1]["revision"] == 1
        assert emitted[-1]["tokens"]["text_in_uncached"] == 400

    def test_turn_cost_rows_in_a_trace_are_not_double_counted(self):
        ledger = TurnLedger(PRICING)
        feed(ledger, two_turn_session())
        before = ledger.category_totals()
        ledger.observe(ev("turn_cost", 99.0, turn=1, turn_id="turn_a", total_usd=9.9))

        assert ledger.category_totals() == before


class TestViews:
    def test_snapshot_is_ordered_and_json_safe(self):
        ledger = TurnLedger(PRICING)
        feed(ledger, two_turn_session())
        snapshot = ledger.snapshot()

        assert [t["turn"] for t in snapshot] == [1, 2]
        json.dumps(snapshot)

    def test_category_totals_sum_the_turns(self):
        ledger = TurnLedger(PRICING)
        feed(ledger, two_turn_session())
        totals = ledger.category_totals()

        assert totals["tokens"]["text_in_uncached"] == 1000 + 300 + 300
        assert totals["tokens"]["cached_in"] == 800 + 900
        expected = sum(price_usage(e["usage"], PRICING).usd
                       for e in two_turn_session() if e["kind"] == "response_done")
        assert abs(totals["total_usd"] - expected) < 1e-5


class TestAttach:
    def test_attach_writes_turn_cost_to_the_trace_file(self, tmp_path):
        trace = TraceWriter(tmp_path, "session_t")
        ledger = TurnLedger(PRICING)
        ledger.attach(trace)
        trace.log("turn_context", turn_id="turn_a")
        trace.log("ptt_up")
        trace.log("response_created", response_id="r1", turn_id="turn_a")
        trace.log("response_done", usage=usage(text=250), turn_usd=0.001, spent_usd=0.001)
        ledger.flush()

        rows = [r for r in trace.read() if r["kind"] == "turn_cost"]
        assert len(rows) == 1
        assert rows[0]["tokens"]["text_in_uncached"] == 250

    def test_a_malformed_event_never_raises_into_the_trace(self, tmp_path):
        trace = TraceWriter(tmp_path, "session_t")
        ledger = TurnLedger(PRICING)
        ledger.attach(trace)
        trace.log("response_created", response_id="r1", turn_id="turn_a")
        trace.log("response_done", usage={"input_token_details": "not-a-dict"})

        assert ledger.errors == 1
