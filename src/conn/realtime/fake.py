"""Scripted demo adapter. Plays scenario files so the entire loop (PTT or text
in, transcript out, tool proposals, approvals, continuations, receipts) runs
with zero credentials and zero network.

Behavioral contract mirrors the live model: after a user turn, create_response
plays the scenario's next segment; if that segment proposes tool calls, the
adapter goes quiet until every call has a result AND create_response is called
again (which is exactly how the daemon drives the live API).
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

from ..events import new_id
from .base import (
    RtClosed, RtEvent, RtInputTranscript, RtResponseCancelled,
    RtResponseCreated, RtResponseDone, RtSessionReady, RtToolCall,
    RtTranscriptDelta,
)

SCENARIO_DIR = Path(__file__).parent / "scenarios"

FALLBACK = {
    "id": "fallback",
    "match": [],
    "segments": [
        {"say": "Demo mode. Try: open Obsidian, search the vault for transformer paper, "
                "or copy something to the clipboard.",
         "usage": {"input_tokens": 180, "output_tokens": 40,
                   "input_token_details": {"text_tokens": 180, "audio_tokens": 0, "cached_tokens": 0},
                   "output_token_details": {"text_tokens": 40, "audio_tokens": 0}}},
    ],
}


def load_scenarios(path: Path = SCENARIO_DIR) -> list[dict]:
    scenarios = []
    if path.exists():
        for f in sorted(path.glob("*.json")):
            scenarios.append(json.loads(f.read_text()))
    return scenarios


class FakeRealtimeAdapter:
    def __init__(self, scenarios: list[dict] | None = None, pace_s: float = 0.02):
        self.scenarios = scenarios if scenarios is not None else load_scenarios()
        self.pace_s = pace_s
        self._queue: asyncio.Queue[RtEvent] = asyncio.Queue()
        self._connected = False
        self._active: dict | None = None   # scenario being played
        self._cursor = 0                   # next segment index
        self._pending_input: str | None = None
        self._audio_buffered = False
        self._play_task: asyncio.Task | None = None
        self._active_response_id: str | None = None
        self._semantic_context: str | None = None
        self._visual_metadata: dict | None = None

    # ---- adapter interface ----

    @property
    def connected(self) -> bool:
        return self._connected

    async def connect(self) -> None:
        self._connected = True
        await self._queue.put(RtSessionReady(session_id=new_id("demo")))

    async def close(self) -> None:
        if self._play_task and not self._play_task.done():
            self._play_task.cancel()
        if self._connected:
            self._connected = False
            await self._queue.put(RtClosed(reason="closed"))

    async def append_audio(self, pcm: bytes) -> None:
        self._audio_buffered = True

    async def clear_input(self) -> None:
        self._audio_buffered = False

    async def commit_input(self) -> None:
        if self._audio_buffered:
            # Demo stand-in for speech: a canned utterance that matches the
            # default scenario, so voice PTT demos work without a model.
            self._pending_input = self._default_utterance()
            self._input_was_audio = True
            self._audio_buffered = False

    async def send_text(self, text: str) -> None:
        self._pending_input = text
        self._input_was_audio = False

    async def clear_semantic_context(self) -> None:
        self._semantic_context = None

    async def upsert_semantic_context(self, text: str) -> None:
        self._semantic_context = text

    async def create_response(self) -> None:
        if self._pending_input is not None:
            text = self._pending_input
            self._pending_input = None
            self._active = self._match(text)
            self._cursor = 0
            if getattr(self, "_input_was_audio", False):
                # Voice path: surface what the "model" heard, like live
                # input transcription would.
                await self._queue.put(RtInputTranscript(text=text))
        self._active_response_id = new_id("response")
        await self._queue.put(RtResponseCreated(response_id=self._active_response_id))
        self._play_task = asyncio.ensure_future(self._play_segment())

    async def cancel_response(self) -> None:
        if self._play_task and not self._play_task.done():
            self._play_task.cancel()
        await self._queue.put(RtResponseCancelled(response_id=self._active_response_id))

    async def send_tool_result(
        self, call_id: str, output: str, model_observation=None,
        visual_observation=None,
    ) -> None:
        if visual_observation is not None:
            self._visual_metadata = dict(visual_observation.metadata)

    async def events(self):
        while True:
            ev = await self._queue.get()
            yield ev
            if isinstance(ev, RtClosed):
                return

    # ---- internals ----

    def _default_utterance(self) -> str:
        for sc in self.scenarios:
            if sc.get("default"):
                return sc.get("spoken", "open obsidian")
        if self.scenarios:
            return self.scenarios[0].get("spoken", "open obsidian")
        return "hello"

    def _match(self, text: str) -> dict:
        lowered = text.lower()
        best, best_hits = None, 0
        for sc in self.scenarios:
            hits = sum(1 for kw in sc.get("match", []) if kw in lowered)
            if hits > best_hits:
                best, best_hits = sc, hits
        return best or FALLBACK

    async def _play_segment(self) -> None:
        try:
            scenario = self._active or FALLBACK
            segments = scenario["segments"]
            if self._cursor >= len(segments):
                await self._queue.put(RtResponseDone(
                    usage={}, had_tool_calls=False,
                    response_id=self._active_response_id,
                ))
                return
            seg = segments[self._cursor]
            self._cursor += 1
            for word in seg.get("say", "").split(" "):
                await self._queue.put(RtTranscriptDelta(
                    text=word + " ", response_id=self._active_response_id,
                ))
                await asyncio.sleep(self.pace_s)
            tools = seg.get("tools", [])
            for t in tools:
                await self._queue.put(RtToolCall(
                    call_id=new_id("call"), name=t["name"],
                    arguments_json=json.dumps(t.get("arguments", {})),
                    response_id=self._active_response_id,
                ))
            await self._queue.put(RtResponseDone(
                usage=seg.get("usage", {}), had_tool_calls=bool(tools),
                response_id=self._active_response_id,
            ))
        except asyncio.CancelledError:
            pass
