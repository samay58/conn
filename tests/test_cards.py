"""Island cards: long answers go on a card, Conn says one sentence.

Builders turn connector results into list or reply cards and give no card
(never an error) for shapes they do not recognise. A send write shows its
full text on a reply card while it waits for approval, and the card settles
honestly: "sent" only on a verified result, "not sent" only when nothing
could have gone out, otherwise "sent, not confirmed"."""

from __future__ import annotations

import json

from conn import cards
from conn.config import Config
from conn.events import Gate, ToolCall
from conn.realtime.fake import FakeRealtimeAdapter
from conn.app import ConnApp
from conn.tools.fake_executors import FAKE_EXECUTORS
from conn.tools.harness import ToolHarness
from conn.tools.registry import RiskLevel, ToolSpec, build_registry


def ok(data: dict) -> str:
    return json.dumps({"ok": True, "data": data, "duration_ms": 5})


PEOPLE = {"items": [
    {"name": "Dana", "channel": "text", "waiting_hours": 5.2, "ask": "Friday dinner?", "tier": "P0"},
    {"name": "Priya", "channel": "email+whatsapp", "waiting_hours": 50, "ask": "Intro to Acme", "tier": "P1"},
], "sources": []}


def test_people_list_card():
    card = cards.build("people", {}, ok({"structured": PEOPLE}))
    assert card["kind"] == "list" and card["title"] == "Waiting on you"
    assert card["subtitle"] == "2 people"
    assert card["rows"][0] == {"title": "Dana", "detail": "Messages · 5h", "note": "Friday dinner?"}
    assert card["rows"][1]["detail"] == "Email + WhatsApp · 2d"
    assert card["persist"] is False


def test_today_skips_done_lines_and_adds_reminders():
    data = {"must": [{"text": "Call the vet", "done": False}, {"text": "Gym", "done": True}],
            "should": [{"text": "Read the memo", "done": False}],
            "reminders_due_today": [{"title": "Pay rent", "due": "2026-11-12 17:00"}]}
    card = cards.build("today", {}, ok({"structured": data}))
    assert [r["title"] for r in card["rows"]] == ["Call the vet", "Read the memo", "Pay rent"]
    assert card["rows"][2]["detail"] == "Reminder 17:00"


def test_calendar_and_thread_cards():
    cal = {"days": [{"date": "2099-01-01", "events": [
        {"start": "09:00", "end": "09:30", "title": "Standup", "location": None}], "open": []}]}
    card = cards.build("calendar", {}, ok({"structured": cal}))
    assert card["rows"][0]["title"] == "Standup" and card["rows"][0]["detail"] == "09:00–09:30"
    thread = {"person": "Sam", "channel": "whatsapp", "messages": [
        {"from": "Sam", "at": "2026-11-10T10:00:00", "text": "Are we on?"},
        {"from": "me", "at": "2026-11-10T10:05:00", "text": "Yes"}]}
    card = cards.build("thread", {}, ok({"structured": thread}))
    assert card["id"] == "thread:sam" and card["subtitle"] == "WhatsApp"
    assert [r["title"] for r in card["rows"]] == ["Sam", "You"]


def test_draft_card_persists_and_text_payload_parses():
    payload = json.dumps({"person": "Dana", "channel": "text", "draft": "Friday works, 7?"})
    card = cards.build("draft", {"person": "Dana"}, ok({"text": payload}))
    assert card["id"] == "reply" and card["state"] == "draft" and card["persist"] is True
    assert card["body"] == "Friday works, 7?" and card["subtitle"] == "Dana · Messages"


def test_unknown_or_failed_results_give_no_card():
    assert cards.build("people", {}, ok({"structured": {"unavailable": "x"}})) is None
    assert cards.build("people", {}, ok({"structured": {"items": "nope"}})) is None
    assert cards.build("people", {}, json.dumps({"ok": False, "error": "x"})) is None
    assert cards.build("people", {}, ok({"withheld": True})) is None
    assert cards.build("people", {}, "not json") is None
    assert cards.build("nope", {}, ok({"structured": PEOPLE})) is None
    assert cards.build("draft", {}, ok({"text": "plain prose, not json"})) is None


