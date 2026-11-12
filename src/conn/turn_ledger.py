"""Per-command (per-turn) cost accounting.

A user command is one turn_id; the model may answer it with several responses
(the first, then one follow-up per round of tool results). The ledger folds
every billed response into the turn that caused it and answers "what did this
command cost", which the session-level CostMeter cannot.

The ledger is fed trace events, not app internals. That is deliberate: the
daemon subscribes it to its TraceWriter, and `--cost-report` replays old trace
files through the very same `observe`, so the live receipt and the offline
report cannot disagree and traces written before turn_cost existed still work.

Attribution rules (all derived from event order, which the trace preserves):
  - `response_created` carries turn_id and opens a response.
  - `response_done` rows predate response_id, so the most recent unresolved
    response is the one that finished (responses are serial). Rows that do
    carry a response_id are matched exactly.
  - `response_cancelled_usage` / `stale_response_usage` always carry the id;
    cancelled responses are billed too, so they count toward their turn.
  - `input` (the transcript) lands just after the turn's first response is
    created for voice, and just before it for typed text.
A turn closes, and its `turn_cost` event is emitted, when the next turn
starts billing or when flush() runs at session end.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from .config import PricingCfg
from .cost import CATEGORY_FIELDS, TurnCost, category_usd, price_usage

EmitFn = Callable[..., object]  # TraceWriter.log shape: emit(kind, **payload)


@dataclass
class TurnAccount:
    turn_id: str
    turn_no: int
    usage: TurnCost = field(default_factory=TurnCost)
    responses: int = 0
    cancelled: int = 0
    tools: int = 0
    utterance: str = ""
    release_ts: float | None = None
    first_audio_ts: float | None = None
    closed: bool = False
    revisions: int = 0

    @property
    def release_to_first_audio_ms(self) -> float | None:
        if self.release_ts is None or self.first_audio_ts is None:
            return None
        return round((self.first_audio_ts - self.release_ts) * 1000, 1)


class TurnLedger:
    def __init__(self, pricing: PricingCfg, emit: EmitFn | None = None):
        self.pricing = pricing
        self.emit = emit
        self.accounts: dict[str, TurnAccount] = {}
        self.errors = 0
        self._ctx_turn: str | None = None            # latest turn_context
        self._current_turn: str | None = None        # latest turn to bill a response
        self._release_ts: dict[str, float] = {}      # first ptt_up per turn
        self._open: dict[str, str] = {}              # response_id -> turn_id
        self._open_order: list[str] = []
        self._pending_text_chars = ""                # typed input awaiting its response

    # ---- wiring ----

    def attach(self, trace) -> None:
        """Subscribe to a TraceWriter and emit turn_cost through it. Accounting
        must never take the daemon down, so a bad event is counted, not raised."""
        self.emit = trace.log

        def listen(event: dict) -> None:
            try:
                self.observe(event)
            except Exception:
                self.errors += 1

        trace.subscribe(listen)

    # ---- event intake ----

    def observe(self, event: dict) -> None:
        kind = event.get("kind")
        ts = event.get("ts")
        if kind == "turn_context":
            self._ctx_turn = event.get("turn_id")
        elif kind == "ptt_up":
            if self._ctx_turn and self._ctx_turn not in self._release_ts and ts is not None:
                self._release_ts[self._ctx_turn] = ts
        elif kind == "input":
            self._on_input(event)
        elif kind == "response_created":
            self._on_created(event)
        elif kind == "model_delta":
            self._on_delta(event)
        elif kind == "tool_proposed":
            account = self.accounts.get(event.get("turn_id") or "")
            if account is not None:
                account.tools += 1
        elif kind == "response_done":
            self._on_usage(event, cancelled=False)
        elif kind in ("response_cancelled_usage", "stale_response_usage"):
            self._on_usage(event, cancelled=True)

    def _account(self, turn_id: str) -> TurnAccount:
        account = self.accounts.get(turn_id)
        if account is None:
            # A new turn starting to bill means every earlier turn is over.
            self._close_all()
            account = TurnAccount(turn_id=turn_id, turn_no=len(self.accounts) + 1,
                                  release_ts=self._release_ts.get(turn_id))
            self.accounts[turn_id] = account
        return account

    def _on_input(self, event: dict) -> None:
        text = event.get("text") or ""
        if event.get("mode") == "text":
            self._pending_text_chars = text
            return
        account = self.accounts.get(self._current_turn or "")
        if account is not None:
            account.utterance = f"{account.utterance} {text}".strip()

    def _on_created(self, event: dict) -> None:
        turn_id = event.get("turn_id")
        response_id = event.get("response_id")
        if not turn_id:
            return
        account = self._account(turn_id)
        self._current_turn = turn_id
        if self._pending_text_chars:
            account.utterance = self._pending_text_chars
            self._pending_text_chars = ""
        if response_id:
            self._open[response_id] = turn_id
            self._open_order.append(response_id)

    def _on_delta(self, event: dict) -> None:
        account = self.accounts.get(self._current_turn or "")
        if (account is None or account.first_audio_ts is not None
                or event.get("modality") != "audio"):
            return
        ts = event.get("ts")
        if ts is not None and account.release_ts is not None and ts >= account.release_ts:
            account.first_audio_ts = ts

    def _on_usage(self, event: dict, *, cancelled: bool) -> None:
        usage = event.get("usage")
        if not usage:
            return
        response_id = event.get("response_id")
        if response_id in self._open:
            turn_id = self._open.pop(response_id)
            self._open_order.remove(response_id)
        elif response_id is None and self._open_order:
            response_id = self._open_order.pop()
            turn_id = self._open.pop(response_id)
        else:
            # Usage for a response whose creation we never saw: keep the
            # dollars on the latest turn rather than lose them.
            turn_id = self._current_turn or "unattributed"
        account = self.accounts.get(turn_id) or self._account(turn_id)
        priced = price_usage(usage, self.pricing)
        for name in CATEGORY_FIELDS.values():
            setattr(account.usage, name, getattr(account.usage, name) + getattr(priced, name))
        account.usage.usd += priced.usd
        account.responses += 1
        account.cancelled += 1 if cancelled else 0
        if account.closed:
            # Late usage (a cancelled response's tokens arriving after the
            # next turn began billing): re-emit so the trace stays truthful.
            account.revisions += 1
            self._emit(account)

    # ---- closing ----

    def _close_all(self) -> None:
        for account in self.accounts.values():
            if not account.closed:
                account.closed = True
                self._emit(account)

    def flush(self) -> None:
        """Close every open turn. Called at session end before the receipt."""
        self._close_all()

    def _emit(self, account: TurnAccount) -> None:
        if self.emit is not None:
            self.emit("turn_cost", **self.turn_dict(account))

    # ---- views ----

    def turn_dict(self, account: TurnAccount) -> dict:
        """The turn_cost payload. Carries the utterance length, never its text."""
        usd = category_usd(account.usage, self.pricing)
        out = {
            "turn": account.turn_no,
            "turn_id": account.turn_id,
            "utterance_chars": len(account.utterance),
            "responses": account.responses,
            "cancelled_responses": account.cancelled,
            "tool_count": account.tools,
            "tokens": {name: getattr(account.usage, attr)
                       for name, attr in CATEGORY_FIELDS.items()},
            "usd": {name: round(value, 6) for name, value in usd.items()},
            "total_usd": round(account.usage.usd, 6),
            "release_to_first_audio_ms": account.release_to_first_audio_ms,
        }
        if account.revisions:
            out["revision"] = account.revisions
        return out

    def snapshot(self) -> list[dict]:
        return [self.turn_dict(a) for a in self.accounts.values()]

    def category_totals(self) -> dict:
        total = TurnCost()
        for account in self.accounts.values():
            for attr in CATEGORY_FIELDS.values():
                setattr(total, attr, getattr(total, attr) + getattr(account.usage, attr))
            total.usd += account.usage.usd
        return {
            "tokens": {name: getattr(total, attr) for name, attr in CATEGORY_FIELDS.items()},
            "usd": {name: round(v, 6) for name, v in category_usd(total, self.pricing).items()},
            "total_usd": round(total.usd, 6),
        }
