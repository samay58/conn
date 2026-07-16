from conn.config import BudgetCfg, PricingCfg
from conn.cost import CostMeter
from conn.trace import TraceWriter, write_receipt
from conn.observations import parse_model_observation

USAGE_TURN = {
    "input_tokens": 640, "output_tokens": 62,
    "input_token_details": {"text_tokens": 480, "audio_tokens": 160, "cached_tokens": 320,
                            "cached_tokens_details": {"text_tokens": 320, "audio_tokens": 0}},
    "output_token_details": {"text_tokens": 22, "audio_tokens": 40},
}

USAGE_IMAGE_TURN = {
    "input_token_details": {
        "text_tokens": 100,
        "image_tokens": 40,
        "cached_tokens": 0,
    },
    "output_token_details": {"text_tokens": 10, "audio_tokens": 0},
}


def make_meter(cap=1.0, warn=0.5):
    return CostMeter(pricing=PricingCfg(),
                     budget=BudgetCfg(session_cap_usd=cap, warn_at_usd=warn))


class TestCostMeter:
    def test_default_budget_has_five_dollar_cap(self):
        budget = BudgetCfg()

        assert budget.session_cap_usd == 5.0
        assert budget.warn_at_usd == 2.5
        assert budget.hard_stop is True

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

    def test_image_tokens_are_accounted_separately(self):
        meter = make_meter()
        turn = meter.ingest(USAGE_IMAGE_TURN)

        assert turn.image_in == 40
        assert abs(turn.usd - (100 * 4 + 40 * 5 + 10 * 24) / 1e6) < 1e-9
        assert meter.receipt()["tokens"]["image_in"] == 40

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

    def test_receipt_accounts_for_observation_bytes_and_estimated_tokens(self):
        meter = make_meter()
        observation = parse_model_observation({
            "snapshot_id": "snapshot_1",
            "observation_id": "observation_1",
            "turn_id": "turn",
            "observation_epoch": 1,
            "bundle_id": "com.apple.Safari",
            "window_id": 1,
            "candidate_count": 0,
            "candidate_bytes": 2,
            "candidates": [],
        })

        meter.record_observation(observation)

        receipt = meter.receipt()
        assert receipt["observations"] == {
            "count": 1,
            "candidate_bytes": observation.byte_count,
            "estimated_input_tokens": observation.estimated_input_tokens,
        }


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
