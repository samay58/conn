"""Adapter boundary. Live (OpenAI WebSocket) and fake (scripted demo) adapters
implement the same interface and emit the same normalized events, so API drift
and demo mode both touch exactly one file each.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import AsyncIterator, Protocol


@dataclass(frozen=True, slots=True)
class RtSessionReady:
    session_id: str


@dataclass(frozen=True, slots=True)
class RtAudioDelta:
    pcm: bytes  # 24kHz mono pcm16


@dataclass(frozen=True, slots=True)
class RtTranscriptDelta:
    text: str  # transcript of the model's spoken output


@dataclass(frozen=True, slots=True)
class RtTextDelta:
    text: str  # text-modality output


@dataclass(frozen=True, slots=True)
class RtInputTranscript:
    text: str  # what the model heard the user say


@dataclass(frozen=True, slots=True)
class RtToolCall:
    call_id: str
    name: str
    arguments_json: str


@dataclass(frozen=True, slots=True)
class RtResponseDone:
    usage: dict = field(default_factory=dict)
    had_tool_calls: bool = False
    status: str = "completed"


@dataclass(frozen=True, slots=True)
class RtResponseCancelled:
    pass


@dataclass(frozen=True, slots=True)
class RtError:
    message: str
    fatal: bool = False


@dataclass(frozen=True, slots=True)
class RtClosed:
    reason: str


RtEvent = (
    RtSessionReady | RtAudioDelta | RtTranscriptDelta | RtTextDelta
    | RtInputTranscript | RtToolCall | RtResponseDone | RtResponseCancelled
    | RtError | RtClosed
)


class RealtimeAdapter(Protocol):
    async def connect(self) -> None: ...
    async def close(self) -> None: ...
    async def append_audio(self, pcm: bytes) -> None: ...
    async def clear_input(self) -> None: ...
    async def commit_input(self) -> None: ...
    async def create_response(self) -> None: ...
    async def cancel_response(self) -> None: ...
    async def send_text(self, text: str) -> None: ...
    async def send_tool_result(self, call_id: str, output: str) -> None: ...
    def events(self) -> AsyncIterator[RtEvent]: ...
    @property
    def connected(self) -> bool: ...
