"""The session state machine. Pure: no I/O, no clocks, no threads.

app.py feeds it MachineInput events and executes the Command list it returns.
The anti-hallucination invariant lives here: CreateResponse is emitted only when
the response is closed AND every ledger call is resolved, so the model is
structurally unable to narrate an outcome it has not received.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from enum import StrEnum

from .events import (
    ApprovalDecision, ApprovalTimeout, BudgetOverride, BudgetTripped,
    CancelResponse, ClearInput, CloseMic, Command, CommitInput, CreateResponse,
    EndSession, ExecTool, FlushPlayback, Gate, MachineInput, ModelSpeaking,
    OpenMic, PlaybackDrained, PttDown, PttUp, QueueApproval, ResetTick,
    RejectInput, ResponseCancelled, ResponseDone, SendText, SendToolResult,
    TextCommand, ToolCall, ToolFinished, ToolProposed, UserStop, WatchdogTick,
    WsFailed, WsReconnected,
)


class Phase(StrEnum):
    IDLE = "idle"
    LISTENING = "listening"
    THINKING = "thinking"
    ACTING = "acting"
    AWAITING_APPROVAL = "awaiting_approval"
    SPEAKING = "speaking"
    DONE = "done"
    FAILED = "failed"
    BUDGET_HOLD = "budget_hold"


class CallStatus(StrEnum):
    PROPOSED = "proposed"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    DENIED = "denied"
    TIMEOUT = "timeout"
    BLOCKED = "blocked"


RESOLVED = {CallStatus.COMPLETED, CallStatus.FAILED, CallStatus.DENIED,
            CallStatus.TIMEOUT, CallStatus.BLOCKED}


@dataclass
class LedgerEntry:
    call: ToolCall
    status: CallStatus
    output: str | None = None


@dataclass
class SessionStateMachine:
    tap_threshold_ms: int = 300
    watchdog_timeout_s: float = 600
    phase: Phase = Phase.IDLE
    ledger: dict[str, LedgerEntry] = field(default_factory=dict)
    last_transition: tuple[Phase, Phase] | None = None
    _ptt_down_ms: int | None = None
    _response_open: bool = False   # a response.create is in flight upstream
    _batch_had_calls: bool = False  # current response proposed at least one tool call
    _transition_seq: int = 0       # bumped on every real phase transition
    _watchdog_armed_seq: int | None = None
    _watchdog_armed_ts_ms: int | None = None

    # ---------- public ----------

    def handle(self, ev: MachineInput) -> list[Command]:
        old_phase = self.phase
        cmds = self._dispatch(ev)
        if self.phase != old_phase:
            self.last_transition = (old_phase, self.phase)
            self._transition_seq += 1
        return cmds

    def _dispatch(self, ev: MachineInput) -> list[Command]:
        match ev:
            case PttDown():
                return self._ptt_down(ev)
            case PttUp():
                return self._ptt_up(ev)
            case TextCommand():
                return self._text(ev)
            case ToolProposed():
                return self._tool_proposed(ev.call)
            case ToolFinished():
                return self._resolve(ev.call_id,
                                     CallStatus.COMPLETED if ev.ok else CallStatus.FAILED,
                                     ev.output, ok=ev.ok)
            case ApprovalDecision():
                return self._approval(ev)
            case ApprovalTimeout():
                return self._resolve(ev.call_id, CallStatus.TIMEOUT,
                                     '{"ok": false, "error": "approval_timeout"}', ok=False)
            case ModelSpeaking():
                if self.phase is Phase.THINKING:
                    self.phase = Phase.SPEAKING
                return []
            case ResponseDone():
                return self._response_done(ev)
            case ResponseCancelled():
                self._response_open = False
                return []
            case PlaybackDrained():
                if (self.phase is Phase.SPEAKING and not self._response_open
                        and not self._unresolved()):
                    self.phase = Phase.DONE
                return []
            case ResetTick():
                if self.phase is Phase.DONE:
                    self.phase = Phase.IDLE
                return []
            case WsFailed():
                return self._ws_failed()
            case WsReconnected():
                if self.phase is Phase.FAILED:
                    self._reset_turn()
                    self.phase = Phase.IDLE
                return []
            case BudgetTripped():
                self.phase = Phase.BUDGET_HOLD
                return [CloseMic(), FlushPlayback()]
            case BudgetOverride():
                if self.phase is Phase.BUDGET_HOLD:
                    self.phase = Phase.THINKING
                    self._response_open = True
                    return [CreateResponse()]
                return []
            case UserStop():
                return self._stop()
            case WatchdogTick():
                return self._watchdog(ev)
        return []

    def unresolved_calls(self) -> list[LedgerEntry]:
        return self._unresolved()

    def snapshot(self) -> dict:
        return {
            "phase": self.phase.value,
            "ledger": [
                {"call_id": e.call.call_id, "name": e.call.name,
                 "preview": e.call.preview, "gate": e.call.gate.value,
                 "status": e.status.value}
                for e in self.ledger.values()
            ],
        }

    # ---------- transitions ----------

    def _ptt_down(self, ev: PttDown) -> list[Command]:
        if self.phase in (Phase.IDLE, Phase.DONE):
            self._new_turn()
            self._ptt_down_ms = ev.ts_ms
            return [ClearInput(), OpenMic()]
        if self.phase is Phase.SPEAKING:
            # Barge-in, v0 flavor: cancel and flush, no truncate precision.
            self._new_turn()
            self._ptt_down_ms = ev.ts_ms
            return [CancelResponse(), FlushPlayback(), ClearInput(), OpenMic()]
        return [RejectInput(reason=self.phase.value)]

    def _ptt_up(self, ev: PttUp) -> list[Command]:
        if self.phase is not Phase.LISTENING:
            return []
        held = ev.ts_ms - (self._ptt_down_ms or ev.ts_ms)
        self._ptt_down_ms = None
        if held < self.tap_threshold_ms:
            self.phase = Phase.IDLE
            return [CloseMic(), ClearInput()]
        self.phase = Phase.THINKING
        self._begin_response()
        return [CloseMic(), CommitInput(), CreateResponse()]

    def _text(self, ev: TextCommand) -> list[Command]:
        if self.phase not in (Phase.IDLE, Phase.DONE):
            return []
        self._new_turn()
        self.phase = Phase.THINKING
        self._begin_response()
        return [SendText(ev.text), CreateResponse()]

    def _tool_proposed(self, call: ToolCall) -> list[Command]:
        if self.phase in (Phase.IDLE, Phase.FAILED, Phase.BUDGET_HOLD):
            return []  # stray proposal outside a turn: ignore, adapter noise
        self._batch_had_calls = True
        cmds: list[Command] = []
        match call.gate:
            case Gate.AUTO:
                self.ledger[call.call_id] = LedgerEntry(call, CallStatus.RUNNING)
                cmds.append(ExecTool(call))
            case Gate.CONFIRM:
                self.ledger[call.call_id] = LedgerEntry(call, CallStatus.PROPOSED)
                cmds.append(QueueApproval(call))
            case Gate.BLOCKED:
                reason = call.block_reason or "blocked_by_policy"
                output = json.dumps({"ok": False, "error": reason})
                self.ledger[call.call_id] = LedgerEntry(call, CallStatus.BLOCKED, output)
                cmds.append(SendToolResult(call.call_id, False, output))
                cmds.extend(self._maybe_continue())
        self._refresh_phase()
        return cmds

    def _approval(self, ev: ApprovalDecision) -> list[Command]:
        entry = self.ledger.get(ev.call_id)
        if entry is None or entry.status is not CallStatus.PROPOSED:
            return []
        if ev.approved:
            entry.status = CallStatus.RUNNING
            self._refresh_phase()
            return [ExecTool(entry.call)]
        return self._resolve(ev.call_id, CallStatus.DENIED,
                             '{"ok": false, "error": "denied_by_user"}', ok=False)

    def _resolve(self, call_id: str, status: CallStatus, output: str, *, ok: bool) -> list[Command]:
        entry = self.ledger.get(call_id)
        if entry is None or entry.status in RESOLVED:
            return []
        entry.status = status
        entry.output = output
        cmds: list[Command] = [SendToolResult(call_id, ok, output)]
        cmds.extend(self._maybe_continue())
        self._refresh_phase()
        return cmds

    def _response_done(self, ev: ResponseDone) -> list[Command]:
        self._response_open = False
        if ev.had_tool_calls:
            self._batch_had_calls = True
        if self._unresolved():
            return []  # tools still pending; the model stays paused
        if self._batch_had_calls:
            # All calls resolved before response.done landed: continue now.
            self._batch_had_calls = False
            self._begin_response()
            self.phase = Phase.THINKING
            return [CreateResponse()]
        if self.phase is Phase.THINKING:
            self.phase = Phase.DONE  # text-only response, nothing to drain
        return []

    def _maybe_continue(self) -> list[Command]:
        """One continuation per tool batch, only after the response closed and
        every call resolved."""
        if self._response_open or self._unresolved() or not self._batch_had_calls:
            return []
        self._batch_had_calls = False
        self._begin_response()
        self.phase = Phase.THINKING
        return [CreateResponse()]

    def _ws_failed(self) -> list[Command]:
        self.phase = Phase.FAILED
        self._reset_turn()
        return [CloseMic(), FlushPlayback()]

    def _watchdog(self, ev: WatchdogTick) -> list[Command]:
        """Polled input, not a clock read: WatchdogTick carries the caller's
        own timestamp. Arms a baseline on (transition_seq, ts) rather than
        phase alone, so a phase that leaves and returns between two ticks
        (e.g. a healthy THINKING -> ACTING -> THINKING tool loop) still
        re-arms: any real transition recorded since the baseline was set
        bumps _transition_seq, which this checks instead of re-checking the
        phase value itself. Forces the same failure path as WsFailed once
        the baseline is stale and no pending call for watchdog_timeout_s.

        FAILED is exempt alongside IDLE and AWAITING_APPROVAL. This is a
        deviation from the original packet text: firing the failure path
        again from FAILED is a no-op that just re-emits CloseMic/
        FlushPlayback, and the watchdog's purpose (forcing a stuck session
        into visible failure) is already satisfied once we're here.
        """
        if self.phase in (Phase.IDLE, Phase.AWAITING_APPROVAL, Phase.FAILED):
            self._watchdog_armed_seq = None
            self._watchdog_armed_ts_ms = None
            return []
        if self._watchdog_armed_seq != self._transition_seq:
            self._watchdog_armed_seq = self._transition_seq
            self._watchdog_armed_ts_ms = ev.ts_ms
            return []
        if self._unresolved():
            return []  # a call is still legitimately in flight
        elapsed_s = (ev.ts_ms - self._watchdog_armed_ts_ms) / 1000
        if elapsed_s >= self.watchdog_timeout_s:
            cmds = self._ws_failed()
            # Fire at most once per full timeout window, not once per tick,
            # even if a future call site's failure path doesn't land in an
            # exempt phase.
            self._watchdog_armed_ts_ms = ev.ts_ms
            return cmds
        return []

    def _stop(self) -> list[Command]:
        cmds: list[Command] = [CancelResponse(), FlushPlayback(), CloseMic(),
                               ClearInput(), EndSession("user_stop")]
        self._reset_turn()
        self.phase = Phase.IDLE
        return cmds

    # ---------- internals ----------

    def _begin_response(self) -> None:
        self._response_open = True

    def _new_turn(self) -> None:
        """Fresh turn: drop last turn's (fully resolved) ledger so stale chips
        disappear, and enter LISTENING."""
        self.ledger.clear()
        self._response_open = False
        self._batch_had_calls = False
        self.phase = Phase.LISTENING

    def _reset_turn(self) -> None:
        self.ledger.clear()
        self._response_open = False
        self._batch_had_calls = False
        self._ptt_down_ms = None

    def _unresolved(self) -> list[LedgerEntry]:
        return [e for e in self.ledger.values() if e.status not in RESOLVED]

    def _refresh_phase(self) -> None:
        if self.phase in (Phase.IDLE, Phase.FAILED, Phase.BUDGET_HOLD, Phase.LISTENING):
            return
        if any(e.status is CallStatus.PROPOSED for e in self.ledger.values()):
            self.phase = Phase.AWAITING_APPROVAL
        elif any(e.status is CallStatus.RUNNING for e in self.ledger.values()):
            self.phase = Phase.ACTING
        elif not self._response_open and not self._unresolved() and not self._batch_had_calls:
            # Turn fully settled; SPEAKING/DONE resolution is handled by
            # PlaybackDrained and ResponseDone, so leave those phases alone.
            if self.phase is Phase.ACTING:
                self.phase = Phase.THINKING
