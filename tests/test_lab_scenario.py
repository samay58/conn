import pytest

from conn.lab.scenario import (
    _wait_for_truth_event,
    _lab_target_absent,
    browser_capsule_passes,
    browser_truth_oracle,
    calendar_period_oracle,
    finder_selection_oracle,
    finder_search_oracle,
    fixture_visual_passes,
    guest_launch_environment,
    has_owner_window,
    notes_type_oracle,
    notes_selection_oracle,
    parse_lab_affordances,
    parse_lab_oracle,
    parse_lab_target,
    parse_frontmost_bundle,
    parse_nonnegative_count,
    parse_notes_selected_object_id,
    parse_notes_titles,
    preview_page_oracle,
    parse_snapshot,
    trace_reached_phase,
    trace_reached_ui_moment,
    window_count_oracle,
)


def test_required_truth_event_fails_closed_on_setup_timeout(tmp_path) -> None:
    truth = tmp_path / "truth.jsonl"
    truth.write_text(
        '{"event":"history_start_loaded","value":"ready"}\n'
    )

    with pytest.raises(RuntimeError, match="guest_truth_event_timeout"):
        _wait_for_truth_event(
            truth,
            event="history_end_loaded",
            timeout_s=0.01,
            required=True,
        )


def test_only_zero_match_target_probe_is_retryable() -> None:
    absent = (
        '{"schema_version":1,"bundle_id":"com.apple.Safari",'
        '"match_count":0,"frame":null}'
    )
    ambiguous = (
        '{"schema_version":1,"bundle_id":"com.apple.Safari",'
        '"match_count":2,"frame":null}'
    )

    assert _lab_target_absent(absent, expected_bundle="com.apple.Safari")
    assert not _lab_target_absent(
        ambiguous, expected_bundle="com.apple.Safari"
    )


def test_lab_affordance_parser_accepts_only_bounded_structural_facts() -> None:
    payload = parse_lab_affordances(
        '{"schema_version":1,"bundle_id":"com.apple.Notes",'
        '"match_count":1,"matches":[{"role":"AXRow","selected":false,'
        '"selected_known":true,"focused":false,"focused_known":true,'
        '"supported_actions":["AXPress"],'
        '"settable_attributes":["AXSelected"],"parent_role":"AXTable",'
        '"parent_supported_actions":[],"parent_settable_attributes":'
        '["AXSelectedRows"],"frame":{"x":10,"y":20,"width":100,'
        '"height":30}}]}',
        expected_bundle="com.apple.Notes",
    )

    assert payload["matches"][0]["supported_actions"] == ["AXPress"]
    with pytest.raises(ValueError, match="affordances"):
        parse_lab_affordances(
            '{"schema_version":1,"bundle_id":"com.apple.Notes",'
            '"match_count":1,"matches":[],"label":"private"}',
            expected_bundle="com.apple.Notes",
        )


def test_preview_page_oracle_requires_one_new_exact_page_value() -> None:
    before = {"bundle_id": "com.apple.Preview", "value_match_count": 0}
    after = {"bundle_id": "com.apple.Preview", "value_match_count": 1}

    assert preview_page_oracle(
        before=before,
        after=after,
        frontmost_bundle="com.apple.Preview",
    )["verdict"] == "matched"
    assert preview_page_oracle(
        before=after,
        after=after,
        frontmost_bundle="com.apple.Preview",
    )["verdict"] == "not_matched"


def test_finder_search_oracle_requires_one_new_exact_value() -> None:
    before = {"bundle_id": "com.apple.finder", "value_match_count": 0}
    after = {"bundle_id": "com.apple.finder", "value_match_count": 1}

    assert finder_search_oracle(
        before=before,
        after=after,
        frontmost_bundle="com.apple.finder",
    )["verdict"] == "matched"
    assert finder_search_oracle(
        before=before,
        after=after | {"value_match_count": 2},
        frontmost_bundle="com.apple.finder",
    )["verdict"] == "not_matched"


