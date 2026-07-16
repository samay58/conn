import json
import asyncio
import dataclasses
import time
import pytest

from conn.actions import (
    ActionEvidence,
    ActionOutcome,
    ActionReceipt,
    DispatchState,
)
from conn.events import Gate, ToolCall, ToolFinished, ToolProposed
from conn.state import CallStatus, SessionStateMachine
from conn.tools.registry import build_registry, computer_mutation_names


MUTATIONS = computer_mutation_names(build_registry())


def receipt(outcome: ActionOutcome, dispatch: DispatchState) -> ActionReceipt:
    return ActionReceipt(
        outcome=outcome,
        dispatch_state=dispatch,
        strategy="ax_press",
        lane="semantic",
        target="New Tab in Terminal",
        effect="window count increases by 1",
        evidence=(ActionEvidence(kind="window_count", summary="1 -> 2", matched=outcome is ActionOutcome.VERIFIED),),
        retry_safe=dispatch is DispatchState.NOT_DISPATCHED,
        duration_ms=83,
        reason_code=None if outcome is ActionOutcome.VERIFIED else "test_unverified",
    )


def test_non_verified_receipt_requires_stable_reason_code() -> None:
    with pytest.raises(ValueError, match="reason code"):
        ActionReceipt(
            outcome=ActionOutcome.DISPATCH_ONLY,
            dispatch_state=DispatchState.DISPATCHED,
            strategy="ax_press",
            lane="semantic",
            target="button",
            effect="effect not observed",
            evidence=(ActionEvidence(
                kind="dispatch_return",
                summary="request accepted",
                matched=False,
            ),),
            retry_safe=False,
            duration_ms=1,
        )


def test_mutation_ok_is_true_only_for_verified() -> None:
    verified = receipt(ActionOutcome.VERIFIED, DispatchState.DISPATCHED)
    unverified = receipt(ActionOutcome.DISPATCH_ONLY, DispatchState.DISPATCHED)

    assert verified.ok is True
    assert unverified.ok is False
    assert unverified.as_dict()["outcome"] == "dispatch_only"
    assert unverified.as_dict()["evidence"] == [
        {"kind": "window_count", "summary": "1 -> 2", "matched": False}
    ]


def test_verified_receipt_requires_dispatched_matched_evidence() -> None:
    with pytest.raises(ValueError, match="matched effect evidence"):
        ActionReceipt(
            outcome=ActionOutcome.VERIFIED,
            dispatch_state=DispatchState.DISPATCHED,
            strategy="raw_executor",
            lane="semantic",
            target="button",
            effect="unknown",
            evidence=(),
            retry_safe=False,
            duration_ms=1,
        )


def test_retry_safe_requires_proven_not_dispatched() -> None:
    with pytest.raises(ValueError, match="not dispatched"):
        ActionReceipt(
            outcome=ActionOutcome.FAILED,
            dispatch_state=DispatchState.DISPATCHED,
            strategy="ax_press",
            lane="semantic",
            target="button",
            effect="unknown",
            evidence=(ActionEvidence(
                kind="dispatch_return",
                summary="request accepted",
                matched=False,
            ),),
            retry_safe=True,
            duration_ms=1,
        )


@pytest.mark.parametrize("field", ["matched", "retry_safe"])
def test_wire_boolean_strings_are_rejected(field: str) -> None:
    payload = {
        "outcome": "verified",
        "dispatch_state": "dispatched",
        "strategy": "ax_press",
        "lane": "semantic",
        "target": "button",
        "effect": "value changes",
        "evidence": [{"predicate": "value", "matched": True}],
        "retry_safe": False,
        "duration_ms": 1,
    }
    if field == "matched":
        payload["evidence"][0]["matched"] = "false"
    else:
        payload["retry_safe"] = "false"

    with pytest.raises(ValueError, match="must be a boolean"):
        ActionReceipt.from_dict(payload)


@pytest.mark.parametrize(("outcome", "dispatch_state"), [
    (ActionOutcome.DISPATCH_ONLY, DispatchState.NOT_DISPATCHED),
    (ActionOutcome.NO_EFFECT, DispatchState.POSSIBLY_DISPATCHED),
    (ActionOutcome.BLOCKED, DispatchState.DISPATCHED),
    (ActionOutcome.AMBIGUOUS, DispatchState.POSSIBLY_DISPATCHED),
])
def test_outcome_rejects_impossible_dispatch_state(
    outcome: ActionOutcome, dispatch_state: DispatchState
) -> None:
    with pytest.raises(ValueError, match="dispatch state"):
        ActionReceipt(
            outcome=outcome,
            dispatch_state=dispatch_state,
            strategy="semantic",
            lane="semantic",
            target="button",
            effect="bounded effect",
            evidence=(ActionEvidence(
                kind="state",
                summary="not matched",
                matched=False,
            ),),
            retry_safe=False,
            duration_ms=1,
        )


