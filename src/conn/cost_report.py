"""`python -m conn --cost-report`: unit economics from trace files.

Every number is recomputed by replaying the trace's raw rows (response_done,
response_created, input, ...) through TurnLedger, so traces from before the
turn_cost event existed report exactly like new ones, and the report agrees
with the live receipt by construction. Existing turn_cost rows are ignored.
"""

from __future__ import annotations

import statistics
from datetime import date, timedelta
from pathlib import Path

from .config import PricingCfg
from .cost import CATEGORY_FIELDS
from .latency import read_events
from .turn_ledger import TurnAccount, TurnLedger

UTTERANCE_WIDTH = 50


def replay(trace_path: Path | str, pricing: PricingCfg) -> TurnLedger:
    """Feed a whole trace through a fresh, non-emitting ledger."""
    ledger = TurnLedger(pricing)
    for event in read_events(trace_path):
        ledger.observe(event)
    return ledger


def _input_tokens(ledger: TurnLedger) -> tuple[int, int]:
    """(total input tokens billed, of which cached)."""
    total = cached = 0
    for account in ledger.accounts.values():
        u = account.usage
        cached += u.cached_in
        total += u.text_in + u.audio_in + u.image_in + u.cached_in
    return total, cached


def _truncate(text: str, width: int = UTTERANCE_WIDTH) -> str:
    text = " ".join(text.split())
    return text if len(text) <= width else text[: width - 3] + "..."


def _usd(value: float) -> str:
    return f"${value:.4f}"


def session_report(trace_path: Path | str, pricing: PricingCfg) -> str:
    path = Path(trace_path)
    ledger = replay(path, pricing)
    accounts = list(ledger.accounts.values())
    lines = [f"conn cost report  {path.stem}  {path.parent.name}"]
    if not accounts:
        lines.append("  no billed responses in this trace")
        return "\n".join(lines)

    costs = [a.usage.usd for a in accounts]
    responses = sum(a.responses for a in accounts)
    cancelled = sum(a.cancelled for a in accounts)
    total = sum(costs)
    in_total, in_cached = _input_tokens(ledger)
    hit_rate = 100 * in_cached / in_total if in_total else 0.0
    per_cmd = [a.responses for a in accounts]
    totals = ledger.category_totals()

    lines += [
        "",
        f"  commands              {len(accounts)}",
        f"  responses             {responses} ({cancelled} cancelled)",
        f"  responses per command mean {statistics.mean(per_cmd):.2f}  "
        f"median {statistics.median(per_cmd):g}  max {max(per_cmd)}",
        f"  total                 {_usd(total)}",
        f"  cost per command      mean {_usd(statistics.mean(costs))}  "
        f"median {_usd(statistics.median(costs))}  max {_usd(max(costs))}",
        f"  input tokens          {in_total:,}  cache hit rate {hit_rate:.1f}%",
        "",
        f"  {'category':<20}{'tokens':>10}{'usd':>11}{'share':>8}",
    ]
    for name in CATEGORY_FIELDS:
        usd = totals["usd"][name]
        share = 100 * usd / total if total else 0.0
        lines.append(f"  {name:<20}{totals['tokens'][name]:>10,}{_usd(usd):>11}{share:>7.1f}%")

    lines += ["", "  five most expensive commands"]
    top = sorted(accounts, key=lambda a: a.usage.usd, reverse=True)[:5]
    for account in top:
        lines.append(_top_line(account))
    return "\n".join(lines)


def _top_line(account: TurnAccount) -> str:
    return (f"  #{account.turn_no:<3}{_usd(account.usage.usd):>9}  "
            f"{account.responses} resp  {account.tools} tools  "
            f"{_truncate(account.utterance) or '(no transcript)'}")


def trace_paths_for_days(data_dir: Path, days: int, today: date | None = None) -> dict[str, list[Path]]:
    """Trace files grouped by date folder, for the last `days` calendar days
    including today."""
    today = today or date.today()
    out: dict[str, list[Path]] = {}
    for offset in range(days):
        day = (today - timedelta(days=offset)).isoformat()
        paths = sorted((data_dir / "traces" / day).glob("*.jsonl"))
        if paths:
            out[day] = paths
    return dict(sorted(out.items()))


def days_report(data_dir: Path, days: int, pricing: PricingCfg, today: date | None = None) -> str:
    grouped = trace_paths_for_days(data_dir, days, today)
    lines = [f"conn cost report  last {days} day(s)"]
    if not grouped:
        lines.append(f"  no traces under {data_dir / 'traces'} in that window")
        return "\n".join(lines)
    lines += ["", f"  {'day':<12}{'sessions':>9}{'commands':>9}{'responses':>10}"
                  f"{'total':>10}{'per cmd':>10}{'cache hit':>10}"]
    grand = {"sessions": 0, "commands": 0, "responses": 0, "usd": 0.0, "in": 0, "cached": 0}
    for day, paths in grouped.items():
        row = {"sessions": 0, "commands": 0, "responses": 0, "usd": 0.0, "in": 0, "cached": 0}
        for path in paths:
            ledger = replay(path, pricing)
            if not ledger.accounts:
                continue
            in_total, in_cached = _input_tokens(ledger)
            row["sessions"] += 1
            row["commands"] += len(ledger.accounts)
            row["responses"] += sum(a.responses for a in ledger.accounts.values())
            row["usd"] += sum(a.usage.usd for a in ledger.accounts.values())
            row["in"] += in_total
            row["cached"] += in_cached
        lines.append(_day_line(day, row))
        for key in grand:
            grand[key] += row[key]
    lines.append(_day_line("all", grand))
    return "\n".join(lines)


def _day_line(label: str, row: dict) -> str:
    per_cmd = row["usd"] / row["commands"] if row["commands"] else 0.0
    hit = 100 * row["cached"] / row["in"] if row["in"] else 0.0
    return (f"  {label:<12}{row['sessions']:>9}{row['commands']:>9}{row['responses']:>10}"
            f"{_usd(row['usd']):>10}{_usd(per_cmd):>10}{hit:>9.1f}%")
