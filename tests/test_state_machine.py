import pytest

from conn.events import (
    ApprovalDecision, ApprovalTimeout, BudgetOverride, BudgetTripped,
    CancelResponse, ClearInput, CloseMic, CommitInput, CreateResponse,
    EndSession, ExecTool, FlushPlayback, Gate, ModelSpeaking, OpenMic,
    PlaybackDrained, PttDown, PttUp, QueueApproval, ResetTick, ResponseDone,
    RejectInput, SendText, SendToolResult, TextCommand, ToolCall, ToolFinished,
    UserStop, WsFailed, WsReconnected,
)
from conn.state import CallStatus, Phase, SessionStateMachine
from conn.tools.registry import build_registry, computer_mutation_names


MUTATIONS = computer_mutation_names(build_registry())


def call(call_id="c1", gate=Gate.AUTO, name="app_open"):
    return ToolCall(call_id=call_id, name=name, arguments={"app": "Obsidian"},
                    gate=gate, preview="Open app: Obsidian")


def kinds(cmds):
    return [type(c).__name__ for c in cmds]


def finished(m, call_id="c1", *, ok=True, output="{}"):
    running = m.ledger[call_id].call
    return ToolFinished(
        call_id=call_id,
        ok=ok,
        output=output,
        turn_id=running.turn_id,
        response_epoch=running.response_epoch,
        observation_epoch=running.observation_epoch,
        execution_id=running.execution_id,
    )


@pytest.fixture
def m():
    return SessionStateMachine(computer_mutations=MUTATIONS)


def start_turn(m, t0=1000, t1=2000):
    m.handle(PttDown(ts_ms=t0))
    return m.handle(PttUp(ts_ms=t1))


class TestPtt:
    def test_ptt_down_from_idle_opens_mic(self, m):
        cmds = m.handle(PttDown(ts_ms=1000))
        assert m.phase is Phase.LISTENING
        assert kinds(cmds) == ["ClearInput", "OpenMic"]

    def test_short_tap_aborts_with_zero_spend(self, m):
        m.handle(PttDown(ts_ms=1000))
        cmds = m.handle(PttUp(ts_ms=1150))
        assert m.phase is Phase.IDLE
        assert kinds(cmds) == ["AckTurn", "CloseMic", "ClearInput"]
        assert not any(isinstance(c, (CommitInput, CreateResponse)) for c in cmds)

    def test_real_press_commits_and_creates_response(self, m):
        cmds = start_turn(m)
        assert m.phase is Phase.THINKING
        assert kinds(cmds) == ["AckTurn", "CloseMic", "CommitInput", "CreateResponse"]

    def test_ptt_down_rejected_while_thinking_and_acting(self, m):
        start_turn(m)
        assert m.handle(PttDown()) == [RejectInput(reason=Phase.THINKING.value)]
        m.handle(ToolProposedFactory())
        assert m.phase is Phase.ACTING
        assert m.handle(PttDown()) == [RejectInput(reason=Phase.ACTING.value)]

    def test_ptt_up_ignored_outside_listening(self, m):
        assert m.handle(PttUp()) == []


def ToolProposedFactory(call_id="c1", gate=Gate.AUTO, name="app_open"):
    from conn.events import ToolProposed
    return ToolProposed(call=call(call_id=call_id, gate=gate, name=name))


class TestTextInput:
    def test_text_from_idle(self, m):
        cmds = m.handle(TextCommand(text="open obsidian"))
        assert m.phase is Phase.THINKING
        assert kinds(cmds) == ["SendText", "CreateResponse"]
        assert cmds[0].text == "open obsidian"

    def test_text_ignored_mid_turn(self, m):
        start_turn(m)
        assert m.handle(TextCommand(text="another")) == []