def test_finder_selection_oracle_accepts_related_selected_nodes_for_one_item() -> None:
    assert finder_selection_oracle(
        selected_match_count=3,
        value_match_count=1,
        frontmost_bundle="com.apple.finder",
    )["verdict"] == "matched"
    assert finder_selection_oracle(
        selected_match_count=0,
        value_match_count=1,
        frontmost_bundle="com.apple.finder",
    )["verdict"] == "not_matched"


def test_lab_target_parser_requires_one_bounded_frame() -> None:
    payload = parse_lab_target(
        '{"schema_version":1,"bundle_id":"com.apple.iCal",'
        '"match_count":1,"frame":{"x":100,"y":80,"width":20,"height":20}}',
        expected_bundle="com.apple.iCal",
    )
    assert payload["frame"] == {
        "x": 100.0,
        "y": 80.0,
        "width": 20.0,
        "height": 20.0,
    }
    with pytest.raises(ValueError, match="lab target"):
        parse_lab_target(
            '{"schema_version":1,"bundle_id":"com.apple.iCal",'
            '"match_count":2,"frame":null}',
            expected_bundle="com.apple.iCal",
        )


def test_calendar_period_oracle_requires_one_new_exact_period_value() -> None:
    before = {
        "value_match_count": 0,
        "bundle_id": "com.apple.iCal",
    }
    after = {
        "value_match_count": 1,
        "bundle_id": "com.apple.iCal",
    }

    assert calendar_period_oracle(
        before=before,
        after=after,
        frontmost_bundle="com.apple.iCal",
        effect="next_month_visible",
    )["verdict"] == "matched"
    assert calendar_period_oracle(
        before=after,
        after=after,
        frontmost_bundle="com.apple.iCal",
        effect="next_month_visible",
    )["verdict"] == "not_matched"
    assert calendar_period_oracle(
        before=after,
        after=before,
        frontmost_bundle="com.apple.iCal",
        effect="current_month_visible",
    )["verdict"] == "matched"


def test_lab_oracle_parser_requires_bounded_counts_and_exact_bundle() -> None:
    payload = parse_lab_oracle(
        '{"schema_version":1,"bundle_id":"com.apple.finder",'
        '"selected_match_count":1,"focused_match_count":1,\n'
        '"window_title_matches":false,"value_match_count":0,'
        '"label_match_count":1,"focused_match_roles":{"AXTextField":1},'
        '"value_match_roles":{"AXStaticText":1},'
        '"value_hash_match_roles":{"AXStaticText":1},'
        '"page_statuses":["Page 2 of 3"]}',
        expected_bundle="com.apple.finder",
    )
    assert payload["selected_match_count"] == 1
    assert payload["page_statuses"] == ["Page 2 of 3"]
    with pytest.raises(ValueError, match="lab oracle"):
        parse_lab_oracle(
            '{"schema_version":1,"bundle_id":"com.apple.Safari",'
            '"selected_match_count":1,"focused_match_count":1,\n'
            '"window_title_matches":false,"value_match_count":0,'
            '"label_match_count":1,"focused_match_roles":{"AXTextField":1},'
            '"value_match_roles":{"AXStaticText":1},'
            '"value_hash_match_roles":{"AXStaticText":1},'
            '"page_statuses":[]}',
            expected_bundle="com.apple.finder",
        )


def test_guest_launch_environment_is_bounded_to_lab_paths() -> None:
    token = "BwcHBwcHBwcHBwcHBwcHBwcHBwcHBwcHBwcHBwcHBwc="
    environment = guest_launch_environment(token)

    assert environment == {
        "CONN_BRIDGE_TOKEN": token,
        "CONN_DATA_DIR": "/Volumes/My Shared Files/artifacts/data",
        "CONN_LAB_GUEST": "1",
        "CONN_PROJECT_ROOT": "/Volumes/My Shared Files/repo",
        "CONN_PYTHON": "/Volumes/My Shared Files/repo/.venv/bin/python",
        "CONN_SERVER_PORT": "18787",
    }


def test_snapshot_parser_rejects_unbounded_window_list() -> None:
    with pytest.raises(ValueError, match="window"):
        parse_snapshot({
            "screen": {"width": 1024, "height": 768},
            "windows": [{}] * 513,
        })


