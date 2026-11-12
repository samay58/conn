"""Cards: the island's detail surface for answers too long to speak.

Conn says one short sentence; the rows, the draft or the full text of a
message about to go out sit on a card. A tool opts in by naming a template
(`card = "people"` on an MCP tool in config). Builders are pure and
defensive: a result in a shape they do not recognise gives no card, never an
error, because a card is a convenience and the spoken answer still stands.

Cards go to the signed app only. They are not traced: a draft or a thread is
message content, and traces keep lengths and outcomes, not bodies.

Wire shape, published as {"type": "card", "card": {...}}:
  id        stable per subject, so a revision replaces the card in place
            (the one "reply" card moves from draft to approve to sent)
  kind      "list" or "reply"
  title     one line
  subtitle  optional second line (recipient and channel, a count)
  rows      list of {"title", "detail", "note"} for list cards
  body      the full message text for reply cards
  state     reply cards: "draft", "approve", "sent", "unconfirmed", "held"
  persist   true keeps the card until it is replaced, sent or dismissed;
            false lets the island retire it on the next push-to-talk
{"type": "card_clear"} removes every card, e.g. at session reset.
"""

from __future__ import annotations

import json
import re
from datetime import date, datetime
from typing import Any, Callable

TEMPLATES = ("people", "today", "calendar", "thread", "draft", "send")
MAX_ROWS = 8
_TEXT_CAP = 280
_BODY_CAP = 2000

Builder = Callable[[dict, dict], "dict | None"]


def _s(value: Any, cap: int = _TEXT_CAP) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    return text if len(text) <= cap else text[: cap - 1].rstrip() + "…"


def _body(value: Any) -> str:
    """A message body: line breaks kept, since the card shows the text that goes out."""
    lines = [re.sub(r"[^\S\n]+", " ", line).strip() for line in str(value or "").strip().splitlines()]
    text = re.sub(r"\n{3,}", "\n\n", "\n".join(lines))
    return text if len(text) <= _BODY_CAP else text[: _BODY_CAP - 1].rstrip() + "…"


def _row(title: Any, detail: Any = "", note: Any = "") -> dict:
    return {"title": _s(title, 80), "detail": _s(detail, 60), "note": _s(note)}


def _slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.casefold()).strip("-") or "someone"


def _waited(hours: Any) -> str:
    try:
        h = float(hours)
    except (TypeError, ValueError):
        return ""
    if h < 1:
        return "just now"
    if h < 24:
        return f"{int(h)}h"
    return f"{int(h // 24)}d"


_CHANNEL = {"text": "Messages", "whatsapp": "WhatsApp", "email": "Email"}


def _channel(value: Any) -> str:
    parts = [p for p in str(value or "").split("+") if p]
    return " + ".join(_CHANNEL.get(p, p.title()) for p in parts)


def _people(data: dict, args: dict) -> dict | None:
    items = data.get("items")
    if not isinstance(items, list) or not items:
        return None
    rows = [_row(i.get("name"), " · ".join(x for x in (_channel(i.get("channel")),
                                                        _waited(i.get("waiting_hours"))) if x),
                 i.get("ask"))
            for i in items[:MAX_ROWS] if isinstance(i, dict) and i.get("name")]
    if not rows:
        return None
    n = len(items)
    return {"id": "list:people", "kind": "list", "title": "Waiting on you",
            "subtitle": f"{n} {'person' if n == 1 else 'people'}", "rows": rows, "persist": False}


def _today(data: dict, args: dict) -> dict | None:
    rows: list[dict] = []
    for section, label in (("must", "Must do"), ("should", "Should do")):
        for item in data.get(section) or []:
            if isinstance(item, dict) and item.get("text") and not item.get("done"):
                rows.append(_row(item["text"], label))
    for r in data.get("reminders_due_today") or []:
        if isinstance(r, dict) and r.get("title"):
            due = str(r.get("due") or "")
            rows.append(_row(r["title"], f"Reminder {due[11:16]}".strip()))
    if not rows:
        return None
    return {"id": "list:today", "kind": "list", "title": "Today",
            "subtitle": f"{len(rows)} open", "rows": rows[:MAX_ROWS], "persist": False}


def _day_label(iso: str) -> str:
    try:
        d = date.fromisoformat(iso)
    except ValueError:
        return iso
    delta = (d - date.today()).days
    if delta == 0:
        return "Today"
    if delta == 1:
        return "Tomorrow"
    return d.strftime("%a %b %-d")


