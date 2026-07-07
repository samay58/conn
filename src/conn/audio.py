"""Half-duplex audio for push-to-talk. The input stream stays open for the
whole session (mic permission prompts once, and key-down latency avoids the
CoreAudio open cost); frames are FORWARDED only while the PTT gate is open.
Playback is a jitter-buffered output stream; drain fires a callback so the
machine can leave SPEAKING.

PTT makes this simple on purpose: no echo cancellation, no VAD, no full-duplex.
"""

from __future__ import annotations

import asyncio
import threading
from typing import Callable

import numpy as np

TARGET_RATE = 24_000
FRAME_MS = 40


class AudioPipe:
    def __init__(self, on_pcm: Callable[[bytes], None], on_drain: Callable[[], None],
                 on_level: Callable[[str, float], None] | None = None):
        import sounddevice as sd
        self._sd = sd
        self.on_pcm = on_pcm       # called on the event loop with 24kHz pcm16
        self.on_drain = on_drain   # called on the event loop when playback empties
        self.on_level = on_level   # (source, 0..1) at frame rate; drives waveforms
        self._gate = False
        self._loop: asyncio.AbstractEventLoop | None = None
        self._in_stream = None
        self._out_stream = None
        self._out_buf = bytearray()
        self._out_lock = threading.Lock()
        self._was_playing = False
        self._in_rate = TARGET_RATE
        self.last_rms = 0.0

    # ---- lifecycle ----

    def start(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop
        self._open_input()
        self._open_output()

    def stop(self) -> None:
        for stream in (self._in_stream, self._out_stream):
            try:
                if stream:
                    stream.stop()
                    stream.close()
            except Exception:
                pass
        self._in_stream = self._out_stream = None

    def _open_input(self) -> None:
        sd = self._sd
        try:
            self._in_rate = TARGET_RATE
            self._in_stream = sd.RawInputStream(
                samplerate=TARGET_RATE, channels=1, dtype="int16",
                blocksize=int(TARGET_RATE * FRAME_MS / 1000),
                callback=self._in_callback)
            self._in_stream.start()
        except Exception:
            # Device refused 24k; capture at 48k and decimate 2:1.
            self._in_rate = 48_000
            self._in_stream = sd.RawInputStream(
                samplerate=48_000, channels=1, dtype="int16",
                blocksize=int(48_000 * FRAME_MS / 1000),
                callback=self._in_callback)
            self._in_stream.start()

    def _open_output(self) -> None:
        self._out_stream = self._sd.RawOutputStream(
            samplerate=TARGET_RATE, channels=1, dtype="int16",
            blocksize=int(TARGET_RATE * FRAME_MS / 1000),
            callback=self._out_callback)
        self._out_stream.start()

    # ---- PTT gate ----

    def gate_open(self) -> None:
        self._gate = True

    def gate_close(self) -> None:
        self._gate = False

    # ---- playback ----

    def play(self, pcm: bytes) -> None:
        with self._out_lock:
            self._out_buf.extend(pcm)
            self._was_playing = True

    def flush(self) -> None:
        with self._out_lock:
            self._out_buf.clear()
            self._was_playing = False

    # ---- stream callbacks (audio threads; keep them tiny) ----

    def _in_callback(self, indata, frames, time_info, status) -> None:
        samples = np.frombuffer(bytes(indata), dtype=np.int16)
        if samples.size:
            self.last_rms = float(np.sqrt(np.mean(samples.astype(np.float64) ** 2)))
        if not self._gate or self._loop is None:
            return
        if self.on_level is not None:
            # Normalize speech rms (~300 to 4000) into 0..1 for the waveform.
            level = min(self.last_rms / 4000.0, 1.0)
            self._loop.call_soon_threadsafe(self.on_level, "mic", level)
        if self._in_rate != TARGET_RATE:
            n = samples.size - (samples.size % 2)
            pairs = samples[:n].astype(np.int32)
            samples = ((pairs[0::2] + pairs[1::2]) // 2).astype(np.int16)
        pcm = samples.tobytes()
        self._loop.call_soon_threadsafe(self.on_pcm, pcm)

    def _out_callback(self, outdata, frames, time_info, status) -> None:
        need = len(outdata)
        with self._out_lock:
            chunk = bytes(self._out_buf[:need])
            del self._out_buf[:need]
            drained = self._was_playing and not self._out_buf
            if drained:
                self._was_playing = False
        outdata[:len(chunk)] = chunk
        if len(chunk) < need:
            outdata[len(chunk):] = b"\x00" * (need - len(chunk))
        if self._loop is not None:
            if self.on_level is not None and chunk:
                samples = np.frombuffer(chunk, dtype=np.int16)
                rms = float(np.sqrt(np.mean(samples.astype(np.float64) ** 2)))
                self._loop.call_soon_threadsafe(self.on_level, "speaker",
                                                min(rms / 6000.0, 1.0))
            if drained:
                self._loop.call_soon_threadsafe(self.on_drain)
