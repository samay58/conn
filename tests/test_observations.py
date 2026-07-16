import base64
import hashlib
import json

import pytest

from conn.events import Gate, ToolCall, ToolFinished
from conn.observations import (
    MAX_MODEL_OBSERVATION_BYTES,
    ObservationQuery,
    ObservationValidationError,
    parse_model_observation,
    parse_visual_observation,
)
from conn.state import SessionStateMachine


def native_observation(*, candidates=None) -> dict:
    candidates = candidates if candidates is not None else []
    data = {
        "snapshot_id": "snapshot_1",
        "observation_id": "observation_1",
        "turn_id": "turn_1",
        "observation_epoch": 2,
        "bundle_id": "org.mozilla.firefox",
        "window_id": 91,
        "candidate_count": len(candidates),
        "candidates": candidates,
    }
    data["candidate_bytes"] = len(
        json.dumps(candidates, separators=(",", ":"), ensure_ascii=False).encode()
    )
    return data


def native_visual_observation() -> dict:
    image = b"\xff\xd8\xffbounded-jpeg"
    return {
        "capture_id": "capture_1",
        "image_data_url": (
            "data:image/jpeg;base64," + base64.b64encode(image).decode()
        ),
        "image_sha256": hashlib.sha256(image).hexdigest(),
        "image_bytes": len(image),
        "mime_type": "image/jpeg",
        "pixel_width": 1280,
        "pixel_height": 720,
        "scale": 1.6,
        "window_id": 91,
        "bundle_id": "org.mozilla.firefox",
        "window_frame": {"x": 10, "y": 20, "width": 800, "height": 450},
        "captured_ms": 1234,
        "excluded_conn_surfaces": True,
    }


def test_query_normalizes_and_bounds_every_wire_field():
    query = ObservationQuery.from_tool_arguments({
        "query": "play video",
        "expected_roles": ["AXButton"],
        "expected_actions": ["AXPress"],
        "scope": "descendant",
        "ancestor_ref": "player",
        "result_limit": 99,
        "include_menu": True,
    })

    assert query.as_wire() == {
        "search_terms": ["play", "video"],
        "expected_roles": ["AXButton"],
        "expected_actions": ["AXPress"],
        "scope": "descendant",
        "ancestor_ref": "player",
        "result_limit": 20,
        "include_menu": True,
    }


def test_candidate_observation_rejects_raw_trees_and_oversized_payloads():
    with pytest.raises(ObservationValidationError, match="raw_tree_forbidden"):
        parse_model_observation({**native_observation(), "nodes": []})

    data = native_observation(candidates=[{
        "ref": f"play-{index}",
        "label": "x" * 160,
        "role": "AXButton",
        "supported_actions": ["AXPress"],
        "ancestor_trail": ["a" * 80] * 4,
        "score": 10,
        "score_reasons": ["label_contains"],
        "descriptor": {
            "label": "x" * 160,
            "role": "AXButton",
            "ancestor_trail": ["a" * 80] * 4,
        },
    } for index in range(20)])
    with pytest.raises(ObservationValidationError, match="payload_too_large"):
        parse_model_observation(data)


def test_typed_observation_crosses_the_state_machine_unchanged():
    observation = parse_model_observation(native_observation())
    machine = SessionStateMachine(computer_mutations=set())
    machine.handle(__import__("conn.events", fromlist=["TextCommand"]).TextCommand("look"))
    call = ToolCall(
        call_id="call_1", name="computer_ax_snapshot", arguments={},
        gate=Gate.AUTO, preview="Read accessibility snapshot",
        turn_id="turn_1", response_epoch=1, observation_epoch=1,
    )
    commands = machine.handle(__import__("conn.events", fromlist=["ToolProposed"]).ToolProposed(call))
    running = commands[0].call

    commands = machine.handle(ToolFinished(
        call_id=running.call_id,
        ok=True,
        output=json.dumps({"ok": True, "data": native_observation()}),
        turn_id=running.turn_id,
        response_epoch=running.response_epoch,
        observation_epoch=running.observation_epoch,
        execution_id=running.execution_id,
        model_observation=observation,
    ))

    sent = next(command for command in commands if command.__class__.__name__ == "SendToolResult")
    assert sent.model_observation is observation


def test_visual_observation_validates_bytes_digest_and_metadata():
    observation = parse_visual_observation(native_visual_observation())

    assert observation.capture_id == "capture_1"
    assert observation.bundle_id == "org.mozilla.firefox"
    assert observation.pixel_size == (1280, 720)
    assert observation.metadata["image_sha256"] == native_visual_observation()[
        "image_sha256"
    ]
    assert "image_data_url" not in observation.metadata


@pytest.mark.parametrize(
    "field,value,error",
    [
        ("image_sha256", "0" * 64, "image_digest_mismatch"),
        ("image_bytes", 99, "image_size_mismatch"),
        ("pixel_width", 1281, "visual_dimensions_exceeded"),
        ("excluded_conn_surfaces", False, "conn_surfaces_not_excluded"),
    ],
)
def test_visual_observation_rejects_untrusted_native_payload(field, value, error):
    payload = native_visual_observation()
    payload[field] = value

    with pytest.raises(ObservationValidationError, match=error):
        parse_visual_observation(payload)
