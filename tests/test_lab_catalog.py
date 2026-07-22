from pathlib import Path

from conn.lab.catalog import (
    driver_config,
    load_catalog,
    result_matches_manifest,
)
from conn.lab.cli import build_parser


ROOT = Path(__file__).resolve().parents[1]


def test_public_scenarios_come_from_validated_versioned_manifests() -> None:
    catalog = load_catalog(ROOT)

    assert tuple(catalog) == (
        "calendar-next",
        "calendar-open",
        "calendar-today",
        "control",
        "finder-open",
        "finder-search",
        "finder-select",
        "firefox-local",
        "firefox-open",
        "firefox-scroll",
        "firefox-space",
        "firefox-visual",
        "fixture-composed",
        "fixture-scroll",
        "fixture-select",
        "fixture-select-named",
        "fixture-type",
        "menu",
        "notes-create",
        "notes-select",
        "notes-type",
        "preview-next-page",
        "preview-open",
        "preview-scroll",
        "safari-focus",
        "safari-history",
        "safari-local",
        "safari-scroll",
        "safari-tab",
        "safari-visual",
        "terminal-window",
        "visual",
    )
    parser = build_parser()
    for scenario_id, manifest in catalog.items():
        parsed = parser.parse_args(["run", scenario_id])
        assert parsed.scenario == scenario_id
        assert manifest.digest
        driver = driver_config(manifest)
        assert driver.capsule
        assert driver.case
        assert driver.setup.vertical_scenario
        assert driver.oracle.kind == manifest.oracle.kind
        assert set(manifest.initial_state) == {"capsule", "case"}


def test_manifest_checks_receipt_oracle_and_dispatch_count() -> None:
    manifest = load_catalog(ROOT)["safari-tab"]
    passing = {
        "machine_receipt": {
            "outcome": "verified",
            "reason_code": None,
        },
        "independent_oracle": {
            "verdict": "matched",
            "effect": "page_hidden",
            "effect_count": 1,
        },
        "dispatch_count": 1,
        "tool_families": ["computer_ax_snapshot", "computer_create"],
    }

    assert result_matches_manifest(manifest, passing)
    assert not result_matches_manifest(
        manifest,
        passing | {"dispatch_count": 2},
    )
    assert not result_matches_manifest(
        manifest,
        passing | {
            "machine_receipt": {
                "outcome": "no_effect",
                "reason_code": "witness_not_matched",
            }
        },
    )
    assert not result_matches_manifest(
        manifest,
        passing | {
            "machine_receipt": {
                "outcome": "dispatch_only",
                "reason_code": "no_trustworthy_witness",
            }
        },
    )
    assert not result_matches_manifest(
        manifest,
        passing | {
            "independent_oracle": {
                "verdict": "not_matched",
                "effect": "page_hidden",
                "effect_count": 0,
            }
        },
    )


def test_finder_selection_manifest_requires_one_verified_row_selection() -> None:
    manifest = load_catalog(ROOT)["finder-select"]

    assert manifest.expected_dispatch_count == 1
    assert manifest.expected_receipt.outcome == "verified"
    assert manifest.oracle.expected == {"effect": "row_selected"}


def test_fixture_control_contract_names_the_tool_it_actually_dispatches() -> None:
    manifest = load_catalog(ROOT)["control"]

    assert manifest.expected_tool_family == "computer_click"


def test_direct_browser_capsules_start_from_another_signed_app() -> None:
    catalog = load_catalog(ROOT)

    for scenario_id in ("safari-local", "firefox-local"):
        setup = driver_config(catalog[scenario_id]).setup
        assert setup.initial_app == "Terminal"
        assert setup.initial_bundle == "com.apple.Terminal"

    assert catalog["safari-local"].expected_receipt.outcome == "dispatch_only"
    firefox = catalog["firefox-local"]
    assert firefox.expected_receipt.outcome == "dispatch_only"
    assert firefox.expected_receipt.reason_code == "no_trustworthy_witness"
    assert result_matches_manifest(firefox, {
        "machine_receipt": {"outcome": "verified", "reason_code": None},
        "independent_oracle": {
            "verdict": "matched",
            "effect": "page_loaded",
        },
        "dispatch_count": 1,
        "tool_families": ["browser_navigate"],
    })
