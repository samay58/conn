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
        "control",
        "firefox-local",
        "firefox-open",
        "firefox-space",
        "firefox-visual",
        "menu",
        "notes-create",
        "notes-select",
        "notes-type",
        "safari-local",
        "safari-tab",
        "visual",
    )
    parser = build_parser()
    for scenario_id, manifest in catalog.items():
        parsed = parser.parse_args(["run", scenario_id])
        assert parsed.scenario == scenario_id
        assert manifest.digest
        assert driver_config(manifest).vertical_scenario


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
            "independent_oracle": {
                "verdict": "not_matched",
                "effect": "page_hidden",
                "effect_count": 0,
            }
        },
    )
