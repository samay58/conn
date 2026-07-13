"""Strict in-memory Realtime server for wire-contract tests.

Enforces the live API rules the July 12 session broke: 32-character item ID
limit, item lifecycle acknowledgements, delete-of-missing-item errors, and
cancellation without an active response. A capturing mock cannot catch these;
this fake refuses like the real service does and counts every protocol error
it emits.
"""

from __future__ import annotations

import asyncio
import json


class StrictRealtimeServer:
    ITEM_ID_MAX = 32

    def __init__(self):
        self.items: dict[str, dict] = {}
        self.active_response_id: str | None = None
        self.protocol_errors: list[str] = []
        self.client_frames: list[dict] = []
        self._response_seq = 0
        self._item_seq = 0
        self._audio_frames = 0
        self.script_tool_calls: list[dict] = []  # consumed one per response

    def connect(self):
        return _StrictSocket(self)

    # ---- server-side handling of one client event ----

    def handle(self, event: dict) -> list[dict]:
        self.client_frames.append(event)
        kind = event.get("type", "")
        out: list[dict] = []
        match kind:
            case "session.update":
                pass
            case "input_audio_buffer.append":
                self._audio_frames += 1
            case "input_audio_buffer.clear":
                self._audio_frames = 0
            case "input_audio_buffer.commit":
                if self._audio_frames == 0:
                    out.append(self._error(
                        "Error committing input audio buffer: the buffer is empty.",
                        event))
                else:
                    self._audio_frames = 0
                    self._item_seq += 1
                    out.append({
                        "type": "conversation.item.created",
                        "item": {"id": f"item_srv{self._item_seq}",
                                 "type": "message", "role": "user"},
                    })
            case "conversation.item.create":
                item = event.get("item", {})
                item_id = item.get("id")
                if item_id is not None and len(item_id) > self.ITEM_ID_MAX:
                    out.append(self._error(
                        "Invalid 'item.id': string too long. Expected a string "
                        f"with maximum length {self.ITEM_ID_MAX}, but got a "
                        f"string with length {len(item_id)} instead.", event))
                else:
                    if item_id is None:
                        self._item_seq += 1
                        item_id = f"item_srv{self._item_seq}"
                    self.items[item_id] = item
                    out.append({
                        "type": "conversation.item.created",
                        "item": {**item, "id": item_id},
                    })
            case "conversation.item.delete":
                item_id = event.get("item_id")
                if item_id not in self.items:
                    out.append(self._error(
                        f"Error deleting item: the item with id '{item_id}' "
                        "does not exist.", event))
                else:
                    del self.items[item_id]
                    out.append({"type": "conversation.item.deleted",
                                "item_id": item_id})
            case "response.create":
                if self.active_response_id is not None:
                    out.append(self._error(
                        "Conversation already has an active response", event))
                else:
                    self._response_seq += 1
                    response_id = f"resp_srv{self._response_seq}"
                    self.active_response_id = response_id
                    out.append({"type": "response.created",
                                "response": {"id": response_id}})
                    out.extend(self._play_response(response_id))
            case "response.cancel":
                response_id = event.get("response_id")
                if self.active_response_id is None:
                    out.append(self._error(
                        "Cancellation failed: no active response found", event))
                elif response_id is not None and response_id != self.active_response_id:
                    out.append(self._error(
                        f"Cancellation failed: response {response_id!r} is not "
                        "active", event))
                else:
                    cancelled = self.active_response_id
                    self.active_response_id = None
                    out.append({
                        "type": "response.done",
                        "response": {"id": cancelled, "status": "cancelled",
                                     "usage": {}},
                    })
        return out

    def _play_response(self, response_id: str) -> list[dict]:
        out: list[dict] = [{
            "type": "response.output_audio_transcript.delta",
            "response_id": response_id, "delta": "Okay.",
        }]
        output = []
        if self.script_tool_calls:
            call = self.script_tool_calls.pop(0)
            out.append({
                "type": "response.function_call_arguments.done",
                "response_id": response_id,
                "call_id": call["call_id"],
                "name": call["name"],
                "arguments": json.dumps(call.get("arguments", {})),
            })
            output.append({
                "type": "function_call", "call_id": call["call_id"],
                "name": call["name"],
                "arguments": json.dumps(call.get("arguments", {})),
            })
        self.active_response_id = None
        out.append({
            "type": "response.done",
            "response": {
                "id": response_id, "status": "completed",
                "usage": {"input_tokens": 10, "output_tokens": 5},
                "output": output,
            },
        })
        return out

    def _error(self, message: str, cause: dict) -> dict:
        self.protocol_errors.append(message)
        return {"type": "error",
                "error": {"message": message,
                          "event_id": cause.get("event_id")}}


class _StrictSocket:
    """Just enough of the websockets client-connection surface for the
    adapter: async send/iteration/close."""

    def __init__(self, server: StrictRealtimeServer):
        self.server = server
        self.queue: asyncio.Queue = asyncio.Queue()
        self.closed = False
        self.queue.put_nowait(json.dumps(
            {"type": "session.created", "session": {"id": "sess_strict"}}))

    async def send(self, text: str) -> None:
        if self.closed:
            raise RuntimeError("socket closed")
        for event in self.server.handle(json.loads(text)):
            self.queue.put_nowait(json.dumps(event))

    async def close(self) -> None:
        self.closed = True
        self.queue.put_nowait(None)

    def __aiter__(self):
        return self

    async def __anext__(self):
        if self.closed and self.queue.empty():
            raise StopAsyncIteration
        item = await self.queue.get()
        if item is None:
            raise StopAsyncIteration
        return item
