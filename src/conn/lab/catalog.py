from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path

from .models import ScenarioManifest


MAX_CATALOG_BYTES = 1_000_000
MAX_SCENARIOS = 64


@dataclass(frozen=True, slots=True)
class ScenarioDriver:
    fixture_scene: str | None
    vertical_scenario: str
    truth_server_run_id: str | None


def load_catalog(root: Path) -> dict[str, ScenarioManifest]:
    path = root.resolve(strict=True) / "lab" / "scenarios.json"
    payload = path.read_bytes()
    if not payload or len(payload) > MAX_CATALOG_BYTES:
        raise RuntimeError("lab_scenario_catalog_invalid")
    try:
        raw = json.loads(payload)
    except ValueError as error:
        raise RuntimeError("lab_scenario_catalog_invalid") from error
    if not isinstance(raw, list) or not 1 <= len(raw) <= MAX_SCENARIOS:
        raise RuntimeError("lab_scenario_catalog_invalid")
    catalog: dict[str, ScenarioManifest] = {}
    try:
        for value in raw:
            manifest = ScenarioManifest.model_validate(value)
            if manifest.id in catalog:
                raise ValueError("duplicate scenario")
            driver_config(manifest)
            catalog[manifest.id] = manifest
    except (TypeError, ValueError) as error:
        raise RuntimeError("lab_scenario_catalog_invalid") from error
    return dict(sorted(catalog.items()))


def driver_config(manifest: ScenarioManifest) -> ScenarioDriver:
    state = manifest.initial_state
    if set(state) != {
        "fixture_scene",
        "vertical_scenario",
        "truth_server_run_id",
    }:
        raise ValueError("lab scenario driver is invalid")
    fixture = _optional_identifier(state.get("fixture_scene"))
    vertical = _identifier(state.get("vertical_scenario"))
    truth = _optional_run_id(state.get("truth_server_run_id"))
    return ScenarioDriver(fixture, vertical, truth)


def result_matches_manifest(manifest: ScenarioManifest, result: dict) -> bool:
    receipt = result.get("machine_receipt")
    oracle = result.get("independent_oracle")
    expected_receipt = manifest.expected_receipt
    if not isinstance(receipt, dict) or not isinstance(oracle, dict):
        return False
    if receipt.get("outcome") != expected_receipt.outcome.value:
        return False
    if receipt.get("reason_code") != expected_receipt.reason_code:
        return False
    if result.get("dispatch_count") != manifest.expected_dispatch_count:
        return False
    tool_families = result.get("tool_families")
    if (
        not isinstance(tool_families, list)
        or manifest.expected_tool_family not in tool_families
    ):
        return False
    if oracle.get("verdict") != "matched":
        return False
    return all(
        oracle.get(key) == value
        for key, value in manifest.oracle.expected.items()
    )


def _identifier(value: object) -> str:
    if (
        not isinstance(value, str)
        or not value
        or len(value) > 80
        or not value.replace("_", "").isalnum()
    ):
        raise ValueError("lab scenario driver is invalid")
    return value


def _optional_identifier(value: object) -> str | None:
    return None if value is None else _identifier(value)


def _optional_run_id(value: object) -> str | None:
    if value is None:
        return None
    if (
        not isinstance(value, str)
        or not value
        or len(value) > 64
        or any(
            not (character.islower() or character.isdigit() or character == "-")
            for character in value
        )
    ):
        raise ValueError("lab scenario driver is invalid")
    return value
