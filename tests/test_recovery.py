"""R6 bounded recovery: one replan only after proven not_dispatched, compile
failures do not consume the dispatch budget, identical failed plan shapes
never run twice in a turn, and every receipt carries a safe spoken reason.
"""

from __future__ import annotations

import json

from conn.actions import (
    ActionOutcome, ActionReceipt, DispatchState, ambiguous_receipt,
    blocked_receipt, not_dispatched_failure_receipt, preparation_failure_receipt,
    uncertain_failure_receipt,
)
from conn.events import (
    ExecTool, Gate, PttDown, PttUp, ResponseDone, SendToolResult, ToolCall,
    ToolFinished, ToolProposed,
)
from conn.state import Phase, SessionStateMachine

MUTATIONS = frozenset({"computer_create", "app_open", "computer_click"})


def machine() -> SessionStateMachine:
    m = SessionStateMachine(computer_mutations=MUTATIONS)
    m.handle(PttDown(ts_ms=1000))
    m.handle(PttUp(ts_ms=2000, voiced=True))
    assert m.phase is Phase.THINKING
    return m


def call(call_id: str, name: str = "computer_create", args: dict | None = None,
         gate: Gate = Gate.AUTO) -> ToolCall:
    return ToolCall(call_id=call_id, name=name,
                    arguments=args or {"kind": "tab"}, gate=gate,
                    preview="Create a new tab")


def finish(m: SessionStateMachine, proposed: ToolCall, receipt: ActionReceipt):
    entry = m.ledger[proposed.call_id]
    return m.handle(ToolFinished(
        call_id=proposed.call_id, ok=receipt.ok,
        output=json.dumps(receipt.as_dict()),
        action_outcome=receipt.outcome,
        turn_id=entry.call.turn_id, response_epoch=entry.call.response_epoch,
        observation_epoch=entry.call.observation_epoch,
        execution_id=entry.call.execution_id,
    ))


def not_dispatched() -> ActionReceipt:
    return not_dispatched_failure_receipt(
        target="New Tab", strategy="native_bridge", duration_ms=5,
        summary="stale_snapshot")


class TestReplanBudget:
    def test_one_replan_allowed_after_proven_not_dispatched(self):
        m = machine()
        first = call("c1", args={"kind": "tab"})
        m.handle(ToolProposed(first))
        finish(m, first, not_dispatched())
        m.handle(ResponseDone(had_tool_calls=True))
        # fresh response proposes a different plan shape: allowed once
        second = call("c2", args={"kind": "window"})
        cmds = m.handle(ToolProposed(second))
        assert any(isinstance(c, ExecTool) for c in cmds), (
            "one replan after not_dispatched must execute")

    def test_second_replan_is_refused(self):
        m = machine()
        first = call("c1", args={"kind": "tab"})
        m.handle(ToolProposed(first))
        finish(m, first, not_dispatched())
        m.handle(ResponseDone(had_tool_calls=True))
        second = call("c2", args={"kind": "window"})
        m.handle(ToolProposed(second))
        finish(m, second, not_dispatched())
        m.handle(ResponseDone(had_tool_calls=True))
        third = call("c3", args={"kind": "note"})
        cmds = m.handle(ToolProposed(third))
        assert not any(isinstance(c, ExecTool) for c in cmds)
        assert "mutation_chain_closed" in (m.ledger["c3"].output or "")

    def test_no_replan_after_possible_dispatch(self):
        m = machine()
        first = call("c1")
        m.handle(ToolProposed(first))
        finish(m, first, uncertain_failure_receipt(
            target="New Tab", strategy="native_bridge", duration_ms=5,
            summary="bridge timeout"))
        m.handle(ResponseDone(had_tool_calls=True))
        second = call("c2", args={"kind": "window"})
        cmds = m.handle(ToolProposed(second))
        assert not any(isinstance(c, ExecTool) for c in cmds)

    def test_no_replan_after_dispatch_without_effect(self):
        m = machine()
        first = call("c1")
        m.handle(ToolProposed(first))
        finish(m, first, ActionReceipt(
            outcome=ActionOutcome.NO_EFFECT,
            dispatch_state=DispatchState.DISPATCHED,
            strategy="ax_menu_action", lane="semantic", target="New Tab",
            effect="requested effect was not observed",
            evidence=(), retry_safe=False, duration_ms=900,
            reason_code="witness_not_matched",
        ))
        m.handle(ResponseDone(had_tool_calls=True))
        second = call("c2", args={"kind": "window"})
        cmds = m.handle(ToolProposed(second))
        assert not any(isinstance(c, ExecTool) for c in cmds)

    def test_ambiguity_stops_for_clarification_not_replan(self):
        m = machine()
        first = call("c1")
        m.handle(ToolProposed(first))
        finish(m, first, ambiguous_receipt(
            target="Save button", data={"candidates": ["Save", "Save All"]},
            duration_ms=4))
        m.handle(ResponseDone(had_tool_calls=True))
        second = call("c2", args={"kind": "window"})
        cmds = m.handle(ToolProposed(second))
        assert not any(isinstance(c, ExecTool) for c in cmds), (
            "ambiguity asks one question; it never replans in the same turn")


