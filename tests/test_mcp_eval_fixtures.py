"""The connector tools in the live intent eval come from neutral fixtures
through register_mcp_tools with a fake manager. No server is ever started."""

from __future__ import annotations

import json
from pathlib import Path

from conn import intent_eval
from conn.tools.risk import RiskLevel

EXPECTED_EXPORTS = {
    "phoenix_today", "phoenix_calendar", "phoenix_people", "phoenix_thread",
    "phoenix_lookup", "phoenix_capture", "phoenix_remind", "phoenix_strike",
    "granola_search_meetings", "granola_search_transcripts",
    "wispr_search_meetings", "wispr_get_meeting",
    "superhuman_search_threads", "superhuman_get_thread",
}
WRITES = {"phoenix_capture", "phoenix_remind", "phoenix_strike"}
CORPUS = Path(__file__).resolve().parents[1] / "evals" / "intent_corpus.json"


def test_fixtures_export_the_fourteen_tools():
    registry = intent_eval.eval_registry()
    assert set(intent_eval.fixture_exported_names()) == EXPECTED_EXPORTS
    assert EXPECTED_EXPORTS <= set(registry)
    assert len(intent_eval.fixture_exported_names()) == 14


def test_writes_confirm_and_are_never_canned_reads():
    registry = intent_eval.eval_registry()
    for name in WRITES:
        assert registry[name].risk is RiskLevel.ACT_CONFIRM
        assert name not in intent_eval._READ_TOOLS
    for name in EXPECTED_EXPORTS - WRITES:
        assert registry[name].risk is RiskLevel.READ
        assert name in intent_eval._READ_TOOLS
        envelope = intent_eval.canned_read(name, "com.apple.Safari")
        assert envelope["ok"] is True and envelope["data"]["text"]


def test_existing_canned_reads_are_unchanged():
    assert intent_eval.canned_read("shortcuts_list", "com.apple.Safari")["data"]["count"] == 5
    assert intent_eval.canned_read(
        "computer_get_context", "com.apple.Notes")["data"]["app"] == "Notes"


def test_corpus_tool_names_exist_among_exported_tools():
    exported = set(intent_eval.eval_registry())
    items = json.loads(CORPUS.read_text())["items"]
    assert len(items) >= 232 + 30
    for item in items:
        for name in item.get("expect", {}).get("tool_any", []):
            assert name in exported, (item["utterance"], name)


def test_refusal_items_allow_no_tool_and_name_no_write_tool():
    items = {i["utterance"]: i for i in json.loads(CORPUS.read_text())["items"]}
    for utterance in ("Move my 3pm to tomorrow.", "Send Dana a text saying I'm running late.",
                      "Remind me to call Dana."):
        expect = items[utterance]["expect"]
        assert expect["allow_no_tool"] is True
        assert not set(expect.get("tool_any", [])) & WRITES


def test_eval_context_pins_a_fixed_local_time():
    assert "local_time=2026-11-11 10:00 Wed." in intent_eval.context_item("com.apple.Safari")


def test_fixtures_hold_only_neutral_sample_names():
    text = (Path(__file__).resolve().parents[1] / "evals" / "mcp_fixture_tools.json").read_text()
    assert "@" not in text
