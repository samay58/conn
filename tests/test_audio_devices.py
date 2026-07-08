"""A2 device choice and low-signal honesty, A3 transcription language pin."""

from __future__ import annotations

import asyncio

import pytest

pytest.importorskip("sounddevice")

from conn.audio import AudioPipe, resolve_input_device
from conn.config import Config
from conn.realtime.openai_ws import OpenAIRealtimeAdapter

DEVICES = [
    {"name": "MacBook Pro Microphone", "max_input_channels": 1},
    {"name": "MacBook Pro Speakers", "max_input_channels": 0},
    {"name": "Elgato Wave:3", "max_input_channels": 2},
    {"name": "Wave Link Stream", "max_input_channels": 2},
]


def test_empty_request_means_system_default():
    assert resolve_input_device(DEVICES, "") == (None, None)
    assert resolve_input_device(DEVICES, "   ") == (None, None)


def test_exact_match_wins_over_substring():
    index, warning = resolve_input_device(DEVICES, "elgato wave:3")
    assert (index, warning) == (2, None)


def test_substring_match_finds_first_input_device():
    index, warning = resolve_input_device(DEVICES, "wave")
    assert (index, warning) == (2, None)


def test_output_only_devices_never_match():
    index, warning = resolve_input_device(DEVICES, "speakers")
    assert index is None
    assert "not found" in warning


def test_not_found_warns_and_falls_back():
    index, warning = resolve_input_device(DEVICES, "Yeti")
    assert index is None
    assert "Yeti" in warning
    assert "MacBook Pro Microphone" in warning


# ---- low-signal window (A2) ----


def make_pipe(low_signal_rms=150.0, hints=None):
    hints = hints if hints is not None else []
    pipe = AudioPipe(on_pcm=lambda pcm: None, on_drain=lambda: None,
                     low_signal_rms=low_signal_rms, on_low_signal=hints.append)
    return pipe, hints


def feed_frames(pipe, rms_values):
    import numpy as np

    for rms in rms_values:
        pcm = np.full(960, int(rms), dtype=np.int16).tobytes()
        pipe._in_callback(pcm, 960, None, None)


def test_quiet_window_fires_low_signal():
    pipe, hints = make_pipe()
    pipe.gate_open()
    feed_frames(pipe, [20] * 6)
    pipe.gate_close()
    assert len(hints) == 1
    assert hints[0] < 150.0


def test_loud_window_stays_silent():
    pipe, hints = make_pipe()
    pipe.gate_open()
    feed_frames(pipe, [20, 20, 900, 20, 20, 20])
    pipe.gate_close()
    assert hints == []


def test_tap_window_never_hints():
    pipe, hints = make_pipe()
    pipe.gate_open()
    feed_frames(pipe, [20, 20])  # below LOW_SIGNAL_MIN_FRAMES
    pipe.gate_close()
    assert hints == []


def test_peak_resets_per_window():
    pipe, hints = make_pipe()
    pipe.gate_open()
    feed_frames(pipe, [900] * 6)
    pipe.gate_close()
    pipe.gate_open()
    feed_frames(pipe, [20] * 6)
    pipe.gate_close()
    assert len(hints) == 1


# ---- transcription language pin (A3) ----


class CapturingAdapter(OpenAIRealtimeAdapter):
    def __init__(self, cfg):
        super().__init__(cfg, tools=[], instructions="test")
        self.sent = []

    async def _send(self, payload):
        self.sent.append(payload)


def connect_and_capture(cfg):
    adapter = CapturingAdapter(cfg)

    async def run():
        import unittest.mock as mock

        with mock.patch("websockets.connect", mock.AsyncMock(return_value=object())), \
             mock.patch.dict("os.environ", {"OPENAI_API_KEY": "test-key"}):
            await adapter.connect()

    asyncio.run(run())
    return adapter.sent


def test_language_pin_rides_session_update():
    sent = connect_and_capture(Config())
    transcription = sent[1]["session"]["audio"]["input"]["transcription"]
    assert transcription == {"model": "gpt-realtime-whisper", "language": "en"}


def test_empty_language_means_no_pin():
    cfg = Config()
    cfg.realtime.transcription_language = ""
    sent = connect_and_capture(cfg)
    transcription = sent[1]["session"]["audio"]["input"]["transcription"]
    assert transcription == {"model": "gpt-realtime-whisper"}
