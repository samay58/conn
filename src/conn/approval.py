"""Pending approval chips with a deny-by-default timeout."""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import Callable

from .events import ApprovalTimeout, ToolCall

APPROVAL_TIMEOUT_S = 30.0


@dataclass
class PendingApproval:
    call: ToolCall
    asked_at: float = field(default_factory=time.time)
    timer: asyncio.TimerHandle | None = None


class ApprovalManager:
    def __init__(self, on_timeout: Callable[[ApprovalTimeout], None],
                 timeout_s: float = APPROVAL_TIMEOUT_S):
        self.pending: dict[str, PendingApproval] = {}
        self._on_timeout = on_timeout
        self.timeout_s = timeout_s

    def ask(self, call: ToolCall) -> None:
        loop = asyncio.get_running_loop()
        p = PendingApproval(call=call)
        p.timer = loop.call_later(
            self.timeout_s, self._timeout, call.call_id)
        self.pending[call.call_id] = p

    def decide(self, call_id: str) -> float | None:
        """Clears the chip; returns decision latency in seconds."""
        p = self.pending.pop(call_id, None)
        if p is None:
            return None
        if p.timer:
            p.timer.cancel()
        return time.time() - p.asked_at

    def clear(self) -> None:
        for p in self.pending.values():
            if p.timer:
                p.timer.cancel()
        self.pending.clear()

    def _timeout(self, call_id: str) -> None:
        if call_id in self.pending:
            self.pending.pop(call_id)
            self._on_timeout(ApprovalTimeout(call_id=call_id))