class TestAutoTool:
    def test_auto_tool_executes_immediately(self, m):
        start_turn(m)
        cmds = m.handle(ToolProposedFactory())
        assert m.phase is Phase.ACTING
        assert kinds(cmds) == ["ExecTool"]

    def test_tool_finishes_before_response_done_waits_for_close(self, m):
        start_turn(m)
        m.handle(ToolProposedFactory())
        cmds = m.handle(finished(m, output='{"ok": true}'))
        assert kinds(cmds) == ["SendToolResult"]  # response still open: no continuation
        cmds = m.handle(ResponseDone(had_tool_calls=True))
        assert kinds(cmds) == ["CreateResponse"]
        assert m.phase is Phase.THINKING

    def test_tool_finishes_after_response_done_continues_once(self, m):
        start_turn(m)
        m.handle(ToolProposedFactory())
        assert m.handle(ResponseDone(had_tool_calls=True)) == []
        cmds = m.handle(finished(m, output='{"ok": true}'))
        assert kinds(cmds) == ["SendToolResult", "CreateResponse"]
        assert m.phase is Phase.THINKING

    def test_duplicate_finish_is_noop(self, m):
        start_turn(m)
        m.handle(ToolProposedFactory())
        m.handle(ResponseDone(had_tool_calls=True))
        m.handle(finished(m))
        assert m.handle(finished(m)) == []

    def test_multi_call_single_continuation(self, m):
        start_turn(m)
        m.handle(ToolProposedFactory("c1", name="computer_get_context"))
        m.handle(ToolProposedFactory("c2", name="computer_get_context"))
        m.handle(ResponseDone(had_tool_calls=True))
        first = m.handle(finished(m, "c1"))
        assert kinds(first) == ["SendToolResult"]  # c2 still unresolved
        second = m.handle(finished(m, "c2"))
        assert kinds(second) == ["SendToolResult", "CreateResponse"]


class TestApproval:
    def test_confirm_tool_queues_chip(self, m):
        start_turn(m)
        cmds = m.handle(ToolProposedFactory(gate=Gate.CONFIRM))
        assert m.phase is Phase.AWAITING_APPROVAL
        assert kinds(cmds) == ["QueueApproval"]

    def test_approve_runs_tool(self, m):
        start_turn(m)
        m.handle(ToolProposedFactory(gate=Gate.CONFIRM))
        cmds = m.handle(ApprovalDecision(call_id="c1", approved=True))
        assert kinds(cmds) == ["ExecTool"]
        assert m.phase is Phase.ACTING

    def test_deny_resolves_with_denial(self, m):
        start_turn(m)
        m.handle(ToolProposedFactory(gate=Gate.CONFIRM))
        m.handle(ResponseDone(had_tool_calls=True))
        cmds = m.handle(ApprovalDecision(call_id="c1", approved=False))
        assert kinds(cmds) == ["SendToolResult", "CreateResponse"]
        assert cmds[0].ok is False
        assert "denied_by_user" in cmds[0].output

    def test_timeout_resolves_as_timeout(self, m):
        start_turn(m)
        m.handle(ToolProposedFactory(gate=Gate.CONFIRM))
        m.handle(ResponseDone(had_tool_calls=True))
        cmds = m.handle(ApprovalTimeout(call_id="c1"))
        assert "approval_timeout" in cmds[0].output
        assert m.ledger["c1"].status is CallStatus.TIMEOUT

    def test_decision_on_unknown_call_is_noop(self, m):
        start_turn(m)
        assert m.handle(ApprovalDecision(call_id="ghost", approved=True)) == []

    def test_mixed_gates_approval_takes_display_priority(self, m):
        start_turn(m)
        m.handle(ToolProposedFactory("c1", gate=Gate.AUTO, name="computer_get_context"))
        m.handle(ToolProposedFactory("c2", gate=Gate.CONFIRM, name="computer_get_context"))
        assert m.phase is Phase.AWAITING_APPROVAL
        m.handle(ApprovalDecision(call_id="c2", approved=True))
        assert m.phase is Phase.ACTING