def test_snapshot_parser_keeps_exact_window_identity() -> None:
    screen, windows = parse_snapshot({
        "screen": {"width": 1024, "height": 768},
        "windows": [{
            "number": 42,
            "owner": "Control Center",
            "layer": 25,
            "x": 765,
            "y": 0,
            "width": 38,
            "height": 30,
        }],
    })

    assert screen == (1024, 768)
    assert windows[0].number == 42


def test_owner_window_check_ignores_other_apps_and_non_window_layers() -> None:
    payload = {
        "screen": {"width": 1024, "height": 768},
        "windows": [
            {
                "number": 1, "owner": "Notes", "layer": 25,
                "x": 0, "y": 0, "width": 30, "height": 30,
            },
            {
                "number": 2, "owner": "Firefox", "layer": 0,
                "x": 0, "y": 30, "width": 900, "height": 600,
            },
        ],
    }

    assert has_owner_window(payload, owner="Notes") is False
    payload["windows"][0]["layer"] = 0
    assert has_owner_window(payload, owner="Notes") is True


def test_frontmost_parser_requires_exact_bundle_identity() -> None:
    assert parse_frontmost_bundle({
        "frontmost_bundle": "org.mozilla.firefox",
    }) == "org.mozilla.firefox"

    with pytest.raises(ValueError, match="frontmost"):
        parse_frontmost_bundle({"frontmost_bundle": ""})


def test_window_count_oracle_requires_one_new_window_in_the_same_app() -> None:
    assert window_count_oracle(
        before=1,
        after=2,
        frontmost_bundle="com.apple.Terminal",
        expected_bundle="com.apple.Terminal",
    )["verdict"] == "matched"
    assert window_count_oracle(
        before=1,
        after=3,
        frontmost_bundle="com.apple.Terminal",
        expected_bundle="com.apple.Terminal",
    )["verdict"] == "not_matched"


def test_browser_truth_oracle_requires_one_exact_event() -> None:
    assert browser_truth_oracle(
        [{"event": "page_loaded", "value": "ready"}],
        event="page_loaded",
        value="ready",
    )["verdict"] == "matched"
    assert browser_truth_oracle(
        [
            {"event": "page_loaded", "value": "ready"},
            {"event": "page_loaded", "value": "ready"},
        ],
        event="page_loaded",
        value="ready",
    )["verdict"] == "not_matched"


def test_visual_capsule_accepts_the_honest_dispatch_only_ceiling() -> None:
    receipt = {
        "outcome": "dispatch_only",
        "reason_code": "no_trustworthy_witness",
    }
    oracle = {
        "verdict": "matched",
        "effect": "pointer_play",
        "effect_count": 1,
    }

    assert browser_capsule_passes(
        scenario="firefox_visual",
        receipt=receipt,
        oracle=oracle,
        transaction_count=1,
        dispatch_count=1,
        actual_bundle="org.mozilla.firefox",
        expected_bundle="org.mozilla.firefox",
    ) is True
    assert receipt["outcome"] == "dispatch_only"


def test_fixture_visual_counts_oracle_match_without_upgrading_receipt() -> None:
    receipt = {
        "outcome": "dispatch_only",
        "reason_code": "no_trustworthy_witness",
    }

    assert fixture_visual_passes(
        receipt=receipt,
        oracle={"verdict": "matched", "effect": "playback_changed"},
        transaction_count=1,
        dispatch_count=1,
    )
    assert receipt["outcome"] == "dispatch_only"


def test_safari_visual_and_history_are_bounded_browser_capsules() -> None:
    visual = {
        "outcome": "dispatch_only",
        "reason_code": "no_trustworthy_witness",
    }
    history = {
        "outcome": "dispatch_only",
        "reason_code": "no_trustworthy_witness",
    }

    assert browser_capsule_passes(
        scenario="safari_visual",
        receipt=visual,
        oracle={"verdict": "matched"},
        transaction_count=1,
        dispatch_count=1,
        actual_bundle="com.apple.Safari",
        expected_bundle="com.apple.Safari",
    )
    assert browser_capsule_passes(
        scenario="safari_history",
        receipt=history,
        oracle={"verdict": "matched"},
        transaction_count=1,
        dispatch_count=1,
        actual_bundle="com.apple.Safari",
        expected_bundle="com.apple.Safari",
    )


