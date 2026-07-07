"""Live adapter: one WebSocket to the OpenAI Realtime API. The daemon owns the
key; nothing client-side ever sees it. All event-name normalization lives here
so API drift touches exactly this file.

Push-to-talk contract: turn_detection is null; the daemon appends audio while
the key is held, commits on release, and drives every response.create itself.
"""

from __future__ import annotations

import asyncio
import base64
import json

import websockets

from ..config import Config
from .base import (
    RtAudioDelta, RtClosed, RtError, RtEvent, RtInputTranscript,
    RtResponseCancelled, RtResponseDone, RtSessionReady, RtTextDelta,
    RtToolCall, RtTranscriptDelta,
)

WS_URL = "wss://api.openai.com/v1/realtime?model={model}"


class OpenAIRealtimeAdapter:
    def __init__(self, cfg: Config, tools: list[dict], instructions: str):
        self.cfg = cfg
        self.tools = tools
        self.instructions = instructions
        self._ws = None
        self._closing = False
        self._emitted_calls: set[str] = set()

    @property
    def connected(self) -> bool:
        return self._ws is not None

    async def connect(self) -> None:
        key = self.cfg.api_key
        if not key:
            raise RuntimeError("OPENAI_API_KEY is not set")
        self._closing = False
        self._ws = await websockets.connect(
            WS_URL.format(model=self.cfg.realtime.model),
            additional_headers={"Authorization": f"Bearer {key}"},
            max_size=1 << 24,
        )
        await self._send({
            "type": "session.update",
            "session": {
                "type": "realtime",
                "instructions": self.instructions,
                "tools": self.tools,
                "tool_choice": "auto",
                "audio": {
                    "input": {
                        "format": {"type": "audio/pcm", "rate": 24000},
                        "turn_detection": None,
                    },
                    "output": {
                        "format": {"type": "audio/pcm", "rate": 24000},
                        "voice": self.cfg.realtime.voice,
                    },
                },
            },
        })
        # Enhancements ride a second update so a rejected key can never take
        # the PTT-critical config down with it.
        await self._send({
            "type": "session.update",
            "session": {
                "type": "realtime",
                "reasoning": {"effort": self.cfg.realtime.reasoning_effort},
                "audio": {"input": {"transcription": {"model": "gpt-realtime-whisper"}}},
            },
        })

    async def close(self) -> None:
        self._closing = True
        if self._ws is not None:
            ws, self._ws = self._ws, None
            await ws.close()

    # ---- client events ----

    async def append_audio(self, pcm: bytes) -> None:
        await self._send({"type": "input_audio_buffer.append",
                          "audio": base64.b64encode(pcm).decode()})

    async def clear_input(self) -> None:
        await self._send({"type": "input_audio_buffer.clear"})

    async def commit_input(self) -> None:
        await self._send({"type": "input_audio_buffer.commit"})

    async def create_response(self) -> None:
        await self._send({"type": "response.create"})

    async def cancel_response(self) -> None:
        await self._send({"type": "response.cancel"})

    async def send_text(self, text: str) -> None:
        await self._send({
            "type": "conversation.item.create",
            "item": {"type": "message", "role": "user",
                     "content": [{"type": "input_text", "text": text}]},
        })

    async def send_tool_result(self, call_id: str, output: str) -> None:
        await self._send({
            "type": "conversation.item.create",
            "item": {"type": "function_call_output", "call_id": call_id,
                     "output": output},
        })

    # ---- server events ----

    async def events(self):
        if self._ws is None:
            return
        # Captured at entry: the identity guard in `finally` only clears
        # self._ws if it still points at THIS socket. A reconnect landing
        # while this generator is abandoned mid-iteration (e.g. during the
        # RtClosed yield) assigns a NEW socket to self._ws, and an unguarded
        # finally would clobber it.
        ws = self._ws
        try:
            async for raw in ws:
                for ev in self._normalize(json.loads(raw)):
                    yield ev
            closing, self._ws = self._closing, None
            if not closing:
                yield RtClosed(reason="connection closed: clean")
        except websockets.ConnectionClosed as e:
            self._ws = None
            yield RtClosed(reason=f"connection closed: {e.code}")
        except Exception as e:
            self._ws = None
            yield RtError(message=str(e), fatal=True)
        finally:
            # Covers GeneratorExit (aclose()/early break/task cancellation),
            # which is a BaseException and skips the `except Exception` above.
            if self._ws is ws:
                self._ws = None

    def _normalize(self, msg: dict) -> list[RtEvent]:
        kind = msg.get("type", "")
        match kind:
            case "session.created":
                return [RtSessionReady(session_id=msg.get("session", {}).get("id", "?"))]
            case "response.output_audio.delta" | "response.audio.delta":
                return [RtAudioDelta(pcm=base64.b64decode(msg.get("delta", "")))]
            case ("response.output_audio_transcript.delta"
                  | "response.audio_transcript.delta"):
                return [RtTranscriptDelta(text=msg.get("delta", ""))]
            case "response.output_text.delta" | "response.text.delta":
                return [RtTextDelta(text=msg.get("delta", ""))]
            case ("conversation.item.input_audio_transcription.completed"
                  | "conversation.item.audio_transcription.completed"):
                return [RtInputTranscript(text=msg.get("transcript", ""))]
            case "response.function_call_arguments.done":
                call_id = msg.get("call_id", "")
                self._emitted_calls.add(call_id)
                return [RtToolCall(call_id=call_id,
                                   name=msg.get("name", ""),
                                   arguments_json=msg.get("arguments", "{}"))]
            case "response.done":
                return self._on_response_done(msg)
            case "response.cancelled":
                return [RtResponseCancelled()]
            case "error":
                err = msg.get("error", {})
                message = err.get("message", str(err))
                # Server-side validation gripes are logged, not fatal; the
                # socket dying is what fatal means here.
                return [RtError(message=message, fatal=False)]
        return []

    def _on_response_done(self, msg: dict) -> list[RtEvent]:
        response = msg.get("response", {})
        events: list[RtEvent] = []
        had_calls = False
        for item in response.get("output", []) or []:
            if item.get("type") == "function_call":
                had_calls = True
                call_id = item.get("call_id", "")
                if call_id not in self._emitted_calls:
                    events.append(RtToolCall(
                        call_id=call_id, name=item.get("name", ""),
                        arguments_json=item.get("arguments", "{}")))
                self._emitted_calls.add(call_id)
        if response.get("status") == "cancelled":
            events.append(RtResponseCancelled())
            return events
        events.append(RtResponseDone(usage=response.get("usage", {}) or {},
                                     had_tool_calls=had_calls,
                                     status=response.get("status", "completed")))
        return events

    async def _send(self, payload: dict) -> None:
        if self._ws is None:
            raise RuntimeError("adapter is not connected")
        await self._ws.send(json.dumps(payload))
