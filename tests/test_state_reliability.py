import pytest

from conn.events import (
    BudgetTripped, Gate, PttDown, PttUp, ResponseDone, ToolCall, ToolFinished,
    ToolProposed, RejectInput, WatchdogTick,
)
from conn.state import Phase, SessionStateMachine


def call(call_id="c1", gate=Gate.AUTO, name="app_open"):
    return ToolCall(call_id=call_id, name=name, arguments={"app": "Obsidian"},
                    gate=gate, preview="Open app: Obsidian")


def kinds(cmds):
    return [type(c).__name__ for c in cmds]


@pytest.fixture
def m():
    return SessionStateMachine()


def start_turn(m, t0=1000, t1=2000):
    m.handle(PttDown(ts_ms=t0))
    return m.handle(PttUp(ts_ms=t1))


class TestRejectInput:
    def test_ptt_down_in_thinking_yields_reject_input(self, m):
        start_turn(m)
        assert m.phase is Phase.THINKING
        cmds = m.handle(PttDown(ts_ms=3000))
        assert cmds == [RejectInput(reason="thinking")]
        assert m.phase is Phase.THINKING  # rejected input causes no transition

    def test_ptt_down_in_acting_yields_reject_input(self, m):
        start_turn(m)
        m.handle(ToolProposed(call=call()))
        assert m.phase is Phase.ACTING
        cmds = m.handle(PttDown(ts_ms=3000))
        assert cmds == [RejectInput(reason="acting")]

    def test_ptt_down_in_budget_hold_yields_reject_input(self, m):
        m.handle(BudgetTripped())
        assert m.phase is Phase.BUDGET_HOLD
        cmds = m.handle(PttDown(ts_ms=1000))
        assert cmds == [RejectInput(reason="budget_hold")]

    def test_accepting_phases_still_return_normal_commands(self, m):
        # IDLE, DONE, and SPEAKING are the accepting phases and must not regress.
        cmds = m.handle(PttDown(ts_ms=1000))
        assert not any(isinstance(c, RejectInput) for c in cmds)