class TestRepeatedPlanShapes:
    def test_identical_failed_shape_is_refused(self):
        m = machine()
        first = call("c1", args={"kind": "tab"})
        m.handle(ToolProposed(first))
        finish(m, first, not_dispatched())
        m.handle(ResponseDone(had_tool_calls=True))
        repeat = call("c2", args={"kind": "tab"})
        cmds = m.handle(ToolProposed(repeat))
        assert not any(isinstance(c, ExecTool) for c in cmds)
        output = m.ledger["c2"].output or ""
        assert "repeated_plan_shape" in output

    def test_fresh_turn_clears_failed_shapes(self):
        m = machine()
        first = call("c1", args={"kind": "tab"})
        m.handle(ToolProposed(first))
        finish(m, first, not_dispatched())
        m.handle(ResponseDone(had_tool_calls=True))
        m.handle(ResponseDone(had_tool_calls=False))  # continuation settles
        m.handle(PttDown(ts_ms=60_000))
        m.handle(PttUp(ts_ms=61_000, voiced=True))
        again = call("c9", args={"kind": "tab"})
        cmds = m.handle(ToolProposed(again))
        assert any(isinstance(c, ExecTool) for c in cmds)

    def test_ephemeral_native_refs_do_not_bypass_the_shape_limit(self):
        m = machine()
        first = ToolCall(
            call_id="c1", name="computer_click",
            arguments={"snapshot_id": "snapshot-old", "ref": "node-old"},
            gate=Gate.AUTO, preview="Press RIVER",
            prepared_plan={
                "target_fingerprint": "river-fingerprint",
                "target_role": "AXLink",
                "authorized_strategies": ["ax_press"],
                "risk": "navigation",
            },
        )
        m.handle(ToolProposed(first))
        finish(m, first, not_dispatched_failure_receipt(
            target="RIVER", strategy="native_bridge", duration_ms=2,
            summary="stale_snapshot",
        ))
        m.handle(ResponseDone(had_tool_calls=True))
        second = ToolCall(
            call_id="c2", name="computer_click",
            arguments={"snapshot_id": "snapshot-new", "ref": "node-new"},
            gate=Gate.AUTO, preview="Press RIVER",
            prepared_plan={
                "target_fingerprint": "river-fingerprint",
                "target_role": "AXLink",
                "authorized_strategies": ["ax_press"],
                "risk": "navigation",
            },
        )

        commands = m.handle(ToolProposed(second))

        assert not any(isinstance(command, ExecTool) for command in commands)
        assert "repeated_plan_shape" in (m.ledger["c2"].output or "")

    def test_ambiguous_mutation_closes_further_grounding_reads(self):
        m = machine()
        first = call("c1")
        m.handle(ToolProposed(first))
        finish(m, first, ambiguous_receipt(
            target="RIVER",
            data={"candidates": ["RIVER in header", "RIVER in sidebar"]},
            duration_ms=2,
        ))
        read = ToolCall(
            call_id="look-again",
            name="computer_ax_snapshot",
            arguments={"query": "RIVER", "ancestor_ref": "new-node-id"},
            gate=Gate.AUTO,
            preview="Read accessibility snapshot",
        )

        commands = m.handle(ToolProposed(read))

        assert not any(isinstance(command, ExecTool) for command in commands)
        assert "clarification_exhausted" in (m.ledger["look-again"].output or "")


class TestGroundingReadBudget:
    @staticmethod
    def _read(call_id: str) -> ToolCall:
        return ToolCall(
            call_id=call_id,
            name="computer_ax_snapshot",
            arguments={"query": "Play"},
            gate=Gate.AUTO,
            preview="Read accessibility snapshot",
        )

    @staticmethod
    def _finish_empty(m: SessionStateMachine, call_id: str) -> None:
        running = m.ledger[call_id].call
        m.handle(ToolFinished(
            call_id=call_id,
            ok=True,
            output='{"ok":true,"data":{"candidate_count":0,"candidates":[]}}',
            turn_id=running.turn_id,
            response_epoch=running.response_epoch,
            observation_epoch=running.observation_epoch,
            execution_id=running.execution_id,
        ))
        m.handle(ResponseDone(had_tool_calls=True))

    def test_third_grounding_read_in_one_turn_is_refused(self):
        m = machine()
        for call_id in ("read-1", "read-2"):
            proposed = self._read(call_id)
            assert any(
                isinstance(command, ExecTool)
                for command in m.handle(ToolProposed(proposed))
            )
            self._finish_empty(m, call_id)

        commands = m.handle(ToolProposed(self._read("read-3")))

        assert not any(isinstance(command, ExecTool) for command in commands)
        assert "grounding_read_limit" in (m.ledger["read-3"].output or "")

    def test_fresh_turn_restores_the_grounding_read_budget(self):
        m = machine()
        for call_id in ("read-1", "read-2"):
            m.handle(ToolProposed(self._read(call_id)))
            self._finish_empty(m, call_id)
        m.handle(ResponseDone(had_tool_calls=False))
        m.handle(PttDown(ts_ms=60_000))
        m.handle(PttUp(ts_ms=61_000, voiced=True))

        commands = m.handle(ToolProposed(self._read("fresh-read")))

        assert any(isinstance(command, ExecTool) for command in commands)


