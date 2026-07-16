from __future__ import annotations

from enum import StrEnum
import hashlib
import json
from typing import Any

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    computed_field,
    field_validator,
    model_validator,
)

from conn.actions import ActionOutcome


MAX_STATE_BYTES = 65_536
MAX_TURNS = 16
MAX_TURN_CHARS = 1_000
MAX_CAPABILITIES = 32


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ScenarioTier(StrEnum):
    FIXTURE = "fixture"
    REAL_APP = "real_app"
    RECOVERY = "recovery"


class ScenarioMode(StrEnum):
    SCRIPTED = "scripted"
    LIVE = "live"


class NavigationGrantState(StrEnum):
    DISABLED = "disabled"
    ACTIVE = "active"
    REVOKED = "revoked"
    SUSPENDED = "suspended"


class FaultPoint(StrEnum):
    BEFORE_PREPARE = "before_prepare"
    AFTER_PREPARE = "after_prepare"
    BEFORE_DISPATCH = "before_dispatch"
    AFTER_FIRST_INPUT = "after_first_input"
    DURING_VERIFICATION = "during_verification"
    DURING_RECEIPT_DELIVERY = "during_receipt_delivery"


class OracleVerdict(StrEnum):
    MATCHED = "matched"
    NOT_MATCHED = "not_matched"
    UNAVAILABLE = "unavailable"


class RunStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    PASSED = "passed"
    FAILED = "failed"
    BLOCKED = "blocked"


def _bounded_json(value: object, field: str) -> object:
    try:
        encoded = json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode()
    except (TypeError, ValueError) as error:
        raise ValueError(f"{field} must contain JSON values") from error
    if len(encoded) > MAX_STATE_BYTES:
        raise ValueError(f"{field} exceeds {MAX_STATE_BYTES} bytes")
    return value


class ScenarioLimits(StrictModel):
    duration_s: float = Field(gt=0, le=900)
    model_responses: int = Field(ge=0, le=20)
    tool_calls: int = Field(ge=0, le=40)
    observation_bytes: int = Field(ge=0, le=10_000_000)
    retries: int = Field(ge=0, le=2)
    live_cost_usd: float = Field(ge=0, le=5)


class ReceiptExpectation(StrictModel):
    outcome: ActionOutcome
    reason_code: str | None = Field(default=None, max_length=160)

    @model_validator(mode="after")
    def reason_matches_outcome(self) -> ReceiptExpectation:
        if self.outcome is ActionOutcome.VERIFIED and self.reason_code is not None:
            raise ValueError("verified expectation cannot carry a reason code")
        if self.outcome is not ActionOutcome.VERIFIED and not self.reason_code:
            raise ValueError("non-verified expectation requires a reason code")
        return self


class OracleSpec(StrictModel):
    kind: str = Field(min_length=1, max_length=80, pattern=r"^[a-z][a-z0-9_]*$")
    expected: dict[str, Any]

    @field_validator("expected")
    @classmethod
    def expected_is_bounded(cls, value: dict[str, Any]) -> dict[str, Any]:
        return _bounded_json(value, "oracle expected")


