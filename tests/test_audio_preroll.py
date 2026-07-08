"""A1 pre-roll: the capture ring fills while the PTT gate is shut, flushes
ahead of live frames in order when the gate opens, trims to its budget, and
clears on gate close. The 2026-07-08 drive lost the first syllable between
keydown and gate-open ("open Obsidian" decoding as Spanish fragments).
"""

from __future__ import annotations

import numpy as np
import pytest

pytest.importorskip("sounddevice")

from conn.audio import BYTES_PER_SAMPLE, TARGET_RATE, AudioPipe


class ImmediateLoop:
    """call_soon_threadsafe that runs inline, preserving submission order."""

    def call_soon_threadsafe(self, fn, *args):
        fn(*args)


def make_pipe(preroll_ms=400, received=None):
    received = received if received is not None else []
    pipe = AudioPipe(on_pcm=received.append, on_drain=lambda: None,
                     preroll_ms=preroll_ms)
    pipe._loop = ImmediateLoop()
    return pipe, received


def frame(value: int, samples: int = 960) -> bytes:
    return np.full(samples, value, dtype=np.int16).tobytes()


def feed(pipe, pcm: bytes) -> None:
    pipe._in_callback(pcm, len(pcm) // BYTES_PER_SAMPLE, None, None)


def test_ring_flushes_ahead_of_live_frames_in_order():
    pipe, received = make_pipe()
    feed(pipe, frame(1))
    feed(pipe, frame(2))
    assert received == []
    pipe.gate_open()
    feed(pipe, frame(3))
    assert received == [frame(1), frame(2), frame(3)]


def test_ring_trims_to_preroll_budget():
    pipe, _received = make_pipe(preroll_ms=80)
    budget_bytes = int(TARGET_RATE * BYTES_PER_SAMPLE * 80 / 1000)
    for value in range(10):
        feed(pipe, frame(value))
    assert pipe._ring_bytes <= budget_bytes
    assert len(pipe._ring) == 2  # 80ms budget holds exactly two 40ms frames


def test_ring_cleared_on_gate_close():
    pipe, received = make_pipe()
    feed(pipe, frame(1))
    pipe.gate_open()
    pipe.gate_close()
    feed(pipe, frame(2))  # refills the ring while shut
    pipe.gate_open()
    feed(pipe, frame(3))
    assert received == [frame(2), frame(3)]


def test_ring_does_not_replay_across_turns():
    pipe, received = make_pipe()
    pipe.gate_open()
    feed(pipe, frame(1))
    pipe.gate_close()
    pipe.gate_open()
    feed(pipe, frame(2))
    assert received == [frame(1), frame(2)]


def test_zero_preroll_disables_the_ring():
    pipe, received = make_pipe(preroll_ms=0)
    feed(pipe, frame(1))
    assert pipe._ring_bytes == 0
    pipe.gate_open()
    feed(pipe, frame(2))
    assert received == [frame(2)]