def test_ambiguity_message_uses_current_descriptor_choices_exactly():
    receipt = ambiguous_receipt(
        target="RIVER",
        data={"candidates": [
            {"descriptor": {"display": "RIVER in header navigation"}},
            {"descriptor": {"display": "RIVER in secondary navigation"}},
        ]},
        duration_ms=2,
    )

    assert receipt.safe_user_message() == (
        "I found more than one match: RIVER in header navigation, "
        "RIVER in secondary navigation. Which one?"
    )


class TestCompileFailureBudget:
    def _blocked_compile_call(self, call_id: str, kind: str) -> ToolCall:
        failure = preparation_failure_receipt(
            outcome="failed", target=f"new {kind}",
            summary="no_live_affordance")
        return ToolCall(
            call_id=call_id, name="computer_create",
            arguments={"kind": kind}, gate=Gate.BLOCKED,
            preview=f"Create a new {kind}",
            block_reason="no_live_affordance",
            prepared_failure=failure.as_dict(),
        )

    def test_compile_failure_does_not_consume_the_dispatch_budget(self):
        m = machine()
        m.handle(ToolProposed(self._blocked_compile_call("c1", "folder")))
        m.handle(ResponseDone(had_tool_calls=True))
        # the model corrects itself with a different plan: still executable
        second = call("c2", args={"kind": "tab"})
        cmds = m.handle(ToolProposed(second))
        assert any(isinstance(c, ExecTool) for c in cmds)

    def test_compile_failures_are_bounded_per_turn(self):
        m = machine()
        m.handle(ToolProposed(self._blocked_compile_call("c1", "folder")))
        m.handle(ResponseDone(had_tool_calls=True))
        m.handle(ToolProposed(self._blocked_compile_call("c2", "note")))
        m.handle(ResponseDone(had_tool_calls=True))
        m.handle(ToolProposed(self._blocked_compile_call("c3", "document")))
        m.handle(ResponseDone(had_tool_calls=True))
        fourth = call("c4", args={"kind": "tab"})
        cmds = m.handle(ToolProposed(fourth))
        assert not any(isinstance(c, ExecTool) for c in cmds)


class TestSafeUserMessages:
    def test_every_receipt_carries_a_safe_spoken_message(self):
        samples = {
            "dispatch_only": ActionReceipt(
                outcome=ActionOutcome.DISPATCH_ONLY,
                dispatch_state=DispatchState.DISPATCHED,
                strategy="ax_menu_action", lane="semantic", target="New Tab",
                effect="effect not observed", evidence=(), retry_safe=False,
                duration_ms=10, reason_code="no_trustworthy_witness",
            ),
            "possibly": uncertain_failure_receipt(
                target="t", strategy="s", duration_ms=1, summary="timeout"),
            "ambiguous": ambiguous_receipt(
                target="Save", data={"candidates": ["Save", "Save All"]},
                duration_ms=1),
            "blocked": blocked_receipt(
                target="t", summary="denied_by_user", duration_ms=1),
            "stale": not_dispatched_failure_receipt(
                target="t", strategy="s", duration_ms=1,
                summary="stale_snapshot"),
            "bridge": not_dispatched_failure_receipt(
                target="t", strategy="s", duration_ms=1,
                summary="native_app_unavailable: Conn.app required"),
        }
        messages = {key: receipt.as_dict()["safe_user_message"]
                    for key, receipt in samples.items()}
        assert messages["dispatch_only"] == (
            "I sent it, but could not confirm it worked.")
        assert messages["possibly"] == (
            "The action may have been sent. Check before retrying.")
        assert "Which one" in messages["ambiguous"]
        assert messages["stale"] == (
            "The app changed before I could act. Try again.")
        assert messages["bridge"] == (
            "Conn lost its app connection before sending anything.")
        for message in messages.values():
            for banned in ("AX", "fingerprint", "predicate", "snapshot",
                           "ref", "epoch"):
                assert banned not in message, (
                    f"internal term {banned!r} in {message!r}")

    def test_receipts_carry_a_stable_reason_code(self):
        receipt = not_dispatched_failure_receipt(
            target="t", strategy="s", duration_ms=1,
            summary="stale_snapshot: observation epoch advanced")
        assert receipt.as_dict()["reason_code"] == "stale_snapshot"