def _calendar(data: dict, args: dict) -> dict | None:
    days = data.get("days")
    if not isinstance(days, list):
        return None
    rows: list[dict] = []
    for day in days:
        if not isinstance(day, dict):
            continue
        label = _day_label(str(day.get("date") or ""))
        for e in day.get("events") or []:
            if not isinstance(e, dict):
                continue
            when = "All day" if e.get("start") == "all-day" else "–".join(
                x for x in (e.get("start"), e.get("end")) if x)
            rows.append(_row(e.get("title") or "Busy",
                             f"{label} {when}" if len(days) > 1 else when, e.get("location")))
    if not rows:
        free = [s for d in days if isinstance(d, dict) for s in d.get("open") or []]
        if not free:
            return None
        rows = [_row("Open", "–".join(x for x in (s.get("start"), s.get("end")) if x))
                for s in free if isinstance(s, dict)]
    first = days[0].get("date", "") if days and isinstance(days[0], dict) else ""
    title = _day_label(str(first)) if len(days) == 1 else "Calendar"
    return {"id": "list:calendar", "kind": "list", "title": title,
            "subtitle": f"{len(rows)} {'event' if len(rows) == 1 else 'events'}",
            "rows": rows[:MAX_ROWS], "persist": False}


def _short_time(at: str) -> str:
    try:
        moment = datetime.fromisoformat(at.replace("Z", "+00:00"))
    except ValueError:
        return ""
    if moment.tzinfo is not None:
        moment = moment.astimezone()
    return moment.strftime("%-I:%M %p") if moment.date() == date.today() else moment.strftime("%a %-I:%M %p")


def _thread(data: dict, args: dict) -> dict | None:
    person = data.get("person")
    messages = data.get("messages")
    if not person or not isinstance(messages, list) or not messages:
        return None
    rows = [_row("You" if m.get("from") == "me" else m.get("from") or person,
                 _short_time(str(m.get("at") or "")), m.get("text"))
            for m in messages[-5:] if isinstance(m, dict)]
    return {"id": f"thread:{_slug(str(person))}", "kind": "list", "title": _s(person, 80),
            "subtitle": _channel(data.get("channel") or args.get("channel") or "text"),
            "rows": rows, "persist": False}


def _reply(person: str, channel: str, body: str, state: str) -> dict:
    titles = {"draft": "Draft", "approve": "Send this?", "sent": "Sent",
              "unconfirmed": "Sent, not confirmed", "held": "Not sent"}
    # One reply is in flight at a time. A fixed id lets the send card replace the
    # draft even when the model names the person differently ("Dana" vs "Dana Reyes").
    return {"id": "reply", "kind": "reply", "title": titles[state],
            "subtitle": " · ".join(x for x in (_s(person, 80), _channel(channel)) if x),
            "body": _body(body), "state": state, "persist": state in ("draft", "approve")}


def _draft(data: dict, args: dict) -> dict | None:
    text = data.get("draft") or data.get("text")
    person = data.get("person") or args.get("person")
    if not text or not person:
        return None
    return _reply(str(person), str(data.get("channel") or args.get("channel") or "text"), str(text), "draft")


def send_card(args: dict, state: str) -> dict | None:
    """The reply card for a send write, built from the exact arguments being
    approved: the chip preview caps at 38 characters, the card shows it all."""
    person, text = args.get("person"), args.get("text")
    if not person or not text:
        return None
    return _reply(str(person), str(args.get("channel") or "text"), str(text), state)


BUILDERS: dict[str, Builder] = {
    "people": _people, "today": _today, "calendar": _calendar,
    "thread": _thread, "draft": _draft,
}


def result_data(output: str) -> dict | None:
    """The tool's own payload from a harness envelope, or None."""
    try:
        envelope = json.loads(output)
    except (TypeError, ValueError):
        return None
    if not isinstance(envelope, dict) or envelope.get("ok") is not True:
        return None
    data = envelope.get("data")
    if not isinstance(data, dict):
        return None
    if isinstance(data.get("structured"), dict):
        return data["structured"]
    if isinstance(data.get("text"), str):
        try:
            parsed = json.loads(data["text"])
        except ValueError:
            return None
        return parsed if isinstance(parsed, dict) else None
    return None


def build(template: str, args: dict, output: str) -> dict | None:
    builder = BUILDERS.get(template)
    if builder is None:
        return None
    data = result_data(output)
    if data is None or data.get("withheld") or data.get("unavailable") or data.get("error"):
        return None
    try:
        return builder(data, args or {})
    except Exception:  # a card is never worth a failed turn
        return None
