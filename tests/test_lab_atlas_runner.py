import json
from pathlib import Path

import pytest

from conn.lab.atlas_runner import capsule_probes, sanitize_native_probe


def test_capsule_probes_cover_the_frozen_surfaces_with_guest_only_setup() -> None:
    probes = capsule_probes()

    assert tuple(probe.surface for probe in probes) == (
        "calendar",
        "finder",
        "firefox",
        "fixture",
        "notes",
        "preview",
        "safari",
        "terminal",
    )
    assert all(probe.expected_bundle for probe in probes)
    ready = {probe.surface: probe.truth_ready for probe in probes}
    assert ready["firefox"] is True
    assert ready["safari"] is True
    assert ready["finder"] is False
    resets = {probe.surface: probe.reset_process for probe in probes}
    assert resets["firefox"] == "firefox"
    assert resets["safari"] is None
    joined = json.dumps([probe.setup_commands for probe in probes])
    assert "/Users/samaydhawan" not in joined
    assert "8787" not in joined
    assert "http://127.0.0.1:18888/atlas" in joined


def test_atlas_marks_the_aqua_session_as_a_lab_guest() -> None:
    source = Path("src/conn/lab/atlas_runner.py").read_text()

    assert '"/bin/launchctl", "setenv", "CONN_LAB_GUEST", "1"' in source


def test_native_probe_sanitizer_keeps_counts_and_drops_private_content() -> None:
    payload = {
        "schema_version": 1,
        "jobs": {
            "app_window_selection": {
                "bundle_id": "com.apple.finder",
                "window_present": True,
                "secure": False,
                "denied": False,
            },
            "control_activation": {
                "bundle_id": "com.apple.finder",
                "candidate_count": 2,
                "total_match_count": 3,
                "truncated": True,
                "secure": False,
                "denied": False,
                "roles": {"AXButton": 2},
                "actions": {"AXPress": 2},
                "label": "Private Project",
            },
            "visual_fallback": {
                "available": True,
                "outcome": "observed",
                "reason_code": "",
                "image_bytes": 1200,
                "pixel_width": 800,
                "pixel_height": 600,
                "bundle_id": "com.apple.finder",
                "image_data_url": "private-image",
            },
        },
        "private_path": "/Users/admin/Private",
    }

    sanitized = sanitize_native_probe(
        payload,
        expected_bundle="com.apple.finder",
    )

    encoded = json.dumps(sanitized, sort_keys=True)
    assert sanitized["jobs"]["control_activation"]["total_match_count"] == 3
    assert sanitized["jobs"]["control_activation"]["roles"] == {
        "AXButton": 2
    }
    assert "Private" not in encoded
    assert "image_data_url" not in encoded


def test_native_probe_refuses_the_wrong_frontmost_app() -> None:
    with pytest.raises(ValueError, match="bundle"):
        sanitize_native_probe(
            {
                "schema_version": 1,
                "jobs": {
                    "app_window_selection": {
                        "bundle_id": "com.apple.Safari",
                        "window_present": True,
                    }
                },
            },
            expected_bundle="com.apple.finder",
        )
