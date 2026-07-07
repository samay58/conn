"""Latency spans computed from a session trace file.

Reads the six budgeted moments from docs/2026-07-05-ux-craft-spec.md's
latency table and computes them from the JSONL events TraceWriter.log()
writes. A span is None whenever the events it needs are missing from the
trace; traces are partial by nature (demo runs, killed sessions, older
schema), so this never raises.

Two timestamp domains coexist in a trace line: `client_ts_ms` (the client's
own monotonic clock, present on ptt_down, ptt_up, ui_ack, kill_switch) and
`ts` (the daemon's wall clock, stamped by TraceWriter.log on every event).
The spec asks for the two keydown/release-to-visible-feedback spans in the
client's own clock (both ends are client-observed, so no clock mixing is
needed); the other four spans have at least one end (model_delta, tool_exec,
tool_proposed, audio_silent) that carries no client timestamp at all, so
those use the daemon `ts` on both ends.
"""

from __future__ import annotations

import json
from pathlib import Path

# name -> (p50_ms, p95_ms | None), from the spec's latency budget table.
BUDGETS_MS: dict[str, tuple[float, float | None]] = {
    "keydown_to_listening_ms": (100, None),
    "release_to_ack_ms": (90, None),
    "release_to_first_token_ms": (900, 1500),
    "release_to_first_tool_ms": (1200, None),
    "proposal_to_chip_ms": (120, None),
    "stop_to_silence_ms": (150, 400),
}

SPAN_NAMES = list(BUDGETS_MS)


def _read_events(trace_path: Path | str) -> list[dict]:
    path = Path(trace_path)
    if not path.exists():
        return []
    events = []
    for line in path.read_text().splitlines():
        line = line.strip()
        if line:
            events.append(json.loads(line))
    return events


def _find(events: list[dict], kind: str, **filters) -> dict | None:
    """First event of `kind` whose fields match `filters`, or None."""
    for e in events:
        if e.get("kind") != kind:
            continue
        if all(e.get(k) == v for k, v in filters.items()):
            return e
    return None


def _client_span_ms(start: dict | None, end: dict | None) -> int | None:
    if start is None or end is None:
        return None
    a, b = start.get("client_ts_ms"), end.get("client_ts_ms")
    if a is None or b is None:
        return None
    return b - a


def _daemon_span_ms(start: dict | None, end: dict | None) -> float | None:
    if start is None or end is None:
        return None
    return round((end["ts"] - start["ts"]) * 1000, 3)


def spans(trace_path: Path | str) -> dict[str, float | None]:
    """The six latency spans for a trace file, keyed as in BUDGETS_MS.

    Each value is None when the trace lacks one of the events the span
    needs. Reads the file fresh every call; traces are small JSONL files
    and this is a report/receipt-attachment path, not a hot loop.
    """
    events = _read_events(trace_path)

    ptt_down = _find(events, "ptt_down")
    ptt_up = _find(events, "ptt_up")
    ack_listening = _find(events, "ui_ack", moment="listening")
    ack_thinking = _find(events, "ui_ack", moment="thinking")
    ack_chip = _find(events, "ui_ack", moment="chip")
    model_delta = _find(events, "model_delta")
    tool_exec = _find(events, "tool_exec")
    tool_proposed = _find(events, "tool_proposed")
    kill_switch = _find(events, "kill_switch")
    # Belay confirms silence via a flush, not the natural end-of-turn drain;
    # both log kind "audio_silent" so this must filter on `after`.
    audio_silent_flush = _find(events, "audio_silent", after="flush")

    return {
        "keydown_to_listening_ms": _client_span_ms(ptt_down, ack_listening),
        "release_to_ack_ms": _client_span_ms(ptt_up, ack_thinking),
        "release_to_first_token_ms": _daemon_span_ms(ptt_up, model_delta),
        "release_to_first_tool_ms": _daemon_span_ms(ptt_up, tool_exec),
        "proposal_to_chip_ms": _daemon_span_ms(tool_proposed, ack_chip),
        "stop_to_silence_ms": _daemon_span_ms(kill_switch, audio_silent_flush),
    }


def budget_status(name: str, value_ms: float | None) -> str:
    """"pass" / "fail" / "n/a", judged against the span's p50 budget."""
    if value_ms is None:
        return "n/a"
    p50, _p95 = BUDGETS_MS[name]
    return "pass" if value_ms <= p50 else "fail"


def format_report(span_values: dict[str, float | None]) -> str:
    """Human-readable report: one line per span, value, budget, pass/fail."""
    width = max(len(name) for name in SPAN_NAMES)
    lines = ["conn latency report"]
    for name in SPAN_NAMES:
        value = span_values.get(name)
        p50, p95 = BUDGETS_MS[name]
        status = budget_status(name, value)
        value_str = f"{value:g}ms" if value is not None else "n/a"
        budget_str = f"budget {p50:g}ms p50" + (f" / {p95:g}ms p95" if p95 else "")
        lines.append(f"  {name:<{width}}  {value_str:>10}  {budget_str:<28}  {status.upper()}")
    return "\n".join(lines)
