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
from collections import deque
from typing import Callable

import numpy as np

TARGET_RATE = 24_000
FRAME_MS = 40
BYTES_PER_SAMPLE = 2
# A listening window shorter than this is a tap, not an utterance; no
# low-signal hint for it.
LOW_SIGNAL_MIN_FRAMES = 5


def resolve_input_device(devices: list[dict], requested: str) -> tuple[int | None, str | None]:
    """A2 device choice: map [audio] input_device to a capture device index.
    Exact name match wins, then first substring match, both case-insensitive
    and input-capable only. Returns (index, warning); (None, None) means
    system default by request, (None, warning) means the name matched
    nothing and capture falls back to the default."""
    requested = requested.strip()
    if not requested:
        return None, None
    inputs = [(index, str(device.get("name", "")))
              for index, device in enumerate(devices)
              if int(device.get("max_input_channels", 0) or 0) > 0]
    wanted = requested.lower()
    for index, name in inputs:
        if name.lower() == wanted:
            return index, None
    for index, name in inputs:
        if wanted in name.lower():
            return index, None
    names = ", ".join(name for _index, name in inputs) or "none found"
    return None, (f"input device {requested!r} not found; using the system "
                  f"default. Inputs: {names}")


class AudioPipe:
    def __init__(self, on_pcm: Callable[[bytes], None], on_drain: Callable[[], None],
                 on_level: Callable[[str, float], None] | None = None,
                 preroll_ms: int = 400, input_device: int | None = None,
                 low_signal_rms: float = 0.0,
                 on_low_signal: Callable[[float], None] | None = None):
        import sounddevice as sd
        self._sd = sd
        self._input_device = input_device
        # A2 low-signal honesty: peak rms is tracked per listening window;
        # a window that closes quiet fires on_low_signal instead of letting
        # silence masquerade as a model failure.
        self._low_signal_rms = low_signal_rms
        self.on_low_signal = on_low_signal
        self._gate_peak_rms = 0.0
        self._gate_frames = 0
        self.on_pcm = on_pcm       # called on the event loop with 24kHz pcm16
        self.on_drain = on_drain   # called on the event loop when playback empties
        self.on_level = on_level   # (source, 0..1) at frame rate; drives waveforms
        # A1 pre-roll: the ring holds the last preroll_ms of capture while
        # the gate is shut and is flushed ahead of live frames at gate open,
        # so the first syllable stops dying between keydown and gate-open.
        self._ring: deque[bytes] = deque()
        self._ring_bytes = 0
        self._ring_max_bytes = int(TARGET_RATE * BYTES_PER_SAMPLE * max(preroll_ms, 0) / 1000)
        self._ring_lock = threading.Lock()
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
                device=self._input_device,
                callback=self._in_callback)
            self._in_stream.start()
        except Exception:
            # Device refused 24k; capture at 48k and decimate 2:1.
            self._in_rate = 48_000
            self._in_stream = sd.RawInputStream(
                samplerate=48_000, channels=1, dtype="int16",
                blocksize=int(48_000 * FRAME_MS / 1000),
                device=self._input_device,
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
        self._gate_peak_rms = 0.0
        self._gate_frames = 0
        self._gate = True

    def gate_close(self) -> None:
        was_open = self._gate
        self._gate = False
        # A stale pre-roll must not leak into the next turn; the ring
        # refills from live capture between now and the next keydown.
        with self._ring_lock:
            self._ring.clear()
            self._ring_bytes = 0
        if (was_open and self.on_low_signal is not None
                and self._gate_frames >= LOW_SIGNAL_MIN_FRAMES
                and self._gate_peak_rms < self._low_signal_rms):
            self.on_low_signal(self._gate_peak_rms)

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
        if self._in_rate != TARGET_RATE:
            n = samples.size - (samples.size % 2)
            pairs = samples[:n].astype(np.int32)
            samples = ((pairs[0::2] + pairs[1::2]) // 2).astype(np.int16)
        pcm = samples.tobytes()
        if not self._gate:
            with self._ring_lock:
                self._ring.append(pcm)
                self._ring_bytes += len(pcm)
                while self._ring and self._ring_bytes > self._ring_max_bytes:
                    self._ring_bytes -= len(self._ring.popleft())
            return
        self._gate_frames += 1
        self._gate_peak_rms = max(self._gate_peak_rms, self.last_rms)
        if self._loop is None:
            return
        if self.on_level is not None:
            # Normalize speech rms (~300 to 4000) into 0..1 for the waveform.
            level = min(self.last_rms / 4000.0, 1.0)
            self._loop.call_soon_threadsafe(self.on_level, "mic", level)
        with self._ring_lock:
            preroll = list(self._ring)
            self._ring.clear()
            self._ring_bytes = 0
        # call_soon_threadsafe preserves submission order from this thread,
        # so the ring lands ahead of the live frame that triggered the flush.
        for chunk in preroll:
            self._loop.call_soon_threadsafe(self.on_pcm, chunk)
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