def test_unverified_tool_result_never_becomes_completed() -> None:
    machine = SessionStateMachine(computer_mutations=MUTATIONS)
    machine.phase = machine.phase.THINKING
    call = ToolCall("call_1", "app_menu", {"path": ["Shell", "New Tab"]}, Gate.AUTO, "Open tab")
    [command] = machine.handle(ToolProposed(call))
    running = command.call
    action_receipt = receipt(ActionOutcome.DISPATCH_ONLY, DispatchState.DISPATCHED)

    machine.handle(ToolFinished(
        call_id="call_1",
        ok=False,
        output=json.dumps(action_receipt.as_dict()),
        action_outcome=ActionOutcome.DISPATCH_ONLY,
        turn_id=running.turn_id,
        response_epoch=running.response_epoch,
        observation_epoch=running.observation_epoch,
        execution_id=running.execution_id,
    ))

    assert machine.ledger["call_1"].status is CallStatus.UNVERIFIED
    assert machine.snapshot()["last_action_outcome"] == "dispatch_only"


def test_verified_tool_result_has_verified_status() -> None:
    machine = SessionStateMachine(computer_mutations=MUTATIONS)
    machine.phase = machine.phase.THINKING
    call = ToolCall("call_1", "app_switch", {"app": "Safari"}, Gate.AUTO, "Switch to Safari")
    [command] = machine.handle(ToolProposed(call))
    running = command.call
    action_receipt = receipt(ActionOutcome.VERIFIED, DispatchState.DISPATCHED)

    machine.handle(ToolFinished(
        call_id="call_1",
        ok=True,
        output=json.dumps(action_receipt.as_dict()),
        action_outcome=ActionOutcome.VERIFIED,
        turn_id=running.turn_id,
        response_epoch=running.response_epoch,
        observation_epoch=running.observation_epoch,
        execution_id=running.execution_id,
    ))

    assert machine.ledger["call_1"].status is CallStatus.VERIFIED
    assert machine.snapshot()["last_action_outcome"] == "verified"


def test_executor_success_without_evidence_is_dispatch_only(harness) -> None:
    harness._executors = {"app_switch": lambda args, ctx: {"activated": True}}
    call = harness.gate("call_1", "app_switch", '{"app": "Safari"}')

    result = asyncio.run(harness.run(call))
    payload = json.loads(result.output)

    assert result.ok is False
    assert result.action_outcome is ActionOutcome.DISPATCH_ONLY
    assert payload["outcome"] == "dispatch_only"
    assert payload["dispatch_state"] == "dispatched"
    assert payload["retry_safe"] is False


def test_mutation_timeout_keeps_worker_owned_until_terminal_result(harness) -> None:
    effects: list[str] = []

    def delayed(args, ctx):
        time.sleep(0.05)
        effects.append("dispatched")
        return {"activated": True}

    harness._executors = {"app_switch": delayed}
    harness.registry["app_switch"] = dataclasses.replace(
        harness.registry["app_switch"], timeout_s=0.01
    )
    call = harness.gate("call_1", "app_switch", '{"app": "Safari"}')

    started = time.monotonic()
    result = asyncio.run(harness.run(call))
    elapsed = time.monotonic() - started
    payload = json.loads(result.output)

    assert elapsed >= 0.04
    assert effects == ["dispatched"]
    assert payload["outcome"] == "dispatch_only"
    assert payload["retry_safe"] is False


def test_mutation_executor_error_is_never_retry_safe(harness) -> None:
    def failed(args, ctx):
        raise RuntimeError("native connection lost after send")

    harness._executors = {"app_switch": failed}
    call = harness.gate("call_1", "app_switch", '{"app": "Safari"}')

    result = asyncio.run(harness.run(call))
    payload = json.loads(result.output)

    assert result.ok is False
    assert payload["outcome"] == "failed"
    assert payload["dispatch_state"] == "possibly_dispatched"
    assert payload["retry_safe"] is False
