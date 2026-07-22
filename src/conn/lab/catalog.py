from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path

from .capsules import CapsuleOracle, CapsuleSetup, capsule_case
from .models import ScenarioManifest


MAX_CATALOG_BYTES = 1_000_000
MAX_SCENARIOS = 64


@dataclass(frozen=True, slots=True)
class ScenarioDriver:
    capsule: str
    case: str
    setup: CapsuleSetup
    oracle: CapsuleOracle


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
    if set(state) != {"capsule", "case"}:
        raise ValueError("lab scenario driver is invalid")
    capsule = _identifier(state.get("capsule"))
    case = _identifier(state.get("case"))
    selected = capsule_case(capsule, case)
    if selected.oracle.kind != manifest.oracle.kind:
        raise ValueError("lab capsule oracle does not match manifest")
    return ScenarioDriver(
        capsule=capsule,
        case=case,
        setup=selected.setup,
        oracle=selected.oracle,
    )


def result_matches_manifest(manifest: ScenarioManifest, result: dict) -> bool:
    receipt = result.get("machine_receipt")
    oracle = result.get("independent_oracle")
    expected_receipt = manifest.expected_receipt
    if not isinstance(receipt, dict) or not isinstance(oracle, dict):
        return False
    outcome = receipt.get("outcome")
    expected_outcome = expected_receipt.outcome.value
    if expected_outcome == "dispatch_only" and outcome == "verified":
        if receipt.get("reason_code") is not None:
            return False
    elif (
        outcome != expected_outcome
        or receipt.get("reason_code") != expected_receipt.reason_code
    ):
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
