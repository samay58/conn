from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class CapsuleSetup:
    vertical_scenario: str
    fixture_scene: str | None = None
    truth_server_run_id: str | None = None
    expected_bundle: str | None = None
    initial_app: str | None = None
    initial_bundle: str | None = None
    window_owner: str | None = None


@dataclass(frozen=True, slots=True)
class CapsuleOracle:
    kind: str


@dataclass(frozen=True, slots=True)
class CapsuleCase:
    setup: CapsuleSetup
    oracle: CapsuleOracle


CAPSULES: dict[str, dict[str, CapsuleCase]] = {
    "calendar": {
        "next": CapsuleCase(
            CapsuleSetup("calendar_next"),
            CapsuleOracle("calendar_period"),
        ),
        "open": CapsuleCase(
            CapsuleSetup("calendar_open", expected_bundle="com.apple.iCal"),
            CapsuleOracle("app_identity"),
        ),
        "today": CapsuleCase(
            CapsuleSetup("calendar_today"),
            CapsuleOracle("calendar_period"),
        ),
    },
    "finder": {
        "open": CapsuleCase(
            CapsuleSetup("finder_open", expected_bundle="com.apple.finder"),
            CapsuleOracle("app_identity"),
        ),
        "search": CapsuleCase(
            CapsuleSetup("finder_search"),
            CapsuleOracle("finder_search"),
        ),
        "select": CapsuleCase(
            CapsuleSetup("finder_select"),
            CapsuleOracle("finder_selection"),
        ),
    },
    "firefox": {
        "local": CapsuleCase(
            CapsuleSetup(
                "firefox_local",
                truth_server_run_id="firefox-local",
                initial_app="Terminal",
                initial_bundle="com.apple.Terminal",
            ),
            CapsuleOracle("browser_truth"),
        ),
        "open": CapsuleCase(
            CapsuleSetup("firefox_open", expected_bundle="org.mozilla.firefox"),
            CapsuleOracle("app_identity"),
        ),
        "space": CapsuleCase(
            CapsuleSetup("firefox_space", truth_server_run_id="firefox-space"),
            CapsuleOracle("browser_truth"),
        ),
        "scroll": CapsuleCase(
            CapsuleSetup(
                "firefox_scroll", truth_server_run_id="firefox-scroll"
            ),
            CapsuleOracle("browser_truth"),
        ),
        "visual": CapsuleCase(
            CapsuleSetup("firefox_visual", truth_server_run_id="firefox-visual"),
            CapsuleOracle("browser_truth"),
        ),
    },
    "fixture": {
        "composed": CapsuleCase(
            CapsuleSetup(
                "fixture_composed",
                fixture_scene="composed",
            ),
            CapsuleOracle("fixture_truth"),
        ),
        "control": CapsuleCase(
            CapsuleSetup("control", fixture_scene="unique_control"),
            CapsuleOracle("fixture_truth"),
        ),
        "scroll": CapsuleCase(
            CapsuleSetup("fixture_scroll", fixture_scene="scroll_target"),
            CapsuleOracle("fixture_truth"),
        ),
        "select": CapsuleCase(
            CapsuleSetup("fixture_select", fixture_scene="selectable_list"),
            CapsuleOracle("fixture_truth"),
        ),
        "select_named": CapsuleCase(
            CapsuleSetup(
                "fixture_select_named", fixture_scene="selectable_list"
            ),
            CapsuleOracle("fixture_truth"),
        ),
        "type": CapsuleCase(
            CapsuleSetup("fixture_type", fixture_scene="text_field"),
            CapsuleOracle("fixture_truth"),
        ),
        "menu": CapsuleCase(
            CapsuleSetup("menu", fixture_scene="menu_recapture"),
            CapsuleOracle("fixture_truth"),
        ),
        "visual": CapsuleCase(
            CapsuleSetup("visual", fixture_scene="opaque_media"),
            CapsuleOracle("fixture_truth"),
        ),
    },
    "notes": {
        "create": CapsuleCase(
            CapsuleSetup("notes_create"),
            CapsuleOracle("notes_store"),
        ),
        "select": CapsuleCase(
            CapsuleSetup("notes_select"),
            CapsuleOracle("notes_store"),
        ),
        "type": CapsuleCase(
            CapsuleSetup("notes_type"),
            CapsuleOracle("notes_store"),
        ),
    },
    "preview": {
        "next_page": CapsuleCase(
            CapsuleSetup("preview_next_page"),
            CapsuleOracle("preview_page"),
        ),
        "open": CapsuleCase(
            CapsuleSetup("preview_open", expected_bundle="com.apple.Preview"),
            CapsuleOracle("app_identity"),
        ),
        "scroll": CapsuleCase(
            CapsuleSetup("preview_scroll"),
            CapsuleOracle("preview_page"),
        ),
    },
    "safari": {
        "focus": CapsuleCase(
            CapsuleSetup("safari_focus", truth_server_run_id="safari-focus"),
            CapsuleOracle("browser_truth"),
        ),
        "history": CapsuleCase(
            CapsuleSetup(
                "safari_history", truth_server_run_id="safari-history"
            ),
            CapsuleOracle("browser_truth"),
        ),
        "local": CapsuleCase(
            CapsuleSetup(
                "safari_local",
                truth_server_run_id="safari-local",
                initial_app="Terminal",
                initial_bundle="com.apple.Terminal",
            ),
            CapsuleOracle("browser_truth"),
        ),
        "scroll": CapsuleCase(
            CapsuleSetup("safari_scroll", truth_server_run_id="safari-scroll"),
            CapsuleOracle("browser_truth"),
        ),
        "tab": CapsuleCase(
            CapsuleSetup("safari_tab", truth_server_run_id="safari-tab"),
            CapsuleOracle("browser_truth"),
        ),
        "visual": CapsuleCase(
            CapsuleSetup(
                "safari_visual", truth_server_run_id="safari-visual"
            ),
            CapsuleOracle("browser_truth"),
        ),
    },
    "terminal": {
        "window": CapsuleCase(
            CapsuleSetup(
                "terminal_window",
                initial_app="Terminal",
                initial_bundle="com.apple.Terminal",
                window_owner="Terminal",
            ),
            CapsuleOracle("window_count"),
        ),
    },
}


def capsule_case(capsule: str, case: str) -> CapsuleCase:
    try:
        return CAPSULES[capsule][case]
    except KeyError as error:
        raise ValueError("lab capsule case is invalid") from error