class TestWatchdog:
    def test_watchdog_forces_failed_path_when_stuck_in_thinking(self):
        m = SessionStateMachine(watchdog_timeout_s=5)
        start_turn(m, t0=1000, t1=2000)
        assert m.phase is Phase.THINKING

        # First tick only arms the baseline for this phase; no trigger yet.
        assert m.handle(WatchdogTick(ts_ms=2000)) == []
        assert m.phase is Phase.THINKING

        # A second tick past the timeout forces the same failure path as WsFailed.
        cmds = m.handle(WatchdogTick(ts_ms=2000 + 5_000 + 1))
        assert m.phase is Phase.FAILED
        assert kinds(cmds) == ["CloseMic", "FlushPlayback"]
        assert m.ledger == {}

    def test_watchdog_does_not_fire_before_timeout_elapses(self):
        m = SessionStateMachine(watchdog_timeout_s=5)
        start_turn(m, t0=1000, t1=2000)
        m.handle(WatchdogTick(ts_ms=2000))
        cmds = m.handle(WatchdogTick(ts_ms=2000 + 1_000))
        assert cmds == []
        assert m.phase is Phase.THINKING

    def test_watchdog_in_idle_is_noop(self, m):
        assert m.phase is Phase.IDLE
        assert m.handle(WatchdogTick(ts_ms=1000)) == []
        assert m.phase is Phase.IDLE

    def test_watchdog_in_awaiting_approval_is_noop(self):
        m = SessionStateMachine(watchdog_timeout_s=5)
        start_turn(m, t0=1000, t1=2000)
        m.handle(ToolProposed(call=call(gate=Gate.CONFIRM)))
        assert m.phase is Phase.AWAITING_APPROVAL
        m.handle(WatchdogTick(ts_ms=2000))
        cmds = m.handle(WatchdogTick(ts_ms=2000 + 10_000))
        assert cmds == []
        assert m.phase is Phase.AWAITING_APPROVAL

    def test_watchdog_does_not_fire_while_a_call_is_running(self):
        m = SessionStateMachine(watchdog_timeout_s=5)
        start_turn(m, t0=1000, t1=2000)
        m.handle(ToolProposed(call=call(gate=Gate.AUTO)))
        assert m.phase is Phase.ACTING
        m.handle(WatchdogTick(ts_ms=2000))
        cmds = m.handle(WatchdogTick(ts_ms=2000 + 10_000))
        assert cmds == []  # the running call is legitimate work, not a hang
        assert m.phase is Phase.ACTING

    def test_watchdog_rearms_after_a_real_transition(self):
        m = SessionStateMachine(watchdog_timeout_s=5)
        start_turn(m, t0=1000, t1=2000)
        m.handle(WatchdogTick(ts_ms=2000))  # arm baseline in THINKING
        # A real transition happens (barge-in style not applicable here, so use
        # ModelSpeaking to move THINKING -> SPEAKING) before the timeout lands.
        from conn.events import ModelSpeaking
        m.handle(ModelSpeaking())
        assert m.phase is Phase.SPEAKING
        # Same absolute timestamp that would have tripped THINKING's baseline
        # must not trip SPEAKING's fresh baseline.
        cmds = m.handle(WatchdogTick(ts_ms=2000 + 5_000 + 1))
        assert cmds == []
        assert m.phase is Phase.SPEAKING

    def test_watchdog_survives_a_healthy_tool_loop_that_leaves_and_returns_to_thinking(self):
        # Defect: re-arm used to be gated on `armed_phase != phase`, so a round
        # trip that leaves THINKING and comes back (THINKING -> ACTING ->
        # THINKING) between two ticks was invisible to the watchdog, even
        # though a real transition happened in between. A live session doing
        # normal tool-call work must never get force-failed.
        m = SessionStateMachine(watchdog_timeout_s=60)
        start_turn(m, t0=1000, t1=2000)
        assert m.phase is Phase.THINKING

        t = 2000
        assert m.handle(WatchdogTick(ts_ms=t)) == []  # arm baseline in THINKING

        for i in range(5):
            t += 30_000  # 30s per round; 5 rounds pushes well past the 60s timeout
            m.handle(ToolProposed(call=call(call_id=f"c{i}")))
            assert m.phase is Phase.ACTING
            m.handle(ToolFinished(call_id=f"c{i}", ok=True, output="{}"))
            m.handle(ResponseDone(had_tool_calls=True))
            assert m.phase is Phase.THINKING
            # The watchdog samples THINKING every round; each round crossed a
            # real ACTING<->THINKING transition since the last sample, so it
            # must re-arm rather than accumulate elapsed time toward a fire.
            cmds = m.handle(WatchdogTick(ts_ms=t))
            assert cmds == []
            assert m.phase is Phase.THINKING

    def test_watchdog_fires_exactly_once_then_stays_silent(self):
        m = SessionStateMachine(watchdog_timeout_s=5)
        start_turn(m, t0=1000, t1=2000)
        m.handle(WatchdogTick(ts_ms=2000))  # arm baseline

        cmds = m.handle(WatchdogTick(ts_ms=2000 + 5_000 + 1))  # fires
        assert m.phase is Phase.FAILED
        assert kinds(cmds) == ["CloseMic", "FlushPlayback"]

        # Every following tick, including ones well past another full
        # timeout window, must return [] and never re-fire.
        for extra_s in (1, 5, 60, 600):
            cmds = m.handle(WatchdogTick(ts_ms=2000 + 5_000 + 1 + extra_s * 1000))
            assert cmds == []
            assert m.phase is Phase.FAILED

    def test_watchdog_never_fires_in_failed_phase(self):
        from conn.events import WsFailed
        m = SessionStateMachine(watchdog_timeout_s=5)
        start_turn(m, t0=1000, t1=2000)
        m.handle(WsFailed(reason="socket closed"))
        assert m.phase is Phase.FAILED

        # First tick after entering FAILED arms a baseline under the old,
        # unfixed code (it isn't exempt yet); the real assertion is the
        # SECOND tick, once elapsed already exceeds the timeout, which must
        # still be a no-op rather than re-firing CloseMic/FlushPlayback for a
        # session that is already visibly failed.
        m.handle(WatchdogTick(ts_ms=2000))
        cmds = m.handle(WatchdogTick(ts_ms=2000 + 5_000 + 1))
        assert cmds == []
        assert m.phase is Phase.FAILED


class TestLastTransition:
    def test_last_transition_records_the_move(self, m):
        assert m.last_transition is None
        m.handle(PttDown(ts_ms=1000))
        assert m.last_transition == (Phase.IDLE, Phase.LISTENING)

    def test_last_transition_unchanged_on_noop_input(self, m):
        m.handle(PttDown(ts_ms=1000))
        assert m.last_transition == (Phase.IDLE, Phase.LISTENING)
        m.handle(PttDown(ts_ms=1500))  # PttDown while LISTENING is a no-op
        assert m.last_transition == (Phase.IDLE, Phase.LISTENING)
