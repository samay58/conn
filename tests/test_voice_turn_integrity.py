"""R2 voice turn integrity: playback-contaminated pre-roll never reaches the
model, short voiced holds are accepted while silent taps reject visibly,
duplicate PTT edges are idempotent, and 500 cycles leave no stuck phase,
duplicate turn, or lost release.
"""

from __future__ import annotations

import asyncio

import numpy as np
import pytest

pytest.importorskip("sounddevice")

from conn.audio import BYTES_PER_SAMPLE, AudioPipe
from conn.events import (
    AckTurn, ClearInput, CommitInput, CreateResponse, PttDown, PttUp,
    RejectInput,
)
from conn.state import Phase, SessionStateMachine


class ImmediateLoop:
    def call_soon_threadsafe(self, fn, *args):
        fn(*args)


WATERMARK = 7777


def make_pipe(received=None, now=None):
    received = received if received is not None else []
    pipe = AudioPipe(on_pcm=received.append, on_drain=lambda: None,
                     preroll_ms=400, low_signal_rms=150.0)
    pipe._loop = ImmediateLoop()
    if now is not None:
        pipe._now = now
    return pipe, received


def frame(value: int, samples: int = 960) -> bytes:
    return np.full(samples, value, dtype=np.int16).tobytes()


def feed(pipe, pcm: bytes) -> None:
    pipe._in_callback(pcm, len(pcm) // BYTES_PER_SAMPLE, None, None)


def pull_playback(pipe, nbytes: int = 1920) -> bytes:
    out = bytearray(nbytes)
    pipe._out_callback(out, nbytes // BYTES_PER_SAMPLE, None, None)
    return bytes(out)


class TestPlaybackContamination:
    def test_mic_frames_during_playback_never_enter_the_ring(self):
        clock = [0.0]
        pipe, received = make_pipe(now=lambda: clock[0])
        pipe.play(frame(WATERMARK))
        pull_playback(pipe)  # device is sounding the watermark
        feed(pipe, frame(WATERMARK))  # mic hears the speaker
        clock[0] += 0.05
        pipe.gate_open()
        feed(pipe, frame(3))
        uploaded = b"".join(received)
        samples = np.frombuffer(uploaded, dtype=np.int16)
        assert WATERMARK not in samples
        assert frame(3) in received

    def test_ring_restarts_clean_after_playback_tail_elapses(self):
        clock = [0.0]
        pipe, received = make_pipe(now=lambda: clock[0])
        pipe.play(frame(WATERMARK))
        pull_playback(pipe)
        feed(pipe, frame(WATERMARK))
        clock[0] += 1.0  # tail long past
        feed(pipe, frame(2))  # clean live capture refills the ring
        pipe.gate_open()
        feed(pipe, frame(3))
        assert received == [frame(2), frame(3)]

    def test_gate_open_during_tail_discards_the_ring(self):
        clock = [0.0]
        pipe, received = make_pipe(now=lambda: clock[0])
        feed(pipe, frame(1))  # pre-playback capture sits in the ring
        pipe.play(frame(WATERMARK))
        pull_playback(pipe)
        pipe.flush()
        pipe.gate_open()  # barge-in lands inside the tail window
        feed(pipe, frame(3))
        assert frame(1) not in received
        assert received == [frame(3)]


class TestWindowVoiced:
    def test_loud_window_reports_voiced(self):
        pipe, _ = make_pipe()
        pipe.gate_open()
        feed(pipe, frame(2000))
        assert pipe.window_voiced() is True

    def test_silent_window_reports_unvoiced(self):
        pipe, _ = make_pipe()
        pipe.gate_open()
        feed(pipe, frame(0))
        assert pipe.window_voiced() is False

    def test_preroll_energy_counts_toward_the_window(self):
        """The first syllable often lives in the pre-roll flushed at gate
        open; a short hold must not read as silent because of that."""
        pipe, _ = make_pipe()
        feed(pipe, frame(2000))  # spoken just before the key landed
        pipe.gate_open()
        feed(pipe, frame(0))
        assert pipe.window_voiced() is True


MUTATIONS = frozenset({"app_open"})


def machine() -> SessionStateMachine:
    return SessionStateMachine(computer_mutations=MUTATIONS)


class TestSignalAwareAcceptance:
    def test_short_voiced_hold_is_accepted(self):
        m = machine()
        m.handle(PttDown(ts_ms=1000))
        cmds = m.handle(PttUp(ts_ms=1150, voiced=True))
        kinds = [type(c) for c in cmds]
        assert CommitInput in kinds and CreateResponse in kinds
        acks = [c for c in cmds if isinstance(c, AckTurn)]
        assert acks and acks[0].accepted

    def test_short_silent_tap_rejects_visibly(self):
        m = machine()
        m.handle(PttDown(ts_ms=1000))
        cmds = m.handle(PttUp(ts_ms=1150, voiced=False))
        kinds = [type(c) for c in cmds]
        assert CreateResponse not in kinds
        assert ClearInput in kinds
        acks = [c for c in cmds if isinstance(c, AckTurn)]
        assert acks and not acks[0].accepted and acks[0].reason == "silent_tap"
        assert m.phase is Phase.IDLE

    def test_short_hold_with_unknown_signal_stays_a_tap(self):
        m = machine()
        m.handle(PttDown(ts_ms=1000))
        cmds = m.handle(PttUp(ts_ms=1100, voiced=None))
        assert CreateResponse not in [type(c) for c in cmds]

    def test_long_hold_accepted_regardless_of_signal(self):
        m = machine()
        m.handle(PttDown(ts_ms=1000))
        cmds = m.handle(PttUp(ts_ms=2500, voiced=None))
        assert CreateResponse in [type(c) for c in cmds]
        acks = [c for c in cmds if isinstance(c, AckTurn)]
        assert acks and acks[0].accepted


class TestDuplicateEdges:
    def test_duplicate_down_while_listening_is_silent_noop(self):
        m = machine()
        m.handle(PttDown(ts_ms=1000))
        cmds = m.handle(PttDown(ts_ms=1010))
        assert cmds == []
        assert m.phase is Phase.LISTENING

    def test_down_in_busy_phase_still_rejects_visibly(self):
        m = machine()
        m.handle(PttDown(ts_ms=1000))
        m.handle(PttUp(ts_ms=2000, voiced=True))
        assert m.phase is Phase.THINKING
        cmds = m.handle(PttDown(ts_ms=2100))
        assert any(isinstance(c, RejectInput) for c in cmds)

    def test_duplicate_up_is_ignored(self):
        m = machine()
        m.handle(PttDown(ts_ms=1000))
        m.handle(PttUp(ts_ms=2000, voiced=True))
        assert m.handle(PttUp(ts_ms=2010, voiced=True)) == []


class TestFiveHundredCycles:
    def test_five_hundred_ptt_cycles_no_stuck_phase_or_duplicate_turn(self):
        m = machine()
        accepted = 0
        for n in range(500):
            ts = 10_000 * (n + 1)
            down = m.handle(PttDown(ts_ms=ts))
            assert m.phase is Phase.LISTENING, f"cycle {n}: stuck in {m.phase}"
            # every 5th cycle is a short silent tap; the rest are voiced
            # holds, half of them shorter than the tap threshold
            silent = n % 5 == 0
            held = 120 if (silent or n % 2) else 900
            up = m.handle(PttUp(ts_ms=ts + held, voiced=not silent))
            acks = [c for c in up if isinstance(c, AckTurn)]
            assert len(acks) == 1, f"cycle {n}: {len(acks)} acks"
            if silent:
                assert m.phase is Phase.IDLE, f"cycle {n}: tap left {m.phase}"
            else:
                accepted += 1
                assert m.phase is Phase.THINKING
                assert CreateResponse in [type(c) for c in up]
                # the response completes with no tool calls; turn settles
                from conn.events import ResponseDone
                m.handle(ResponseDone(had_tool_calls=False))
                from conn.events import ResetTick
                m.handle(ResetTick())
                assert m.phase in (Phase.IDLE, Phase.DONE)
                if m.phase is Phase.DONE:
                    m.handle(ResetTick())
        assert accepted == 400

    def test_fifty_cycles_through_the_full_app_loop(self, cfg, ctx):
        from tests.test_trace_truth import build_app

        async def run():
            app = build_app(cfg, ctx)
            app._loop = asyncio.get_running_loop()
            await app.adapter.connect()
            for n in range(50):
                await app.on_ptt_down(client_ts_ms=n * 1000,
                                      source="app_hotkey",
                                      gesture_id=f"g{n}")
                assert app.machine.phase is Phase.LISTENING, (
                    f"cycle {n}: press not accepted")
                # wall-clock hold here is ~0ms with no voice signal, so every
                # release resolves as a visibly rejected silent tap
                await app.on_ptt_up(client_ts_ms=n * 1000 + 700,
                                    source="app_hotkey", gesture_id=f"g{n}")
                assert app.machine.phase is not Phase.LISTENING, (
                    f"cycle {n}: lost release")
            events = app.trace.read()
            await app.stop()
            return events

        events = asyncio.run(run())
        downs = [e for e in events if e["kind"] == "ptt_down"]
        acks = [e for e in events if e["kind"] == "turn_ack"]
        assert len(downs) == 50
        assert len(acks) == 50, "every gesture must be acknowledged"
        assert {a["gesture_id"] for a in acks} == {f"g{n}" for n in range(50)}


class TestSoakSessions:
    def test_three_hundred_turn_soak_sessions_stay_clean(self, cfg, ctx):
        """R8 mechanical soak: three 100-turn sessions through the full app
        loop with the scripted adapter. No stuck phase, no duplicate
        response, no unresolved ledger entries, no unbounded repair loop."""
        from tests.test_trace_truth import build_app
        from conn.events import ResetTick

        # 100 scripted turns cost past the $1 default cap; the cap firing is
        # its own pinned behavior, not this soak's subject.
        cfg.budget.session_cap_usd = 10.0
        for session in range(3):
            async def run():
                app = build_app(cfg, ctx)
                await app.start()
                for n in range(100):
                    await app.on_text(f"open obsidian please {n}")
                    for _ in range(500):
                        await asyncio.sleep(0.001)
                        if app.machine.phase in (Phase.DONE, Phase.IDLE):
                            break
                    assert app.machine.phase in (Phase.DONE, Phase.IDLE), (
                        f"session {session} turn {n}: stuck in {app.machine.phase}")
                    assert not app.machine.unresolved_calls(), (
                        f"session {session} turn {n}: unresolved calls")
                    await app.dispatch(ResetTick())
                events = app.trace.read()
                await app.stop()
                return events

            events = asyncio.run(run())
            errors = [e for e in events if e["kind"] == "upstream_error"]
            assert errors == [], f"session {session}: {errors[:2]}"
