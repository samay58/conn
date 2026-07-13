import dataclasses
import json

import pytest

from conn.actions import ActionOutcome, preparation_failure_receipt
from conn.events import (
    ApprovalDecision,
    ApprovalTimeout,
    ExecTool,
    Gate,
    SendToolResult,
    ToolCall,
    ToolFinished,
    ToolProposed,
)
from conn.state import CallStatus, Phase, SessionStateMachine
from conn.tools.registry import build_registry, computer_mutation_names


MUTATIONS = computer_mutation_names(build_registry())


ACTION_RECEIPT_FIELDS = {
    "outcome",
    "ok",
    "dispatch_state",
    "strategy",
    "lane",
    "target",
    "effect",
    "evidence",
    "retry_safe",
    "duration_ms",
}


def test_state_machine_requires_injected_mutation_policy() -> None:
    with pytest.raises(TypeError, match="computer_mutations"):
        SessionStateMachine()


def assert_predispatch_receipt(command: SendToolResult, outcome: str) -> dict:
    payload = json.loads(command.output)
    assert ACTION_RECEIPT_FIELDS <= payload.keys()
    assert payload["outcome"] == outcome
    assert payload["ok"] is False
    assert payload["dispatch_state"] == "not_dispatched"
    return payload


def sent_result(commands) -> SendToolResult:
    return next(command for command in commands if isinstance(command, SendToolResult))


def confirm_call(call_id: str = "confirm") -> ToolCall:
    return ToolCall(
        call_id=call_id,
        name="app_menu",
        arguments={"path": ["File", "Close"]},
        gate=Gate.CONFIRM,
        preview="Use menu: File > Close",
    )


def test_user_denial_serializes_as_blocked_outcome() -> None:
    machine = SessionStateMachine(computer_mutations=MUTATIONS)
    machine.phase = Phase.THINKING
    machine.handle(ToolProposed(confirm_call()))

    result = sent_result(machine.handle(
        ApprovalDecision(call_id="confirm", approved=False)))

    assert machine.snapshot()["last_action_outcome"] == "blocked"
    assert_predispatch_receipt(result, "blocked")


def test_approval_timeout_serializes_as_failed_outcome() -> None:
    machine = SessionStateMachine(computer_mutations=MUTATIONS)
    machine.phase = Phase.THINKING
    machine.handle(ToolProposed(confirm_call()))

    result = sent_result(machine.handle(ApprovalTimeout(call_id="confirm")))

    assert machine.snapshot()["last_action_outcome"] == "failed"
    assert_predispatch_receipt(result, "failed")


def test_policy_and_sequential_refusals_use_full_action_receipts() -> None:
    policy_machine = SessionStateMachine(computer_mutations=MUTATIONS)
    policy_machine.phase = Phase.THINKING
    policy_result = sent_result(policy_machine.handle(ToolProposed(ToolCall(
        "policy", "app_switch", {}, Gate.BLOCKED, "Switch app",
        block_reason="blocked_by_policy",
    ))))
    policy_payload = assert_predispatch_receipt(policy_result, "blocked")
    assert policy_payload["error"] == "blocked_by_policy"

    sequential_machine = SessionStateMachine(computer_mutations=MUTATIONS)
    sequential_machine.phase = Phase.THINKING
    sequential_machine.handle(ToolProposed(ToolCall(
        "first", "app_switch", {}, Gate.AUTO, "Switch app")))
    sequential_result = sent_result(sequential_machine.handle(ToolProposed(ToolCall(
        "second", "app_menu", {}, Gate.AUTO, "Use menu")))
    )
    sequential_payload = assert_predispatch_receipt(sequential_result, "blocked")
    assert "sequential_action_required" in sequential_payload["error"]


def test_prepared_ambiguity_preserves_ambiguous_outcome() -> None:
    machine = SessionStateMachine(computer_mutations=MUTATIONS)
    machine.phase = Phase.THINKING
    prepared_failure = preparation_failure_receipt(
        outcome="ambiguous",
        target="Open settings",
        summary="target_ambiguous",
    ).as_dict()

    result = sent_result(machine.handle(ToolProposed(ToolCall(
        "ambiguous",
        "computer_click",
        {},
        Gate.BLOCKED,
        "Open settings",
        block_reason="target_ambiguous",
        prepared_failure=prepared_failure,
    ))))

    payload = json.loads(result.output)
    assert payload["outcome"] == "ambiguous"
    assert payload["dispatch_state"] == "not_dispatched"
    assert payload["retry_safe"] is True
    assert machine.ledger["ambiguous"].status is CallStatus.AMBIGUOUS