def test_notes_store_count_parser_is_bounded() -> None:
    assert parse_nonnegative_count("2\n") == 2
    with pytest.raises(ValueError, match="count"):
        parse_nonnegative_count("-1")
    with pytest.raises(ValueError, match="count"):
        parse_nonnegative_count("10001")


def test_notes_title_parser_requires_a_bounded_string_array() -> None:
    assert parse_notes_titles('["conn lab seed","conn lab second"]') == (
        "conn lab seed",
        "conn lab second",
    )
    with pytest.raises(ValueError, match="titles"):
        parse_notes_titles('{"title":"conn lab seed"}')
    with pytest.raises(ValueError, match="titles"):
        parse_notes_titles('["' + ("x" * 1025) + '"]')


def test_notes_typing_oracle_requires_exact_single_note_and_notes_frontmost() -> None:
    assert notes_type_oracle(
        before=("conn lab seed",),
        after=("conn lab scratch",),
        frontmost_bundle="com.apple.Notes",
    )["verdict"] == "matched"
    assert notes_type_oracle(
        before=("conn lab seed",),
        after=("conn lab seed", "conn lab scratch"),
        frontmost_bundle="com.apple.Notes",
    )["verdict"] == "not_matched"
    assert notes_type_oracle(
        before=("conn lab seed",),
        after=("conn lab scratch",),
        frontmost_bundle="com.apple.Safari",
    )["verdict"] == "not_matched"


def test_notes_selected_object_parser_reads_bounded_window_state() -> None:
    payload = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" '
        '"http://www.apple.com/DTDs/PropertyList-1.0.dtd">'
        '<plist version="1.0"><dict><key>windowStateArchive</key><dict>'
        '<key>currentNoteObjectID</key>'
        '<string>x-coredata://ABCDEF01-2345-6789-ABCD-EF0123456789/'
        'ICNote/p5</string></dict></dict></plist>'
    )

    assert parse_notes_selected_object_id(payload).endswith("/ICNote/p5")
    with pytest.raises(ValueError, match="selected note"):
        parse_notes_selected_object_id("<plist version=\"1.0\"><dict/></plist>")


def test_notes_selection_oracle_requires_previous_exact_note_identity() -> None:
    seed = "x-coredata://ABCDEF01-2345-6789-ABCD-EF0123456789/ICNote/p5"
    second = "x-coredata://ABCDEF01-2345-6789-ABCD-EF0123456789/ICNote/p6"
    assert notes_selection_oracle(
        titles_before=("conn lab seed", "Conn lab second"),
        titles_after=("conn lab seed", "Conn lab second"),
        selected_before=second,
        selected_after=seed,
        expected_selected=seed,
        frontmost_bundle="com.apple.Notes",
    )["verdict"] == "matched"
    assert notes_selection_oracle(
        titles_before=("conn lab seed", "Conn lab second"),
        titles_after=("conn lab seed", "Conn lab second"),
        selected_before=second,
        selected_after=second,
        expected_selected=seed,
        frontmost_bundle="com.apple.Notes",
    )["verdict"] == "not_matched"


def test_trace_phase_wait_ignores_partial_and_other_events(tmp_path) -> None:
    trace_dir = tmp_path / "data" / "traces" / "2026-07-16"
    trace_dir.mkdir(parents=True)
    trace = trace_dir / "session_test.jsonl"
    trace.write_text(
        '{"kind":"phase_change","to_phase":"thinking"}\n'
        '{"kind":"phase_change","to_phase":"awaiting_approval"}\n'
        '{"kind":"ui_ack","moment":"approval"}\n'
        '{"kind":"phase_change"'
    )

    assert trace_reached_phase(tmp_path, "awaiting_approval") is True
    assert trace_reached_phase(tmp_path, "done") is False
    assert trace_reached_ui_moment(tmp_path, "approval") is True
    assert trace_reached_ui_moment(tmp_path, "chip") is False
