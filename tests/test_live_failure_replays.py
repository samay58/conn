import json
from pathlib import Path


FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "live_failures"


def load_json(name: str) -> dict:
    return json.loads((FIXTURE_ROOT / name).read_text())


def test_live_failure_manifest_links_sanitized_replays_to_source_evidence():
    manifest = load_json("manifest.json")

    assert manifest["schema_version"] == 1
    assert set(manifest["sources"]) == {
        "session_64e67d4bf3",
        "session_a7613a568b",
        "session_4a09e788eb",
        "session_86cb484325",
    }
    for source in manifest["sources"].values():
        assert len(source["trace_sha256"]) == 64
        assert len(source["receipt_sha256"]) == 64
        assert source["trace_schema"] == 3
    cases = manifest["cases"]
    assert {case["id"] for case in cases} == {
        "river_duplicate",
        "firefox_anonymous_video",
        "safari_nested_tabs",
        "notes_collections",
        "notes_delayed_type",
        "direct_url_routing",
        "notes_relative_routing",
        "repeated_snapshot_context",
        "barge_in_splice",
    }
    for case in cases:
        assert case["source_session"].startswith("session_")
        assert case["spoken_command"]
        assert case["current_disposition"]
        assert case["intended_disposition"]
        assert case["fixture"]
        assert case["source_event"]
        assert case["evidence_limitations"]
        assert (FIXTURE_ROOT / case["fixture"]).is_file()


def test_river_fixture_preserves_duplicate_fingerprint_and_unique_structure():
    fixture = load_json("river_duplicate.json")
    matches = [node for node in fixture["nodes"] if node["title"] == "RIVER"]

    assert len(matches) == 2
    assert len({node["fingerprint"] for node in matches}) == 1
    assert len({tuple(node["path"]) for node in matches}) == 2
    assert all("AXPress" in node["supported_actions"] for node in matches)


def test_firefox_fixture_remains_an_anonymous_refusal_control():
    fixture = load_json("firefox_anonymous_video.json")

    assert fixture["expected_candidate_count"] == 0
    assert fixture["intended_disposition"] == "refuse_before_dispatch"
    assert all(not node["title"] and not node["description"]
               for node in fixture["nodes"])
    assert sum(node["frame"] == fixture["window_frame"]
               for node in fixture["nodes"]) >= 3


def test_create_fixtures_preserve_nested_tabs_and_competing_note_collections():
    safari = load_json("safari_nested_tabs.json")
    notes = load_json("notes_collections.json")

    by_ref = {node["ref"]: node for node in safari["nodes"]}
    assert by_ref["tab-1"]["parent_ref"] != "tab-strip"
    assert by_ref[by_ref["tab-1"]["parent_ref"]]["parent_ref"] == "tab-strip"
    assert by_ref["tab-1"]["role"] == "AXRadioButton"

    collections = [node for node in notes["nodes"]
                   if node["role"] in {"AXOutline", "AXTable"}]
    assert {node["role"] for node in collections} == {"AXOutline", "AXTable"}
    assert sum(node["role"] == "AXTable" for node in collections) == 2
    assert notes["genuine_ambiguity_refuses"] is True


def test_replays_pin_routing_context_growth_timeout_and_voice_splice():
    fixture = load_json("python_replays.json")

    assert fixture["direct_url"]["current_tool"] == "browser_search"
    assert fixture["direct_url"]["intended_tool"] == "browser_navigate"
    assert fixture["notes_relative"]["current_tool"] == "phoenix_search"
    assert fixture["notes_relative"]["intended_tool"] == "computer_select_relative"
    assert fixture["repeated_snapshot"]["observations"] == 5
    assert fixture["repeated_snapshot"]["unique_tree_shapes"] == 1
    assert fixture["delayed_type"]["duration_ms"] == 2701
    assert fixture["barge_in"]["observed_transcript"].startswith(
        fixture["barge_in"]["stale_prefix"])
    assert fixture["barge_in"]["intended_transcript"] == (
        "I can't help with destructive actions yet.")
