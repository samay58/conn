import pytest

from conn.config import Config
from conn.events import ResponseProvenance
from conn.realtime.base import (
    RtError,
    RtResponseCancelled,
    RtResponseCreated,
    RtResponseDone,
    RtToolCall,
)
from conn.realtime.openai_ws import OpenAIRealtimeAdapter
from conn.state import ResponseProvenanceLedger


def adapter() -> OpenAIRealtimeAdapter:
    return OpenAIRealtimeAdapter(Config(), tools=[], instructions="")


def test_response_created_exposes_authoritative_server_identity() -> None:
    events = adapter()._normalize({
        "type": "response.created",
        "response": {"id": "response_123"},
    })

    assert events == [RtResponseCreated(response_id="response_123")]


def test_live_response_event_without_identity_fails_closed() -> None:
    events = adapter()._normalize({
        "type": "response.function_call_arguments.done",
        "call_id": "call_123",
        "name": "app_switch",
        "arguments": '{"app":"Safari"}',
    })

    assert events == [RtError(
        message=(
            "protocol_error: missing response_id for "
            "response.function_call_arguments.done"
        ),
        fatal=False,
    )]


def test_tool_call_waits_for_completed_terminal_response() -> None:
    live = adapter()
    live._normalize({"type": "response.created", "response": {"id": "response_1"}})

    early = live._normalize({
        "type": "response.function_call_arguments.done",
        "response_id": "response_1",
        "call_id": "call_1",
        "name": "app_switch",
        "arguments": '{"app":"Safari"}',
    })
    completed = live._normalize({
        "type": "response.done",
        "response": {
            "id": "response_1",
            "status": "completed",
            "output": [{
                "type": "function_call",
                "call_id": "call_1",
                "name": "app_switch",
                "arguments": '{"app":"Safari"}',
            }],
        },
    })

    assert early == []
    assert completed == [
        RtToolCall(
            call_id="call_1",
            name="app_switch",
            arguments_json='{"app":"Safari"}',
            response_id="response_1",
        ),
        RtResponseDone(
            usage={},
            had_tool_calls=True,
            status="completed",
            response_id="response_1",
        ),
    ]


def test_completed_response_discards_buffered_call_missing_from_terminal() -> None:
    live = adapter()
    live._normalize({"type": "response.created", "response": {"id": "response_1"}})
    live._normalize({
        "type": "response.function_call_arguments.done",
        "response_id": "response_1",
        "call_id": "call_1",
        "name": "app_switch",
        "arguments": '{"app":"Safari"}',
    })

    events = live._normalize({
        "type": "response.done",
        "response": {"id": "response_1", "status": "completed", "output": []},
    })

    assert events == [RtResponseDone(
        usage={}, had_tool_calls=False, status="completed", response_id="response_1"
    )]


def test_completed_response_rejects_terminal_call_that_changed() -> None:
    live = adapter()
    live._normalize({"type": "response.created", "response": {"id": "response_1"}})
    live._normalize({
        "type": "response.function_call_arguments.done",
        "response_id": "response_1",
        "call_id": "call_1",
        "name": "app_switch",
        "arguments": '{"app":"Safari"}',
    })

    events = live._normalize({
        "type": "response.done",
        "response": {
            "id": "response_1",
            "status": "completed",
            "output": [{
                "type": "function_call",
                "call_id": "call_1",
                "name": "app_switch",
                "arguments": '{"app":"Notes"}',
            }],
        },
    })

    assert isinstance(events[0], RtError)
    assert "does not match" in events[0].message
    assert events[1].had_tool_calls is False
    assert not any(isinstance(event, RtToolCall) for event in events)


@pytest.mark.parametrize("status", ["failed", "incomplete", "cancelled"])
def test_noncompleted_response_discards_buffered_tool_calls(status: str) -> None:
    live = adapter()
    live._normalize({"type": "response.created", "response": {"id": "response_1"}})
    live._normalize({
        "type": "response.function_call_arguments.done",
        "response_id": "response_1",
        "call_id": "call_1",
        "name": "app_switch",
        "arguments": '{"app":"Safari"}',
    })

    events = live._normalize({
        "type": "response.done",
        "response": {
            "id": "response_1",
            "status": status,
            "output": [{
                "type": "function_call",
                "call_id": "call_1",
                "name": "app_switch",
                "arguments": '{"app":"Safari"}',
            }],
        },
    })

    assert not any(isinstance(event, RtToolCall) for event in events)
    if status == "cancelled":
        assert events == [RtResponseCancelled(response_id="response_1")]
    else:
        assert events == [RtResponseDone(
            usage={},
            had_tool_calls=False,
            status=status,
            response_id="response_1",
        )]


def test_response_creation_binds_server_ids_to_requested_local_epochs() -> None:
    ledger = ResponseProvenanceLedger()
    old = ResponseProvenance("turn_old", response_epoch=1, observation_epoch=4)
    new = ResponseProvenance("turn_new", response_epoch=0, observation_epoch=5)

    ledger.request(old)
    ledger.cancel_current()
    ledger.request(new)

    assert ledger.created("response_old") == old
    assert ledger.created("response_new") == new
    assert ledger.resolve("response_old") is None
    assert ledger.resolve("response_new") == new
    assert ledger.active_response_id == "response_new"


@pytest.mark.parametrize("message", [
    {"type": "response.created", "response": {}},
    {"type": "response.output_audio.delta", "delta": ""},
    {"type": "response.output_text.delta", "delta": "text"},
    {"type": "response.output_audio_transcript.delta", "delta": "text"},
    {"type": "response.function_call_arguments.done"},
    {"type": "response.done", "response": {}},
    {"type": "response.cancelled"},
])
def test_all_live_response_scoped_messages_require_identity(message: dict) -> None:
    [event] = adapter()._normalize(message)

    assert isinstance(event, RtError)
    assert event.message.startswith("protocol_error: missing response_id for ")