class TestBlocked:
    def test_blocked_tool_auto_denies(self, m):
        start_turn(m)
        cmds = m.handle(ToolProposedFactory(gate=Gate.BLOCKED))
        assert kinds(cmds) == ["SendToolResult"]
        assert cmds[0].ok is False
        assert "blocked_by_policy" in cmds[0].output
        cmds = m.handle(ResponseDone(had_tool_calls=True))
        assert kinds(cmds) == ["CreateResponse"]


class TestSpeakingAndDone:
    def test_plain_answer_lifecycle(self, m):
        start_turn(m)
        m.handle(ModelSpeaking())
        assert m.phase is Phase.SPEAKING
        m.handle(ResponseDone(had_tool_calls=False))
        m.handle(PlaybackDrained())
        assert m.phase is Phase.DONE
        m.handle(ResetTick())
        assert m.phase is Phase.IDLE

    def test_text_only_response_goes_straight_to_done(self, m):
        m.handle(TextCommand(text="what app am I in"))
        m.handle(ResponseDone(had_tool_calls=False))
        assert m.phase is Phase.DONE

    def test_barge_in_cancels_and_reopens_mic(self, m):
        start_turn(m)
        m.handle(ModelSpeaking())
        cmds = m.handle(PttDown(ts_ms=5000))
        assert m.phase is Phase.LISTENING
        assert kinds(cmds) == ["CancelResponse", "FlushPlayback", "ClearInput", "OpenMic"]

    def test_new_turn_clears_previous_ledger(self, m):
        start_turn(m)
        m.handle(ToolProposedFactory())
        m.handle(ResponseDone(had_tool_calls=True))
        m.handle(finished(m))
        m.handle(ResponseDone(had_tool_calls=False))
        assert m.phase is Phase.DONE
        m.handle(PttDown(ts_ms=9000))
        assert m.ledger == {}


class TestFailureAndBudget:
    def test_ws_failure_resets_turn(self, m):
        start_turn(m)
        m.handle(ToolProposedFactory())
        cmds = m.handle(WsFailed(reason="socket closed"))
        assert m.phase is Phase.FAILED
        assert m.ledger == {}
        assert kinds(cmds) == ["CloseMic", "FlushPlayback"]
        m.handle(WsReconnected())
        assert m.phase is Phase.IDLE

    def test_budget_hold_rejects_ptt_and_blocks_text(self, m):
        m.handle(BudgetTripped())
        assert m.phase is Phase.BUDGET_HOLD
        assert m.handle(PttDown()) == [RejectInput(reason=Phase.BUDGET_HOLD.value)]
        assert m.handle(TextCommand(text="hi")) == []

    def test_budget_override_reissues_response(self, m):
        m.handle(BudgetTripped())
        cmds = m.handle(BudgetOverride())
        assert m.phase is Phase.THINKING
        assert kinds(cmds) == ["CreateResponse"]

    def test_user_stop_kills_everything(self, m):
        start_turn(m)
        m.handle(ModelSpeaking())
        cmds = m.handle(UserStop())
        assert m.phase is Phase.IDLE
        assert kinds(cmds) == ["CancelResponse", "FlushPlayback", "CloseMic",
                               "ClearInput", "EndSession"]
        assert cmds[-1].reason == "user_stop"


class TestHygiene:
    def test_stray_tool_proposal_in_idle_ignored(self, m):
        assert m.handle(ToolProposedFactory()) == []
        assert m.ledger == {}

    def test_snapshot_shape(self, m):
        start_turn(m)
        m.handle(ToolProposedFactory(gate=Gate.CONFIRM))
        snap = m.snapshot()
        assert snap["phase"] == "awaiting_approval"
        assert snap["ledger"][0] == {
            "call_id": "c1", "name": "app_open", "preview": "Open app: Obsidian",
            "gate": "confirm", "status": "proposed",
        }
