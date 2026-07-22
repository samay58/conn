import json
from pathlib import Path

import pytest

from conn.lab.promotion import (
    candidate_packet,
    load_frozen_incidents,
    promote_file,
)


def test_failure_promotion_keeps_facts_separate_and_drops_private_payloads() -> None:
    source = {
        "sanitized": True,
        "user_goal": "Play the video",
        "app": {"bundle_id": "org.mozilla.firefox", "private_path": "/Users/me"},
        "window": {"id": 42, "title": "Private tab"},
        "model_proposal": {
            "tool": "computer_activate",
            "arguments": {"goal": "Play", "image_bytes": "secret-image"},
        },
        "observations": {"candidate_count": 0, "nodes": ["private tree"]},
        "receipt": {
            "outcome": "dispatch_only",
            "reason_code": "no_trustworthy_witness",
            "dispatch_state": "dispatched",
            "clipboard_body": "secret clipboard",
        },
        "oracle": {"verdict": "matched", "effect": "pointer_play"},
        "limits": {"tool_calls": 6, "duration_s": 180},
        "required_capabilities": ["screen_capture", "pointer"],
        "api_key": "secret-key",
    }

    packet = candidate_packet(source, incident_id="opaque-play")
    encoded = json.dumps(packet.model_dump(mode="json"), sort_keys=True)

    assert packet.review_status == "candidate"
    assert packet.captured_facts.user_goal == "Play the video"
    assert packet.captured_facts.bundle_id == "org.mozilla.firefox"
    assert packet.captured_facts.window_id == 42
    assert packet.expected_behavior is None
    assert packet.missing_setup == ()
    assert packet.unresolved_questions == ()
    assert "secret" not in encoded
    assert "Private tab" not in encoded
    assert "/Users/me" not in encoded
    assert "nodes" not in encoded


def test_unsanitized_source_is_refused() -> None:
    try:
        candidate_packet({"user_goal": "Open private note"}, incident_id="raw")
    except ValueError as error:
        assert str(error) == "promotion_source_not_sanitized"
    else:
        raise AssertionError("unsanitized source was accepted")


@pytest.mark.parametrize("goal", [
    "Open /Users/samay/private.pdf",
    "Type password hunter2",
    "Paste the clipboard secret",
    "Open samay@example.com",
])
def test_promotion_refuses_private_goal_text(goal: str) -> None:
    with pytest.raises(ValueError, match="promotion_goal_not_sanitized"):
        candidate_packet({
            "sanitized": True,
            "user_goal": goal,
        }, incident_id="private-goal")


def test_promotion_file_stays_inside_data_and_writes_candidate(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    source = root / "data" / "reports" / "sanitized.json"
    source.parent.mkdir(parents=True)
    source.write_text(json.dumps({
        "sanitized": True,
        "user_goal": "Open Firefox",
        "app": {"bundle_id": "org.mozilla.firefox"},
        "model_proposal": {"tool": "app_open"},
        "receipt": {"outcome": "verified"},
    }))

    output = promote_file(root, source, incident_id="wrong-browser")

    assert output.is_relative_to(root / "data" / "lab-promotions")
    assert json.loads(output.read_text())["expected_behavior"] is None

    outside = tmp_path / "private.json"
    outside.write_text(source.read_text())
    with pytest.raises(ValueError, match="promotion_source_outside_data"):
        promote_file(root, outside, incident_id="wrong-browser")


def test_promotion_refuses_symlinked_output_root(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    source = root / "data" / "reports" / "sanitized.json"
    source.parent.mkdir(parents=True)
    source.write_text(json.dumps({
        "sanitized": True,
        "user_goal": "Open Firefox",
    }))
    outside = tmp_path / "outside"
    outside.mkdir()
    (root / "data" / "lab-promotions").symlink_to(outside, target_is_directory=True)

    with pytest.raises(ValueError, match="promotion_output_outside_data"):
        promote_file(root, source, incident_id="wrong-browser")


def test_frozen_incidents_name_the_four_approved_failures() -> None:
    root = Path(__file__).parents[1]

    incidents = load_frozen_incidents(root)

    assert tuple(incident.id for incident in incidents) == (
        "july13-menu-target",
        "opaque-play",
        "repeated-zero-candidate",
        "wrong-browser",
    )
    assert all(incident.review_status == "frozen" for incident in incidents)
    assert all(incident.expected_behavior for incident in incidents)
    assert all(
        (root / incident.fixture).is_file()
        for incident in incidents
    )
