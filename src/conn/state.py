"""The session state machine. Pure: no I/O, no clocks, no threads.

app.py feeds it MachineInput events and executes the Command list it returns.
The anti-hallucination invariant lives here: CreateResponse is emitted only when
the response is closed AND every ledger call is resolved, so the model is
structurally unable to narrate an outcome it has not received.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field, replace
from enum import StrEnum

from .events import (
    AckTurn, ApprovalDecision, ApprovalTimeout, BudgetOverride, BudgetTripped,
    CancelResponse, ClearInput, CloseMic, Command, CommitInput, CreateResponse,
    EndSession, ExecTool, FlushPlayback, Gate, MachineInput, ModelSpeaking,
    OpenMic, PlaybackDrained, PttDown, PttUp, QueueApproval, ResetTick,
    RejectInput, ResponseCancelled, ResponseDone, SendText, SendToolResult,
    ResponseProvenance, TextCommand, ToolCall, ToolFinished, ToolProposed,
    UserStop, WatchdogTick, WsFailed, WsReconnected,
)
from .actions import (
    ActionEvidence,
    ActionOutcome,
    ActionReceipt,
    DispatchState,
    ambiguous_receipt,
    blocked_receipt,
    dispatch_only_receipt,
    uncertain_failure_receipt,
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
    VERIFIED = "verified"
    UNVERIFIED = "unverified"
    NO_EFFECT = "no_effect"
    AMBIGUOUS = "ambiguous"
    FAILED = "failed"
    DENIED = "denied"
    TIMEOUT = "timeout"
    BLOCKED = "blocked"


RESOLVED = {CallStatus.COMPLETED, CallStatus.VERIFIED, CallStatus.UNVERIFIED,
            CallStatus.NO_EFFECT, CallStatus.AMBIGUOUS, CallStatus.FAILED,
            CallStatus.DENIED, CallStatus.TIMEOUT, CallStatus.BLOCKED}


@dataclass
class LedgerEntry:
    call: ToolCall
    status: CallStatus
    output: str | None = None


@dataclass
class PendingResponse:
    provenance: ResponseProvenance
    cancelled: bool = False


@dataclass
class ResponseProvenanceLedger:
    pending: list[PendingResponse] = field(default_factory=list)
    bindings: dict[str, ResponseProvenance] = field(default_factory=dict)
    active_response_id: str | None = None
    retired_response_ids: set[str] = field(default_factory=set)

    def request(self, provenance: ResponseProvenance) -> None:
        self.pending.append(PendingResponse(provenance))

    def cancel_current(self) -> None:
        if self.pending:
            self.pending[-1].cancelled = True
            return
        if self.active_response_id is not None:
            self.retire(self.active_response_id)

    def created(self, response_id: str) -> ResponseProvenance | None:
        if not response_id or response_id in self.bindings or not self.pending:
            return None
        pending = self.pending.pop(0)
        self.bindings[response_id] = pending.provenance
        if pending.cancelled:
            self.retired_response_ids.add(response_id)
        else:
            if self.active_response_id is not None:
                self.retired_response_ids.add(self.active_response_id)
            self.active_response_id = response_id
        return pending.provenance

    def resolve(self, response_id: str | None) -> ResponseProvenance | None:
        if (not response_id or response_id != self.active_response_id
                or response_id in self.retired_response_ids):
            return None
        return self.bindings.get(response_id)

    def retire(self, response_id: str) -> None:
        self.retired_response_ids.add(response_id)
        if self.active_response_id == response_id:
            self.active_response_id = None


@dataclass
class SessionStateMachine:
    computer_mutations: frozenset[str]
    tap_threshold_ms: int = 300
    watchdog_timeout_s: float = 600
    phase: Phase = Phase.IDLE
    ledger: dict[str, LedgerEntry] = field(default_factory=dict)
    last_transition: tuple[Phase, Phase] | None = None
    _ptt_down_ms: int | None = None
    _response_open: bool = False   # a response.create is in flight upstream
    _batch_had_calls: bool = False  # current response proposed at least one tool call
    _mutation_reserved: bool = False
    _mutation_chain_closed: bool = False
    _replan_budget: int = 1        # one replan per turn, only after proven not_dispatched
    _predispatch_failures: int = 0  # compile failures do not consume the replan budget
    _failed_shapes: set[str] = field(default_factory=set)
    _execution_seq: int = 0
    _transition_seq: int = 0       # bumped on every real phase transition
    _watchdog_armed_seq: int | None = None
    _watchdog_armed_ts_ms: int | None = None


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
                return self._tool_finished(ev)
            case ApprovalDecision():
                return self._approval(ev)
            case ApprovalTimeout():
                entry = self.ledger.get(ev.call_id)
                output = (
                    self._predispatch_failure_output(entry.call, "approval_timeout")
                    if entry is not None
                    and self._is_computer_mutation(entry.call.name)
                    else '{"ok": false, "error": "approval_timeout"}'
                )
                return self._resolve(ev.call_id, CallStatus.TIMEOUT,
                                     output, ok=False)
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

    def _is_computer_mutation(self, name: str) -> bool:
        return name in self.computer_mutations

    def snapshot(self) -> dict:
        action_outcomes = [
            self._outcome_for_status(entry.status).value
            for entry in self.ledger.values()
            if self._outcome_for_status(entry.status) is not None
        ]
        return {
            "phase": self.phase.value,
            "last_action_outcome": action_outcomes[-1] if action_outcomes else None,
            "ledger": [
                {"call_id": e.call.call_id, "name": e.call.name,
                 "preview": e.call.preview, "gate": e.call.gate.value,
                 "status": e.status.value}
                for e in self.ledger.values()
            ],
        }

    @staticmethod
    def _status_for_result(ev: ToolFinished) -> CallStatus:
        match ev.action_outcome:
            case ActionOutcome.VERIFIED:
                return CallStatus.VERIFIED
            case ActionOutcome.DISPATCH_ONLY:
                return CallStatus.UNVERIFIED
            case ActionOutcome.NO_EFFECT:
                return CallStatus.NO_EFFECT
            case ActionOutcome.AMBIGUOUS:
                return CallStatus.AMBIGUOUS
            case ActionOutcome.BLOCKED:
                return CallStatus.BLOCKED
            case ActionOutcome.FAILED:
                return CallStatus.FAILED
            case None:
                return CallStatus.COMPLETED if ev.ok else CallStatus.FAILED

    @staticmethod
    def _outcome_for_status(status: CallStatus) -> ActionOutcome | None:
        return {
            CallStatus.VERIFIED: ActionOutcome.VERIFIED,
            CallStatus.UNVERIFIED: ActionOutcome.DISPATCH_ONLY,
            CallStatus.NO_EFFECT: ActionOutcome.NO_EFFECT,
            CallStatus.AMBIGUOUS: ActionOutcome.AMBIGUOUS,
            CallStatus.BLOCKED: ActionOutcome.BLOCKED,
            CallStatus.DENIED: ActionOutcome.BLOCKED,
            CallStatus.FAILED: ActionOutcome.FAILED,
            CallStatus.TIMEOUT: ActionOutcome.FAILED,
        }.get(status)


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
        if self.phase is Phase.LISTENING:
            # Duplicate modifier edge for the gesture already in progress;
            # idempotent, not a rejection.
            return []
        return [RejectInput(reason=self.phase.value)]

    def _ptt_up(self, ev: PttUp) -> list[Command]:
        if self.phase is not Phase.LISTENING:
            return []
        held = ev.ts_ms - (self._ptt_down_ms or ev.ts_ms)
        self._ptt_down_ms = None
        if held < self.tap_threshold_ms and ev.voiced is not True:
            # Duration alone cannot discard a voiced command; silence plus a
            # short hold can, and it must be visible, never silent.
            self.phase = Phase.IDLE
            return [AckTurn(accepted=False, reason="silent_tap"),
                    CloseMic(), ClearInput()]
        self.phase = Phase.THINKING
        self._begin_response()
        return [AckTurn(accepted=True), CloseMic(), CommitInput(),
                CreateResponse()]

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
        if call.call_id in self.ledger:
            return []
        self._batch_had_calls = True
        if self._is_computer_mutation(call.name):
            if self._plan_shape(call) in self._failed_shapes:
                # The same failed plan shape never runs twice in one turn; a
                # model repeating itself has exhausted its safe options.
                self._mutation_chain_closed = True
                output = self._blocked_action_output(
                    call, "repeated_plan_shape: this exact plan already failed this turn")
                self.ledger[call.call_id] = LedgerEntry(
                    call, CallStatus.BLOCKED, output)
                cmds = [SendToolResult(call.call_id, False, output)]
                cmds.extend(self._maybe_continue())
                self._refresh_phase()
                return cmds
            if self._mutation_chain_closed:
                output = self._blocked_action_output(
                    call, "mutation_chain_closed: fresh user turn required")
                self.ledger[call.call_id] = LedgerEntry(
                    call, CallStatus.BLOCKED, output)
                cmds = [SendToolResult(call.call_id, False, output)]
                cmds.extend(self._maybe_continue())
                self._refresh_phase()
                return cmds
            if self._mutation_reserved:
                output = self._blocked_action_output(
                    call,
                    "sequential_action_required: propose one mutation after observing the prior outcome",
                )
                self._mutation_chain_closed = True
                self.ledger[call.call_id] = LedgerEntry(call, CallStatus.BLOCKED, output)
                cmds = [SendToolResult(call.call_id, False, output)]
                cmds.extend(self._maybe_continue())
                self._refresh_phase()
                return cmds
            self._mutation_reserved = True
        cmds: list[Command] = []
        match call.gate:
            case Gate.AUTO:
                running_call = self._start_execution(call)
                self.ledger[call.call_id] = LedgerEntry(
                    running_call, CallStatus.RUNNING)
                cmds.append(ExecTool(running_call))
            case Gate.CONFIRM:
                self.ledger[call.call_id] = LedgerEntry(call, CallStatus.PROPOSED)
                cmds.append(QueueApproval(call))
            case Gate.BLOCKED:
                reason = call.block_reason or "blocked_by_policy"
                if self._is_computer_mutation(call.name):
                    prepared_failure = self._prepared_failure_receipt(call)
                    if self._is_recoverable_compile_failure(prepared_failure):
                        # A predispatch compiler failure does not consume the
                        # dispatch budget, but it is bounded per turn and its
                        # shape can never be retried.
                        self._predispatch_failures += 1
                        self._failed_shapes.add(self._plan_shape(call))
                        if self._predispatch_failures > 2:
                            self._mutation_chain_closed = True
                    else:
                        self._mutation_chain_closed = True
                    if prepared_failure is not None:
                        output = json.dumps(prepared_failure.as_dict())
                        status = {
                            ActionOutcome.AMBIGUOUS: CallStatus.AMBIGUOUS,
                            ActionOutcome.BLOCKED: CallStatus.BLOCKED,
                            ActionOutcome.FAILED: CallStatus.FAILED,
                        }[prepared_failure.outcome]
                    else:
                        output = self._blocked_action_output(call, reason)
                        status = CallStatus.BLOCKED
                else:
                    output = json.dumps({"ok": False, "error": reason})
                    status = CallStatus.BLOCKED
                self.ledger[call.call_id] = LedgerEntry(call, status, output)
                cmds.append(SendToolResult(call.call_id, False, output))
                cmds.extend(self._maybe_continue())
        self._refresh_phase()
        return cmds

    def _approval(self, ev: ApprovalDecision) -> list[Command]:
        entry = self.ledger.get(ev.call_id)
        if entry is None or entry.status is not CallStatus.PROPOSED:
            return []
        if ev.approved:
            entry.call = self._start_execution(entry.call)
            entry.status = CallStatus.RUNNING
            self._refresh_phase()
            return [ExecTool(entry.call)]
        output = (
            self._blocked_action_output(entry.call, "denied_by_user")
            if self._is_computer_mutation(entry.call.name)
            else '{"ok": false, "error": "denied_by_user"}'
        )
        return self._resolve(ev.call_id, CallStatus.DENIED, output, ok=False)

    def _resolve(self, call_id: str, status: CallStatus, output: str, *, ok: bool) -> list[Command]:
        entry = self.ledger.get(call_id)
        if entry is None or entry.status in RESOLVED:
            return []
        if (self._is_computer_mutation(entry.call.name)
                and status is not CallStatus.VERIFIED):
            if status is CallStatus.FAILED and self._replan_budget > 0 \
                    and self._proven_not_dispatched(output):
                # One safe replan: the failure is proven predispatch, so a
                # single fresh plan may follow. Any dispatched or uncertain
                # outcome still stops the chain.
                self._replan_budget -= 1
                self._failed_shapes.add(self._plan_shape(entry.call))
            else:
                self._mutation_chain_closed = True
        entry.status = status
        entry.output = output
        cmds: list[Command] = [SendToolResult(call_id, ok, output)]
        cmds.extend(self._maybe_continue())
        self._refresh_phase()
        return cmds

    def _tool_finished(self, ev: ToolFinished) -> list[Command]:
        entry = self.ledger.get(ev.call_id)
        if entry is None or not self._completion_matches(entry.call, ev):
            return []
        status = self._status_for_result(ev)
        output = ev.output
        result_ok = ev.ok
        if self._is_computer_mutation(entry.call.name):
            receipt = self._validated_action_receipt(entry.call, ev)
            status = self._status_for_result(replace(
                ev, action_outcome=receipt.outcome, ok=receipt.ok))
            output = json.dumps(receipt.as_dict())
            result_ok = receipt.ok
        return self._resolve(ev.call_id, status, output, ok=result_ok)

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


    def _begin_response(self) -> None:
        self._response_open = True
        self._mutation_reserved = False

    def _new_turn(self) -> None:
        """Fresh turn: drop last turn's (fully resolved) ledger so stale chips
        disappear, and enter LISTENING."""
        self.ledger.clear()
        self._response_open = False
        self._batch_had_calls = False
        self._mutation_reserved = False
        self._mutation_chain_closed = False
        self._replan_budget = 1
        self._predispatch_failures = 0
        self._failed_shapes.clear()
        self.phase = Phase.LISTENING

    def _reset_turn(self) -> None:
        self.ledger.clear()
        self._response_open = False
        self._batch_had_calls = False
        self._mutation_reserved = False
        self._ptt_down_ms = None

    def _start_execution(self, call: ToolCall) -> ToolCall:
        self._execution_seq += 1
        return replace(call, execution_id=self._execution_seq)

    @staticmethod
    def _plan_shape(call: ToolCall) -> str:
        try:
            arguments = json.dumps(call.arguments, sort_keys=True, default=str)
        except (TypeError, ValueError):
            arguments = repr(call.arguments)
        return f"{call.name}:{arguments}"

    @staticmethod
    def _proven_not_dispatched(output: str) -> bool:
        try:
            payload = json.loads(output)
        except (TypeError, ValueError):
            return False
        return (isinstance(payload, dict)
                and payload.get("dispatch_state") == "not_dispatched"
                and payload.get("retry_safe") is True)

    @staticmethod
    def _is_recoverable_compile_failure(receipt: ActionReceipt | None) -> bool:
        return (receipt is not None
                and receipt.outcome is ActionOutcome.FAILED
                and receipt.dispatch_state is DispatchState.NOT_DISPATCHED
                and receipt.retry_safe)

    @staticmethod
    def _blocked_action_output(call: ToolCall, reason: str) -> str:
        return json.dumps(blocked_receipt(
            target=call.preview or call.name,
            summary=reason,
            duration_ms=0,
        ).as_dict())

    @staticmethod
    def _predispatch_failure_output(call: ToolCall, reason: str) -> str:
        return json.dumps(ActionReceipt(
            outcome=ActionOutcome.FAILED,
            dispatch_state=DispatchState.NOT_DISPATCHED,
            strategy="approval_gate",
            lane="semantic",
            target=call.preview or call.name,
            effect="action was not dispatched",
            evidence=(ActionEvidence(
                kind="approval_gate",
                summary=reason,
                matched=False,
            ),),
            retry_safe=False,
            duration_ms=0,
            data={"error": reason},
        ).as_dict())

    @staticmethod
    def _prepared_failure_receipt(call: ToolCall) -> ActionReceipt | None:
        if not isinstance(call.prepared_failure, dict):
            return None
        try:
            receipt = ActionReceipt.from_dict(call.prepared_failure)
        except (KeyError, TypeError, ValueError):
            return None
        if (
            receipt.outcome
            not in {
                ActionOutcome.AMBIGUOUS,
                ActionOutcome.BLOCKED,
                ActionOutcome.FAILED,
            }
            or receipt.dispatch_state is not DispatchState.NOT_DISPATCHED
            or receipt.ok
        ):
            return None
        return receipt

    @staticmethod
    def _validated_action_receipt(
        call: ToolCall, result: ToolFinished
    ) -> ActionReceipt:
        try:
            payload = json.loads(result.output)
        except (TypeError, ValueError):
            payload = None
        if isinstance(payload, dict) and result.action_outcome is not None:
            try:
                receipt = ActionReceipt.from_dict(payload)
            except (KeyError, TypeError, ValueError):
                receipt = None
            if receipt is not None and receipt.outcome is result.action_outcome:
                return receipt

        target = call.preview or call.name
        duration_ms = (
            payload.get("duration_ms", 0)
            if isinstance(payload, dict)
            and isinstance(payload.get("duration_ms", 0), int)
            else 0
        )
        strategy = (
            payload.get("strategy")
            if isinstance(payload, dict)
            and isinstance(payload.get("strategy"), str)
            else "unclassified_executor_result"
        )
        summary = (
            payload.get("error")
            if isinstance(payload, dict)
            and isinstance(payload.get("error"), str)
            else "executor returned no valid action receipt"
        )
        match result.action_outcome:
            case ActionOutcome.NO_EFFECT:
                return ActionReceipt(
                    outcome=ActionOutcome.NO_EFFECT,
                    dispatch_state=DispatchState.DISPATCHED,
                    strategy=strategy,
                    lane="semantic",
                    target=target,
                    effect="requested effect was not observed",
                    evidence=(ActionEvidence(
                        kind="effect_observation",
                        summary=summary,
                        matched=False,
                    ),),
                    retry_safe=False,
                    duration_ms=duration_ms,
                    data={"error": summary},
                )
            case ActionOutcome.AMBIGUOUS:
                data = payload if isinstance(payload, dict) else {"error": summary}
                return ambiguous_receipt(
                    target=target, data=data, duration_ms=duration_ms)
            case ActionOutcome.BLOCKED:
                return blocked_receipt(
                    target=target, summary=summary, duration_ms=duration_ms)
            case ActionOutcome.FAILED:
                return uncertain_failure_receipt(
                    target=target,
                    strategy=strategy,
                    duration_ms=duration_ms,
                    summary=summary,
                )
            case ActionOutcome.VERIFIED | ActionOutcome.DISPATCH_ONLY | None:
                if result.action_outcome is None and not result.ok:
                    return uncertain_failure_receipt(
                        target=target,
                        strategy=strategy,
                        duration_ms=duration_ms,
                        summary=summary,
                    )
                return dispatch_only_receipt(
                    target=target,
                    strategy=strategy,
                    duration_ms=duration_ms,
                )

    @staticmethod
    def _completion_matches(call: ToolCall, result: ToolFinished) -> bool:
        return (
            result.execution_id is not None
            and result.turn_id == call.turn_id
            and result.response_epoch == call.response_epoch
            and result.observation_epoch == call.observation_epoch
            and result.execution_id == call.execution_id
        )

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
