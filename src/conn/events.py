"""Event vocabulary shared by the state machine, the harness, the adapters, and the console.

Machine inputs are frozen dataclasses; the machine returns command dataclasses.
Everything here is pure data so the whole protocol is unit-testable and serializable.
"""

# Boundary rule:
# - Allowed: frozen dataclasses, enums, IDs, timestamp helpers, protocol unions.
# - Not allowed: state transitions, tool policy, UI behavior, retry logic, timers.

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from enum import StrEnum

from .actions import ActionOutcome


def now_ms() -> int:
    return int(time.time() * 1000)


def mono_ms() -> int:
    """Monotonic clock in milliseconds; use for all span math (never wall-clock)."""
    return int(time.monotonic() * 1000)


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:10]}"


class Gate(StrEnum):
    AUTO = "auto"        # READ / ACT_LOW: execute immediately
    CONFIRM = "confirm"  # ACT_CONFIRM: approval chip, nothing runs until the user decides
    BLOCKED = "blocked"  # refused by policy; the model gets a structured denial


@dataclass(frozen=True, slots=True)
class ResponseProvenance:
    turn_id: str
    response_epoch: int
    observation_epoch: int


@dataclass(frozen=True, slots=True)
class ToolCall:
    call_id: str
    name: str
    arguments: dict
    gate: Gate
    preview: str  # human sentence shown on the chip, e.g. 'Open app: Obsidian'
    block_reason: str | None = None  # set when gate is BLOCKED; goes back to the model
    turn_id: str | None = None
    response_epoch: int | None = None
    observation_epoch: int | None = None
    execution_id: int | None = None
    prepared_plan: dict | None = None
    prepared_failure: dict | None = None


# Machine inputs

@dataclass(frozen=True, slots=True)
class PttDown:
    ts_ms: int = field(default_factory=now_ms)
    client_ts_ms: int | None = None


@dataclass(frozen=True, slots=True)
class PttUp:
    ts_ms: int = field(default_factory=now_ms)
    client_ts_ms: int | None = None
    voiced: bool | None = None  # audio saw speech energy this window; None when unknowable


@dataclass(frozen=True, slots=True)
class TextCommand:
    text: str


@dataclass(frozen=True, slots=True)
class ToolProposed:
    call: ToolCall


@dataclass(frozen=True, slots=True)
class ToolFinished:
    call_id: str
    ok: bool
    output: str  # JSON string handed back to the model verbatim
    action_outcome: ActionOutcome | None = None
    turn_id: str | None = None
    response_epoch: int | None = None
    observation_epoch: int | None = None
    execution_id: int | None = None
    action_trace: dict | None = None


@dataclass(frozen=True, slots=True)
class ApprovalDecision:
    call_id: str
    approved: bool


@dataclass(frozen=True, slots=True)
class ApprovalTimeout:
    call_id: str


@dataclass(frozen=True, slots=True)
class ModelSpeaking:
    pass


@dataclass(frozen=True, slots=True)
class ResponseDone:
    had_tool_calls: bool = False


@dataclass(frozen=True, slots=True)
class ResponseCancelled:
    pass


@dataclass(frozen=True, slots=True)
class PlaybackDrained:
    pass


@dataclass(frozen=True, slots=True)
class ResetTick:
    pass


@dataclass(frozen=True, slots=True)
class WsFailed:
    reason: str


@dataclass(frozen=True, slots=True)
class WsReconnected:
    pass


@dataclass(frozen=True, slots=True)
class BudgetTripped:
    pass


@dataclass(frozen=True, slots=True)
class BudgetOverride:
    pass


@dataclass(frozen=True, slots=True)
class UserStop:
    pass


@dataclass(frozen=True, slots=True)
class WatchdogTick:
    """Polled input from the app watchdog.

    Carries the caller's monotonic timestamp so the pure state machine never
    reads a clock.
    """
    ts_ms: int


MachineInput = (
    PttDown | PttUp | TextCommand | ToolProposed | ToolFinished
    | ApprovalDecision | ApprovalTimeout | ModelSpeaking | ResponseDone
    | ResponseCancelled | PlaybackDrained | ResetTick | WsFailed
    | WsReconnected | BudgetTripped | BudgetOverride | UserStop
    | WatchdogTick
)


# Machine outputs executed by app.py

@dataclass(frozen=True, slots=True)
class ClearInput:
    pass


@dataclass(frozen=True, slots=True)
class OpenMic:
    pass


@dataclass(frozen=True, slots=True)
class CloseMic:
    pass


@dataclass(frozen=True, slots=True)
class CommitInput:
    pass


@dataclass(frozen=True, slots=True)
class CreateResponse:
    pass


@dataclass(frozen=True, slots=True)
class CancelResponse:
    pass


@dataclass(frozen=True, slots=True)
class FlushPlayback:
    pass


@dataclass(frozen=True, slots=True)
class SendText:
    text: str


@dataclass(frozen=True, slots=True)
class ExecTool:
    call: ToolCall


@dataclass(frozen=True, slots=True)
class QueueApproval:
    call: ToolCall


@dataclass(frozen=True, slots=True)
class SendToolResult:
    call_id: str
    ok: bool
    output: str


@dataclass(frozen=True, slots=True)
class EndSession:
    reason: str


@dataclass(frozen=True, slots=True)
class RejectInput:
    """Client-visible refusal when input arrives in a non-accepting phase."""
    reason: str


@dataclass(frozen=True, slots=True)
class AckTurn:
    """Every PTT release is acknowledged: accepted into a turn, or rejected
    with a reason the surface can show. An accepted voiced turn is never
    silently discarded."""
    accepted: bool
    reason: str | None = None


Command = (
    ClearInput | OpenMic | CloseMic | CommitInput | CreateResponse
    | CancelResponse | FlushPlayback | SendText | ExecTool | QueueApproval
    | SendToolResult | EndSession | RejectInput | AckTurn
)