class ScenarioManifest(StrictModel):
    schema_version: int = Field(ge=1, le=1)
    id: str = Field(
        min_length=1,
        max_length=80,
        pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$",
    )
    description: str = Field(min_length=1, max_length=500)
    tier: ScenarioTier
    mode: ScenarioMode
    initial_state: dict[str, Any]
    spoken_or_typed_turns: tuple[str, ...]
    navigation_grant_state: NavigationGrantState
    fault_schedule: tuple[FaultPoint, ...] = ()
    expected_tool_family: str = Field(
        min_length=1,
        max_length=80,
        pattern=r"^[a-z][a-z0-9_]*$",
    )
    expected_dispatch_count: int = Field(ge=0, le=16)
    expected_receipt: ReceiptExpectation
    oracle: OracleSpec
    limits: ScenarioLimits
    required_capabilities: tuple[str, ...]

    @field_validator("initial_state")
    @classmethod
    def initial_state_is_bounded(cls, value: dict[str, Any]) -> dict[str, Any]:
        return _bounded_json(value, "initial state")

    @field_validator("spoken_or_typed_turns")
    @classmethod
    def turns_are_bounded(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if not 1 <= len(value) <= MAX_TURNS:
            raise ValueError(f"scenario requires 1 to {MAX_TURNS} turns")
        if any(not turn.strip() or len(turn) > MAX_TURN_CHARS for turn in value):
            raise ValueError(
                f"each turn must contain 1 to {MAX_TURN_CHARS} characters"
            )
        return value

    @field_validator("fault_schedule")
    @classmethod
    def fault_schedule_is_bounded(
        cls, value: tuple[FaultPoint, ...]
    ) -> tuple[FaultPoint, ...]:
        if len(value) > 8:
            raise ValueError("fault schedule exceeds 8 boundaries")
        if len(set(value)) != len(value):
            raise ValueError("fault schedule contains duplicate boundaries")
        return value

    @field_validator("required_capabilities")
    @classmethod
    def capabilities_are_bounded(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if len(value) > MAX_CAPABILITIES:
            raise ValueError(f"required capabilities exceed {MAX_CAPABILITIES}")
        if len(set(value)) != len(value):
            raise ValueError("required capabilities contain duplicates")
        for capability in value:
            if not capability or len(capability) > 80:
                raise ValueError("capability names must contain 1 to 80 characters")
            if not capability.replace("_", "").isalnum():
                raise ValueError("capability names may contain letters, digits, and _")
        return value

    @computed_field
    @property
    def digest(self) -> str:
        payload = self.model_dump_json(
            exclude={"digest"}, by_alias=True, exclude_none=False
        ).encode()
        return hashlib.sha256(payload).hexdigest()


class LabRun(StrictModel):
    run_id: str = Field(
        min_length=1,
        max_length=64,
        pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$",
    )
    scenario_id: str = Field(
        min_length=1,
        max_length=80,
        pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$",
    )
    scenario_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    vm_name: str = Field(
        min_length=10,
        max_length=80,
        pattern=r"^conn-lab-[a-z0-9]+(?:-[a-z0-9]+)*$",
    )
    mode: ScenarioMode
    status: RunStatus
    started_ms: int = Field(ge=0)
    finished_ms: int | None = Field(default=None, ge=0)
    artifact_dir: str = Field(min_length=1, max_length=500)
    failure_reason: str | None = Field(default=None, max_length=160)

    @model_validator(mode="after")
    def timestamps_are_ordered(self) -> LabRun:
        if self.finished_ms is not None and self.finished_ms < self.started_ms:
            raise ValueError("finished_ms cannot precede started_ms")
        if self.status in {RunStatus.PASSED, RunStatus.FAILED, RunStatus.BLOCKED}:
            if self.finished_ms is None:
                raise ValueError("terminal run requires finished_ms")
        return self

    @computed_field
    @property
    def duration_ms(self) -> int | None:
        if self.finished_ms is None:
            return None
        return self.finished_ms - self.started_ms


class OracleResult(StrictModel):
    run_id: str = Field(min_length=1, max_length=64)
    scenario_id: str = Field(min_length=1, max_length=80)
    kind: str = Field(min_length=1, max_length=80, pattern=r"^[a-z][a-z0-9_]*$")
    verdict: OracleVerdict
    expected: dict[str, Any]
    actual: dict[str, Any]
    reason: str | None = Field(default=None, max_length=160)

    @field_validator("expected", "actual")
    @classmethod
    def values_are_bounded(cls, value: dict[str, Any]) -> dict[str, Any]:
        return _bounded_json(value, "oracle value")


class ArtifactManifest(StrictModel):
    run_id: str = Field(min_length=1, max_length=64)
    scenario_id: str = Field(min_length=1, max_length=80)
    scenario_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    guest_os_build: str = Field(min_length=1, max_length=80)
    tart_version: str = Field(min_length=1, max_length=40)
    image_digest: str = Field(pattern=r"^sha256:[a-f0-9]{64}$")
    conn_commit: str = Field(pattern=r"^[a-f0-9]{7,40}$")
    dirty_tree_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    binary_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    signing_identity: str = Field(min_length=1, max_length=160)
