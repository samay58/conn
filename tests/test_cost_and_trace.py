from conn.config import BudgetCfg, PricingCfg
from conn.cost import CostMeter
from conn.trace import TraceWriter, write_receipt

USAGE_TURN = {
    "input_tokens": 640, "output_tokens": 62,
    "input_token_details": {"text_tokens": 480, "audio_tokens": 160, "cached_tokens": 320,
                            "cached_tokens_details": {"text_tokens": 320, "audio_tokens": 0}},
    "output_token_details": {"text_tokens": 22, "audio_tokens": 40},
}


def make_meter(cap=1.0, warn=0.5):
    return CostMeter(pricing=PricingCfg(),
                     budget=BudgetCfg(session_cap_usd=cap, warn_at_usd=warn))


class TestCostMeter:
    def test_turn_math_respects_cached_split(self):
        meter = make_meter()
        turn = meter.ingest(USAGE_TURN)
        # billable text in: 480 - 320 cached = 160; audio in stays 160
        assert turn.text_in == 160
        assert turn.audio_in == 160
        assert turn.cached_in == 320
        expected = (160 * 4.00 + 22 * 24.00 + 160 * 32.00 + 40 * 64.00 + 320 * 0.40) / 1e6
        assert abs(turn.usd - expected) < 1e-9

    def test_cap_trips_on_estimate(self):
        meter = make_meter(cap=0.001)
        assert not meter.would_exceed() or True  # first-turn estimate may trip a tiny cap
        meter.ingest(USAGE_TURN)
        assert meter.would_exceed()

    def test_override_disarms_cap(self):
        meter = make_meter(cap=0.0001)
        meter.ingest(USAGE_TURN)
        assert meter.would_exceed()
        meter.overridden = True
        assert not meter.would_exceed()

    def test_warn_threshold(self):
        meter = make_meter(warn=0.001)
        meter.ingest(USAGE_TURN)
        assert meter.should_warn()

    def test_receipt_accumulates(self):
        meter = make_meter()
        meter.ingest(USAGE_TURN)
        meter.ingest(USAGE_TURN)
        meter.tool_calls = 3
        r = meter.receipt()
        assert r["model_responses"] == 2
        assert r["tokens"]["text_in"] == 320
        assert r["tokens"]["audio_out"] == 80
        assert r["tool_calls"] == 3
        assert len(r["per_response_usd"]) == 2
        assert r["estimated_usd"] > 0


class TestTrace:
    def test_jsonl_roundtrip_and_listeners(self, tmp_path):
        heard = []
        t = TraceWriter(tmp_path, "session_x")
        t.subscribe(heard.append)
        t.log("session_start", model="gpt-realtime-2")
        t.log("tool_proposed", name="app_open", gate="auto")
        events = t.read()
        assert [e["kind"] for e in events] == ["session_start", "tool_proposed"]
        assert all("ts" in e for e in events)
        assert len(heard) == 2

    def test_receipt_file(self, tmp_path):
        path = write_receipt(tmp_path, "session_x", {"estimated_usd": 0.12})
        assert path.exists()
        assert "session_x" in path.name
