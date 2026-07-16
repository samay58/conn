from __future__ import annotations

import pytest
from pydantic import ValidationError

from conn.lab.models import (
    ArtifactManifest,
    LabRun,
    OracleResult,
    OracleSpec,
    ReceiptExpectation,
    ScenarioLimits,
    ScenarioManifest,
)


def scenario_payload() -> dict:
    return {
        "schema_version": 1,
        "id": "fixture-no-effect",
        "description": "Press a control that reports dispatch without an effect.",
        "tier": "fixture",
        "mode": "scripted",
        "initial_state": {"scene": "no_effect"},
        "spoken_or_typed_turns": ["Press the no-effect control"],
        "navigation_grant_state": "active",
        "fault_schedule": ["during_verification"],
        "expected_tool_family": "computer_click",
        "expected_dispatch_count": 1,
        "expected_receipt": {
            "outcome": "no_effect",
            "reason_code": "effect_not_observed",
        },
        "oracle": {
            "kind": "fixture_truth",
            "expected": {"effect_count": 0},
        },
        "limits": {
            "duration_s": 30,
            "model_responses": 2,
            "tool_calls": 3,
            "observation_bytes": 1_200_000,
            "retries": 0,
            "live_cost_usd": 0,
        },
        "required_capabilities": ["accessibility", "signed_bridge"],
    }


def test_scenario_manifest_is_strict_and_bounded() -> None:
    scenario = ScenarioManifest.model_validate(scenario_payload())

    assert scenario.id == "fixture-no-effect"
    assert scenario.limits.tool_calls == 3
    assert scenario.expected_receipt.outcome.value == "no_effect"

    unknown_fault = scenario_payload()
    unknown_fault["fault_schedule"] = ["after_everything"]
    with pytest.raises(ValidationError):
        ScenarioManifest.model_validate(unknown_fault)

    oversized_turn = scenario_payload()
    oversized_turn["spoken_or_typed_turns"] = ["x" * 1_001]
    with pytest.raises(ValidationError):
        ScenarioManifest.model_validate(oversized_turn)


def test_run_oracle_and_artifact_records_share_scenario_identity() -> None:
    run = LabRun(
        run_id="run-20260716-a1",
        scenario_id="fixture-no-effect",
        scenario_digest="a" * 64,
        vm_name="conn-lab-run-20260716-a1",
        mode="scripted",
        status="passed",
        started_ms=100,
        finished_ms=450,
        artifact_dir="data/lab-runs/2026-07-16/run-20260716-a1",
    )
    oracle = OracleResult(
        run_id=run.run_id,
        scenario_id=run.scenario_id,
        kind="fixture_truth",
        verdict="matched",
        expected={"effect_count": 0},
        actual={"effect_count": 0},
    )
    artifact = ArtifactManifest(
        run_id=run.run_id,
        scenario_id=run.scenario_id,
        scenario_digest=run.scenario_digest,
        guest_os_build="25F71",
        tart_version="2.32.1",
        image_digest="sha256:" + "b" * 64,
        conn_commit="75e138c",
        dirty_tree_digest="c" * 64,
        binary_sha256="d" * 64,
        signing_identity="Conn Dev Signing",
    )

    assert oracle.verdict.value == "matched"
    assert artifact.run_id == run.run_id
    assert run.duration_ms == 350


def test_individual_models_reject_unbounded_values() -> None:
    with pytest.raises(ValidationError):
        ScenarioLimits(
            duration_s=901,
            model_responses=1,
            tool_calls=1,
            observation_bytes=1,
            retries=0,
            live_cost_usd=0,
        )
    with pytest.raises(ValidationError):
        OracleSpec(kind="fixture_truth", expected={"blob": "x" * 70_000})
    with pytest.raises(ValidationError):
        ReceiptExpectation(outcome="verified", reason_code="x" * 161)
