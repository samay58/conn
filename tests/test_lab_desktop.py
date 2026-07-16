import pytest

from conn.lab.desktop import (
    WindowRecord,
    approval_point,
    navigation_menu_point,
    notes_new_note_point,
    select_new_window,
)


def window(number: int, owner: str, layer: int, bounds=(0, 0, 20, 20)):
    return WindowRecord(
        number=number,
        owner=owner,
        layer=layer,
        x=bounds[0],
        y=bounds[1],
        width=bounds[2],
        height=bounds[3],
    )


def test_new_status_item_is_selected_by_owner_layer_and_window_identity() -> None:
    before = [window(1, "Control Center", 25)]
    after = [
        *before,
        window(2, "Control Center", 25, (765, 0, 38, 30)),
        window(3, "Conn", 25, (0, 572, 424, 196)),
    ]

    selected = select_new_window(
        before,
        after,
        owner="Control Center",
        layer=25,
    )

    assert selected.number == 2


def test_genuine_window_ambiguity_refuses() -> None:
    after = [
        window(2, "Control Center", 25),
        window(3, "Control Center", 25),
    ]

    with pytest.raises(ValueError, match="ambiguous"):
        select_new_window([], after, owner="Control Center", layer=25)


def test_navigation_target_is_center_of_measured_conn_menu() -> None:
    menu = window(4, "Conn", 101, (728, 31, 290, 270))

    assert navigation_menu_point(menu) == (873, 166)


def test_navigation_target_accepts_policy_guidance_menu_width() -> None:
    menu = window(4, "Conn", 101, (600, 31, 450, 300))

    assert navigation_menu_point(menu) == (825, 181)


def test_unexpected_menu_shape_refuses_pointer_target() -> None:
    with pytest.raises(ValueError, match="unexpected"):
        navigation_menu_point(window(4, "Conn", 101, (0, 0, 800, 800)))


def test_approval_point_targets_approve_in_fallback_panel() -> None:
    panel = window(9, "Conn", 25, (300, 147, 424, 196))

    assert approval_point(panel) == (666, 272)


def test_approval_point_refuses_other_conn_windows() -> None:
    with pytest.raises(ValueError, match="approval"):
        approval_point(window(9, "Conn", 101, (300, 147, 424, 196)))


def test_notes_setup_point_uses_fixed_golden_window_shape() -> None:
    notes = window(12, "Notes", 0, (12, 9, 1000, 660))

    assert notes_new_note_point(notes) == (549, 37)
    with pytest.raises(ValueError, match="Notes"):
        notes_new_note_point(window(12, "Notes", 0, (12, 9, 900, 660)))
