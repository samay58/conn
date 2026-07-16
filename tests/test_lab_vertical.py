from pathlib import Path

from conn.actions import ActionOutcome
from conn.config import Config
from conn.events import ModelObservation, VisualObservation
from conn.lab.vertical import (
    LAB_COMMAND,
    action_result_recorded,
    build_vertical_app,
    grounded_arguments,
    read_scripted_audio,
    summarize_vertical,
    vertical_command,
    visual_grounding_arguments,
)


def test_vertical_completion_accepts_native_failure_without_transaction_trace() -> None:
    events = [{
        "kind": "tool_result",
        "output": (
            '{"outcome":"failed","dispatch_state":"possibly_dispatched",'
            '"reason_code":"native_bridge_timeout"}'
        ),
    }]

    assert action_result_recorded(events) is True
    assert action_result_recorded([{
        "kind": "tool_result",
        "output": '{"ok":true,"data":{"candidates":[]}}',
    }]) is False


def test_vertical_loop_uses_real_native_harness(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv(
        "CONN_BRIDGE_TOKEN",
        "BwcHBwcHBwcHBwcHBwcHBwcHBwcHBwcHBwcHBwcHBwc=",
    )
    app = build_vertical_app(Config(data_dir=tmp_path))

    assert app.harness._executors is None
    assert app.adapter.scenarios[0]["match"] == [LAB_COMMAND]
    assert app.adapter.scenarios[0]["segments"][0]["tools"] == [
        {
            "name": "computer_ax_snapshot",
            "arguments": {
                "query": "Continue",
                "expected_roles": ["AXCheckBox"],
                "expected_actions": ["AXPress"],
                "result_limit": 1,
            },
        }
    ]


def test_live_vertical_uses_the_production_realtime_adapter(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv(
        "CONN_BRIDGE_TOKEN",
        "BwcHBwcHBwcHBwcHBwcHBwcHBwcHBwcHBwcHBwcHBwc=",
    )
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")

    app = build_vertical_app(
        Config(data_dir=tmp_path),
        scenario="control",
        model_mode="live",
    )

    assert type(app.adapter).__name__ == "OpenAIRealtimeAdapter"
    assert app.harness._executors is None


def test_live_control_uses_a_natural_visible_target_command() -> None:
    assert vertical_command("control", model_mode="scripted") == LAB_COMMAND
    assert vertical_command("control", model_mode="live") == (
        "Click Continue in the current window"
    )
    assert vertical_command("firefox_visual", model_mode="live") == (
        "Click the visible Play button in Firefox"
    )


def test_menu_vertical_uses_semantic_create_without_model_mechanism(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv(
        "CONN_BRIDGE_TOKEN",
        "BwcHBwcHBwcHBwcHBwcHBwcHBwcHBwcHBwcHBwcHBwc=",
    )
    app = build_vertical_app(Config(data_dir=tmp_path), scenario="menu")

    assert app.adapter.scenarios[0]["segments"][0]["tools"] == [{
        "name": "computer_create",
        "arguments": {"kind": "window"},
    }]


def test_firefox_vertical_keeps_the_named_app_goal(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv(
        "CONN_BRIDGE_TOKEN",
        "BwcHBwcHBwcHBwcHBwcHBwcHBwcHBwcHBwcHBwcHBwc=",
    )
    app = build_vertical_app(Config(data_dir=tmp_path), scenario="firefox_open")

    assert app.adapter.scenarios[0]["segments"][0]["tools"] == [{
        "name": "app_open",
        "arguments": {"app": "Firefox"},
    }]


def test_safari_local_vertical_preserves_browser_and_literal_url(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv(
        "CONN_BRIDGE_TOKEN",
        "BwcHBwcHBwcHBwcHBwcHBwcHBwcHBwcHBwcHBwcHBwc=",
    )
    app = build_vertical_app(Config(data_dir=tmp_path), scenario="safari_local")

    assert app.adapter.scenarios[0]["segments"][0]["tools"] == [{
        "name": "browser_navigate",
        "arguments": {
            "url": "http://127.0.0.1:18888/media",
            "browser_scope": "Safari",
        },
    }]


def test_safari_new_tab_uses_semantic_create_without_menu_path(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv(
        "CONN_BRIDGE_TOKEN",
        "BwcHBwcHBwcHBwcHBwcHBwcHBwcHBwcHBwcHBwcHBwc=",
    )
    app = build_vertical_app(Config(data_dir=tmp_path), scenario="safari_tab")

    assert app.adapter.scenarios[0]["segments"][0]["tools"] == [{
        "name": "computer_create",
        "arguments": {"kind": "tab", "app": "Safari"},
    }]


def test_notes_create_uses_semantic_create_without_menu_path(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv(
        "CONN_BRIDGE_TOKEN",
        "BwcHBwcHBwcHBwcHBwcHBwcHBwcHBwcHBwcHBwcHBwc=",
    )
    app = build_vertical_app(Config(data_dir=tmp_path), scenario="notes_create")

    assert app.adapter.scenarios[0]["segments"][0]["tools"] == [{
        "name": "computer_create",
        "arguments": {"kind": "note", "app": "Notes"},
    }]


def test_notes_observe_uses_one_bounded_visual_observation(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv(
        "CONN_BRIDGE_TOKEN",
        "BwcHBwcHBwcHBwcHBwcHBwcHBwcHBwcHBwcHBwcHBwc=",
    )
    app = build_vertical_app(Config(data_dir=tmp_path), scenario="notes_observe")

    assert app.adapter.scenarios[0]["segments"][0]["tools"] == [{
        "name": "computer_visual_observe",
        "arguments": {},
    }]


def test_notes_typing_grounds_one_text_area_before_setting_text(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv(
        "CONN_BRIDGE_TOKEN",
        "BwcHBwcHBwcHBwcHBwcHBwcHBwcHBwcHBwcHBwcHBwc=",
    )
    app = build_vertical_app(Config(data_dir=tmp_path), scenario="notes_type")
    tools = [
        segment["tools"][0]
        for segment in app.adapter.scenarios[0]["segments"]
        if segment.get("tools")
    ]

    assert tools == [
        {
            "name": "computer_ax_snapshot",
            "arguments": {
                "query": "conn lab seed",
                "expected_roles": ["AXTextArea"],
                "result_limit": 1,
            },
        },
        {
            "name": "computer_type_text",
            "arguments": {
                "snapshot_id": "__LAB_SNAPSHOT_ID__",
                "ref": "__LAB_REF__",
                "text": "conn lab scratch",
                "submit": False,
            },
        },
    ]


def test_notes_selection_uses_relative_semantic_intent(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv(
        "CONN_BRIDGE_TOKEN",
        "BwcHBwcHBwcHBwcHBwcHBwcHBwcHBwcHBwcHBwcHBwc=",
    )
    app = build_vertical_app(Config(data_dir=tmp_path), scenario="notes_select")

    assert app.adapter.scenarios[0]["segments"][0]["tools"] == [{
        "name": "computer_select_relative",
        "arguments": {
            "relation": "next",
            "kind": "note",
            "app": "Notes",
        },
    }]


def test_firefox_local_vertical_preserves_browser_and_literal_url(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv(
        "CONN_BRIDGE_TOKEN",
        "BwcHBwcHBwcHBwcHBwcHBwcHBwcHBwcHBwcHBwcHBwc=",
    )
    app = build_vertical_app(Config(data_dir=tmp_path), scenario="firefox_local")

    assert app.adapter.scenarios[0]["segments"][0]["tools"] == [{
        "name": "browser_navigate",
        "arguments": {
            "url": "http://127.0.0.1:18888/media",
            "browser_scope": "Firefox",
        },
    }]


def test_firefox_visual_uses_bounded_current_capture(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv(
        "CONN_BRIDGE_TOKEN",
        "BwcHBwcHBwcHBwcHBwcHBwcHBwcHBwcHBwcHBwcHBwc=",
    )
    app = build_vertical_app(Config(data_dir=tmp_path), scenario="firefox_visual")

    assert isinstance(app.adapter.scenarios[0]["segments"][1]["tools"], list)
    assert app.adapter.scenarios[0]["segments"][1]["tools"][0]["name"] == (
        "computer_visual_observe"
    )
    assert app.adapter.scenarios[0]["segments"][2]["tools"][0]["name"] == (
        "computer_activate"
    )


def test_firefox_space_uses_one_semantic_key(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv(
        "CONN_BRIDGE_TOKEN",
        "BwcHBwcHBwcHBwcHBwcHBwcHBwcHBwcHBwcHBwcHBwc=",
    )
    app = build_vertical_app(Config(data_dir=tmp_path), scenario="firefox_space")

    assert app.adapter.scenarios[0]["segments"][0]["tools"] == [{
        "name": "computer_key",
        "arguments": {"key": "space"},
    }]


def test_visual_vertical_falls_back_only_after_accessibility_finds_nothing(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv(
        "CONN_BRIDGE_TOKEN",
        "BwcHBwcHBwcHBwcHBwcHBwcHBwcHBwcHBwcHBwcHBwc=",
    )
    app = build_vertical_app(Config(data_dir=tmp_path), scenario="visual")
    segments = app.adapter.scenarios[0]["segments"]

    assert segments[0]["tools"][0]["name"] == "computer_ax_snapshot"
    assert segments[1]["tools"] == [{
        "name": "computer_visual_observe",
        "arguments": {},
    }]
    assert segments[2]["tools"][0]["name"] == "computer_activate"
    assert "grounding" in segments[2]["tools"][0]["arguments"]


def test_grounded_arguments_require_one_native_candidate() -> None:
    observation = ModelObservation(
        observation_id="observation",
        snapshot_id="snapshot",
        bundle_id="com.conn.ActionFixture",
        window_id=42,
        text=(
            '{"snapshot_id":"snapshot","candidates":'
            '[{"ref":"e2","role":"AXCheckBox"}]}'
        ),
        byte_count=50,
        estimated_input_tokens=13,
    )

    assert grounded_arguments(observation) == {
        "snapshot_id": "snapshot",
        "ref": "e2",
    }


def test_visual_grounding_binds_current_capture_without_raw_coordinate() -> None:
    observation = VisualObservation(
        capture_id="capture-current",
        image_data_url="data:image/jpeg;base64,/9j/",
        image_sha256="digest",
        image_bytes=3,
        pixel_size=(760, 680),
        scale=1,
        window_id=42,
        bundle_id="com.conn.ActionFixture",
        window_frame={"x": 100, "y": 100, "width": 760, "height": 680},
        captured_ms=10,
        metadata={"capture_id": "capture-current"},
    )

    grounding = visual_grounding_arguments(observation)

    assert grounding["capture_id"] == "capture-current"
    assert grounding["label"] == "Play"
    assert grounding["confidence"] == 0.99
    assert grounding["region"] == {
        "x": 0.4,
        "y": 0.4,
        "width": 0.2,
        "height": 0.2,
    }
    assert "coordinate" not in grounding


def test_scripted_audio_file_is_bounded(tmp_path: Path) -> None:
    audio = tmp_path / "command.pcm"
    audio.write_bytes(b"\x00\x01" * 80)

    assert read_scripted_audio(audio) == b"\x00\x01" * 80

    audio.write_bytes(b"")
    try:
        read_scripted_audio(audio)
    except ValueError as error:
        assert "empty" in str(error)
    else:
        raise AssertionError("empty audio fixture was accepted")


def test_oracle_never_upgrades_dispatch_only_receipt() -> None:
    summary = summarize_vertical(
        trace_events=[{
            "kind": "action_transaction",
            "outcome": ActionOutcome.DISPATCH_ONLY.value,
            "dispatch_state": "dispatched",
        }],
        truth_events=[{"effect": "control_changed", "value": "on"}],
        tool_outputs=[{
            "outcome": ActionOutcome.DISPATCH_ONLY.value,
            "dispatch_state": "dispatched",
            "reason_code": "verification_ceiling",
        }],
    )

    assert summary["machine_receipt"]["outcome"] == "dispatch_only"
    assert summary["independent_oracle"]["verdict"] == "matched"
    assert summary["passed"] is False


def test_verified_receipt_and_single_truth_event_pass() -> None:
    summary = summarize_vertical(
        trace_events=[{
            "kind": "action_transaction",
            "outcome": ActionOutcome.VERIFIED.value,
            "dispatch_state": "dispatched",
        }],
        truth_events=[{"effect": "control_changed", "value": "on"}],
        tool_outputs=[{
            "outcome": ActionOutcome.VERIFIED.value,
            "dispatch_state": "dispatched",
            "reason_code": None,
        }],
    )

    assert summary["independent_oracle"]["effect_count"] == 1
    assert summary["passed"] is True