@pytest.mark.parametrize(("outcome", "ok"), [
    (ActionOutcome.DISPATCH_ONLY, False),
    (ActionOutcome.NO_EFFECT, False),
    (ActionOutcome.AMBIGUOUS, False),
    (ActionOutcome.BLOCKED, False),
    (ActionOutcome.FAILED, False),
    (None, True),
])
def test_every_nonverified_mutation_outcome_closes_chain(
        outcome: ActionOutcome | None, ok: bool) -> None:
    machine = SessionStateMachine(computer_mutations=MUTATIONS)
    machine.phase = Phase.THINKING
    [command] = machine.handle(ToolProposed(ToolCall(
        "first", "app_switch", {}, Gate.AUTO, "Switch app")))
    running = command.call

    machine.handle(ToolFinished(
        call_id=running.call_id,
        ok=ok,
        output="{}",
        action_outcome=outcome,
        turn_id=running.turn_id,
        response_epoch=running.response_epoch,
        observation_epoch=running.observation_epoch,
        execution_id=running.execution_id,
    ))
    commands = machine.handle(ToolProposed(ToolCall(
        "second", "app_switch", {}, Gate.AUTO, "Switch app")))

    assert not any(isinstance(command, ExecTool) for command in commands)
    assert machine.ledger["second"].status is CallStatus.BLOCKED


@pytest.mark.parametrize(("field", "value"), [
    ("turn_id", "wrong_turn"),
    ("response_epoch", 9),
    ("observation_epoch", 9),
    ("execution_id", 9),
])
def test_completion_identity_must_match_in_every_dimension(
        field: str, value: str | int) -> None:
    machine = SessionStateMachine(computer_mutations=MUTATIONS)
    machine.phase = Phase.THINKING
    [command] = machine.handle(ToolProposed(ToolCall(
        "call", "app_switch", {}, Gate.AUTO, "Switch app",
        turn_id="turn", response_epoch=1, observation_epoch=2)))
    running = command.call
    result = ToolFinished(
        call_id=running.call_id,
        ok=True,
        output="{}",
        action_outcome=ActionOutcome.VERIFIED,
        turn_id=running.turn_id,
        response_epoch=running.response_epoch,
        observation_epoch=running.observation_epoch,
        execution_id=running.execution_id,
    )

    assert machine.handle(dataclasses.replace(result, **{field: value})) == []
    assert machine.ledger["call"].status is CallStatus.RUNNING


def test_mutation_without_action_outcome_is_unverified_not_success() -> None:
    machine = SessionStateMachine(computer_mutations=MUTATIONS)
    machine.phase = Phase.THINKING
    [command] = machine.handle(ToolProposed(ToolCall(
        "call", "app_switch", {}, Gate.AUTO, "Switch app")))
    running = command.call

    result = sent_result(machine.handle(ToolFinished(
        call_id=running.call_id,
        ok=True,
        output='{"ok":true}',
        turn_id=running.turn_id,
        response_epoch=running.response_epoch,
        observation_epoch=running.observation_epoch,
        execution_id=running.execution_id,
    )))

    assert machine.ledger["call"].status is CallStatus.UNVERIFIED
    assert machine.snapshot()["last_action_outcome"] == "dispatch_only"
    payload = json.loads(result.output)
    assert ACTION_RECEIPT_FIELDS <= payload.keys()
    assert payload["outcome"] == "dispatch_only"
    assert payload["ok"] is False
    assert payload["dispatch_state"] == "dispatched"
    assert result.ok is False


def test_nonverified_action_outcome_forces_model_visible_ok_false() -> None:
    machine = SessionStateMachine(computer_mutations=MUTATIONS)
    machine.phase = Phase.THINKING
    [command] = machine.handle(ToolProposed(ToolCall(
        "call", "app_switch", {}, Gate.AUTO, "Switch app")))
    running = command.call

    result = sent_result(machine.handle(ToolFinished(
        call_id=running.call_id,
        ok=True,
        output='{"ok":true,"outcome":"dispatch_only"}',
        action_outcome=ActionOutcome.DISPATCH_ONLY,
        turn_id=running.turn_id,
        response_epoch=running.response_epoch,
        observation_epoch=running.observation_epoch,
        execution_id=running.execution_id,
    )))

    assert result.ok is False


def test_verified_enum_without_receipt_evidence_is_downgraded() -> None:
    machine = SessionStateMachine(computer_mutations=MUTATIONS)
    machine.phase = Phase.THINKING
    [command] = machine.handle(ToolProposed(ToolCall(
        "call", "app_switch", {}, Gate.AUTO, "Switch app")))
    running = command.call

    result = sent_result(machine.handle(ToolFinished(
        call_id=running.call_id,
        ok=True,
        output='{"ok":true}',
        action_outcome=ActionOutcome.VERIFIED,
        turn_id=running.turn_id,
        response_epoch=running.response_epoch,
        observation_epoch=running.observation_epoch,
        execution_id=running.execution_id,
    )))

    payload = json.loads(result.output)
    assert result.ok is False
    assert payload["outcome"] == "dispatch_only"
    assert machine.ledger["call"].status is CallStatus.UNVERIFIED