def test_send_card_replaces_the_draft_whatever_name_the_model_uses():
    draft = cards.build("draft", {"person": "Dana"}, ok({"structured": {"person": "Dana Reyes", "draft": "Hi"}}))
    send = cards.send_card({"person": "Dana", "text": "Hi"}, "approve")
    assert draft["id"] == send["id"] == "reply"


def test_send_card_shows_the_whole_text():
    long = "Thanks for sending this over. " * 6
    card = cards.send_card({"person": "Dana", "text": long}, "approve")
    assert card["body"] == long.strip() and card["title"] == "Send this?"
    assert cards.send_card({"person": "Dana"}, "approve") is None


def test_send_card_keeps_line_breaks():
    card = cards.send_card({"person": "Dana", "text": "Hi  Dana,\n\n\n\nFriday works.\n7 at the usual place?  "}, "approve")
    assert card["body"] == "Hi Dana,\n\nFriday works.\n7 at the usual place?"


def _app_with_send_tool(tmp_path, ctx):
    cfg = Config()
    cfg.data_dir = tmp_path / "data"
    registry = build_registry()
    noop = lambda args, ctx: {"status": "verified"}
    registry["phoenix_send_text"] = ToolSpec(
        name="phoenix_send_text", description="send", parameters={"type": "object", "properties": {}},
        risk=RiskLevel.ACT_CONFIRM, preview=lambda a: "Text", executor=noop, card="send")
    registry["phoenix_people"] = ToolSpec(
        name="phoenix_people", description="people", parameters={"type": "object", "properties": {}},
        risk=RiskLevel.READ, preview=lambda a: "Checking", executor=noop, card="people")
    harness = ToolHarness(registry, cfg, ctx, executors=FAKE_EXECUTORS)
    app = ConnApp(cfg, FakeRealtimeAdapter(pace_s=0.0), harness)
    messages: list[dict] = []
    app.publisher = messages.append
    return app, messages


def _call(name: str, call_id: str, args: dict) -> ToolCall:
    return ToolCall(call_id=call_id, name=name, arguments=args, gate=Gate.AUTO, preview=name)


def _cards(messages):
    return [m["card"] for m in messages if m.get("type") == "card"]


def test_send_card_settles_from_the_real_result(tmp_path, ctx):
    app, messages = _app_with_send_tool(tmp_path, ctx)
    args = {"person": "Dana", "text": "Friday works, 7?"}
    cases = [
        (ok({"status": "verified"}), "sent"),
        (json.dumps({"ok": False, "error": "denied_by_user"}), "held"),
        (json.dumps({"ok": False, "error": "approval_timeout"}), "held"),
        (json.dumps({"ok": False, "error": "mcp_server_unavailable: phoenix"}), "held"),
        (json.dumps({"ok": False, "error": "mcp_write_not_sent: Nothing was sent."}), "held"),
        (json.dumps({"ok": False, "error": "mcp_write_unknown: no answer"}), "unconfirmed"),
        (json.dumps({"ok": False, "error": "timeout after 22.0s"}), "unconfirmed"),
    ]
    for n, (output, state) in enumerate(cases):
        messages.clear()
        app._show_send_card(_call("phoenix_send_text", f"c{n}", args))
        app._settle_send_card(f"c{n}", output)
        shown = _cards(messages)
        assert [c["state"] for c in shown] == ["approve", state], output
        assert shown[0]["body"] == "Friday works, 7?"
    messages.clear()
    app._settle_send_card("never-asked", ok({}))
    assert _cards(messages) == []


def test_read_result_card_and_no_card_for_native_tools(tmp_path, ctx):
    app, messages = _app_with_send_tool(tmp_path, ctx)
    app._show_result_card(_call("phoenix_people", "p1", {}), ok({"structured": PEOPLE}))
    app._show_result_card(_call("open_app", "p2", {"app": "Notes"}), ok({"structured": PEOPLE}))
    shown = _cards(messages)
    assert len(shown) == 1 and shown[0]["title"] == "Waiting on you"
    trace = app.trace.read()
    shown_events = [e for e in trace if e["kind"] == "card_shown"]
    assert shown_events and "Dana" not in json.dumps(shown_events)
