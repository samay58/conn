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
import uuid
from dataclasses import dataclass

import websockets

from ..config import Config
from .base import (
    RtAudioDelta, RtClosed, RtError, RtEvent, RtInputTranscript,
    RtResponseCancelled, RtResponseCreated, RtResponseDone, RtSessionReady,
    RtTextDelta, RtToolCall, RtTranscriptDelta,
)

WS_URL = "wss://api.openai.com/v1/realtime?model={model}"

# The live API rejects item IDs longer than 32 characters. Client IDs stay in
# use (deletion and error correlation both need to name the item before the
# server acknowledges it), so they are minted under the limit by construction.
ITEM_ID_MAX = 32


@dataclass
class _ItemRecord:
    """Acknowledged-item ledger entry. An item may be deleted only from
    `created`; a failed create is dropped outright; a delete requested
    before the ack arrives is `doomed` and sent on acknowledgement. Event
    IDs are kept so both the ledger and the error-correlation map shrink on
    every acknowledgement instead of growing for the session's lifetime."""
    state: str  # create_sent | created | delete_sent
    doomed: bool = False
    create_event_id: str | None = None
    delete_event_id: str | None = None


class OpenAIRealtimeAdapter:
    def __init__(self, cfg: Config, tools: list[dict], instructions: str):
        self.cfg = cfg
        self.tools = tools
        self.instructions = instructions
        self._ws = None
        self._closing = False
        self._pending_calls: dict[str, dict[str, RtToolCall]] = {}
        self._semantic_item_id: str | None = None
        self._items: dict[str, _ItemRecord] = {}
        self._event_causes: dict[str, tuple[str, str]] = {}
        self._active_response_id: str | None = None

    @property
    def connected(self) -> bool:
        return self._ws is not None

    async def connect(self) -> None:
        key = self.cfg.api_key
        if not key:
            raise RuntimeError("OPENAI_API_KEY is not set")
        self._closing = False
        self._semantic_item_id = None
        self._pending_calls.clear()
        self._items.clear()
        self._event_causes.clear()
        self._active_response_id = None
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
                "audio": {"input": {"transcription": self._transcription_config()}},
            },
        })

    def _transcription_config(self) -> dict:
        """A3: the language pin ends short clips decoding as whatever
        language fits ("óperas serían" for "open Obsidian"). Empty config
        value means no pin."""
        transcription: dict = {"model": "gpt-realtime-whisper"}
        language = self.cfg.realtime.transcription_language.strip()
        if language:
            transcription["language"] = language
        return transcription

    async def close(self) -> None:
        self._closing = True
        self._pending_calls.clear()
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
        """Cancel is bound: it names the active response and is never sent
        without one. Late events from an uncancellable response are dropped
        by the app-side provenance ledger instead."""
        response_id = self._active_response_id
        if response_id is None:
            return
        await self._send({"type": "response.cancel",
                          "response_id": response_id})

    async def send_text(self, text: str) -> None:
        await self._send({
            "type": "conversation.item.create",
            "item": {"type": "message", "role": "user",
                     "content": [{"type": "input_text", "text": text}]},
        })

    @staticmethod
    def _new_item_id() -> str:
        item_id = f"ctx_{uuid.uuid4().hex[:24]}"
        assert len(item_id) <= ITEM_ID_MAX
        return item_id

    async def _create_item(self, item_id: str, item: dict) -> None:
        event_id = f"evt_{uuid.uuid4().hex[:16]}"
        self._items[item_id] = _ItemRecord(state="create_sent",
                                           create_event_id=event_id)
        self._event_causes[event_id] = ("item_create", item_id)
        await self._send({
            "type": "conversation.item.create",
            "event_id": event_id,
            "item": {**item, "id": item_id},
        })

    async def _delete_item(self, item_id: str) -> None:
        record = self._items.get(item_id)
        if record is None or record.state == "delete_sent":
            return
        if record.state == "create_sent":
            record.doomed = True
            return
        record.state = "delete_sent"
        event_id = f"evt_{uuid.uuid4().hex[:16]}"
        record.delete_event_id = event_id
        self._event_causes[event_id] = ("item_delete", item_id)
        await self._send({"type": "conversation.item.delete",
                          "event_id": event_id, "item_id": item_id})

    async def clear_semantic_context(self) -> None:
        if self._semantic_item_id is None:
            return
        item_id, self._semantic_item_id = self._semantic_item_id, None
        await self._delete_item(item_id)

    async def upsert_semantic_context(self, text: str) -> None:
        await self.clear_semantic_context()
        item_id = self._new_item_id()
        await self._create_item(item_id, {
            "type": "message",
            "role": "system",
            "content": [{"type": "input_text", "text": text}],
        })
        self._semantic_item_id = item_id

    async def send_tool_result(self, call_id: str, output: str) -> None:
        item_id = None
        try:
            payload = json.loads(output)
        except (TypeError, json.JSONDecodeError):
            payload = None
        data = payload.get("data") if isinstance(payload, dict) else None
        if isinstance(data, dict) and isinstance(data.get("snapshot_id"), str):
            await self.clear_semantic_context()
            item_id = self._new_item_id()
        item = {"type": "function_call_output", "call_id": call_id,
                "output": output}
        if item_id:
            await self._create_item(item_id, item)
            self._semantic_item_id = item_id
        else:
            await self._send({"type": "conversation.item.create", "item": item})

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
        if kind == "response.created":
            response_id = msg.get("response", {}).get("id")
            if not response_id:
                return [self._missing_response_id(kind)]
        elif kind == "response.done":
            if not msg.get("response", {}).get("id"):
                return [self._missing_response_id(kind)]
        elif kind.startswith("response.") and not msg.get("response_id"):
            return [self._missing_response_id(kind)]
        match kind:
            case "session.created":
                return [RtSessionReady(session_id=msg.get("session", {}).get("id", "?"))]
            case "conversation.item.created":
                self._on_item_created(msg.get("item", {}).get("id"))
                return []
            case "conversation.item.deleted":
                record = self._items.pop(msg.get("item_id"), None)
                if record is not None and record.delete_event_id:
                    self._event_causes.pop(record.delete_event_id, None)
                return []
            case "response.created":
                self._pending_calls.setdefault(response_id, {})
                self._active_response_id = response_id
                return [RtResponseCreated(response_id=response_id)]
            case "response.output_audio.delta" | "response.audio.delta":
                return [RtAudioDelta(pcm=base64.b64decode(msg.get("delta", "")),
                                     response_id=msg.get("response_id"))]
            case ("response.output_audio_transcript.delta"
                  | "response.audio_transcript.delta"):
                return [RtTranscriptDelta(text=msg.get("delta", ""),
                                          response_id=msg.get("response_id"))]
            case "response.output_text.delta" | "response.text.delta":
                return [RtTextDelta(text=msg.get("delta", ""),
                                    response_id=msg.get("response_id"))]
            case ("conversation.item.input_audio_transcription.completed"
                  | "conversation.item.audio_transcription.completed"):
                return [RtInputTranscript(text=msg.get("transcript", ""))]
            case "response.function_call_arguments.done":
                response_id = msg.get("response_id")
                call_id = msg.get("call_id", "")
                self._pending_calls.setdefault(response_id, {})[call_id] = RtToolCall(
                    call_id=call_id,
                    name=msg.get("name", ""),
                    arguments_json=msg.get("arguments", "{}"),
                    response_id=response_id,
                )
                return []
            case "response.done":
                return self._on_response_done(msg)
            case "response.cancelled":
                response_id = msg.get("response_id")
                self._pending_calls.pop(response_id, None)
                if self._active_response_id == response_id:
                    self._active_response_id = None
                return [RtResponseCancelled(response_id=response_id)]
            case "error":
                err = msg.get("error", {})
                message = err.get("message", str(err))
                related = self._resolve_error_cause(err.get("event_id"))
                # Server-side validation gripes are logged, not fatal; the
                # socket dying is what fatal means here.
                return [RtError(message=message, fatal=False, related=related)]
        return []

    def _on_item_created(self, item_id: str | None) -> None:
        record = self._items.get(item_id) if item_id else None
        if record is None:
            return
        record.state = "created"
        if record.create_event_id:
            self._event_causes.pop(record.create_event_id, None)
            record.create_event_id = None
        if record.doomed:
            record.doomed = False
            asyncio.ensure_future(self._flush_doomed(item_id))

    async def _flush_doomed(self, item_id: str) -> None:
        """Deferred delete for an item superseded before its create ack. The
        socket may have died in between; that is reconnect territory, not an
        unretrieved task exception."""
        try:
            await self._delete_item(item_id)
        except Exception:
            pass

    def _resolve_error_cause(self, event_id: object) -> str | None:
        """Bind a nonfatal server error back to the client event that caused
        it, and keep the item ledger truthful: a failed create never becomes
        current context, and its ID is never deleted later."""
        if not isinstance(event_id, str):
            return None
        cause = self._event_causes.pop(event_id, None)
        if cause is None:
            return None
        kind, item_id = cause
        if kind == "item_create":
            # A failed create has no server-side item: drop the record
            # entirely so nothing ever targets or retains it.
            self._items.pop(item_id, None)
            if self._semantic_item_id == item_id:
                self._semantic_item_id = None
        elif kind == "item_delete":
            self._items.pop(item_id, None)
        return f"{kind}:{item_id}"

    @staticmethod
    def _missing_response_id(kind: str) -> RtError:
        return RtError(
            message=f"protocol_error: missing response_id for {kind}",
            fatal=False,
        )

    def _on_response_done(self, msg: dict) -> list[RtEvent]:
        response = msg.get("response", {})
        response_id = response.get("id")
        status = response.get("status", "completed")
        if self._active_response_id == response_id:
            self._active_response_id = None
        pending = self._pending_calls.pop(response_id, {})
        if status == "cancelled":
            return [RtResponseCancelled(response_id=response_id)]
        if status != "completed":
            return [RtResponseDone(
                usage=response.get("usage", {}) or {},
                had_tool_calls=False,
                status=status,
                response_id=response_id,
            )]
        terminal: list[RtToolCall] = []
        for item in response.get("output", []) or []:
            if item.get("type") != "function_call":
                continue
            call = RtToolCall(
                call_id=item.get("call_id", ""),
                name=item.get("name", ""),
                arguments_json=item.get("arguments", "{}"),
                response_id=response_id,
            )
            buffered = pending.get(call.call_id)
            if buffered is not None and buffered != call:
                return [
                    RtError(
                        message=(
                            "protocol_error: terminal tool call does not match "
                            f"buffered arguments for {call.call_id!r}"
                        ),
                        fatal=False,
                    ),
                    RtResponseDone(
                        usage=response.get("usage", {}) or {},
                        had_tool_calls=False,
                        status=status,
                        response_id=response_id,
                    ),
                ]
            terminal.append(call)
        events: list[RtEvent] = list(terminal)
        events.append(RtResponseDone(usage=response.get("usage", {}) or {},
                                     had_tool_calls=bool(terminal),
                                     status=status,
                                     response_id=response_id))
        return events

    async def _send(self, payload: dict) -> None:
        if self._ws is None:
            raise RuntimeError("adapter is not connected")
        await self._ws.send(json.dumps(payload))
