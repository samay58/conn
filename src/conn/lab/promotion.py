from __future__ import annotations

import json
import os
from datetime import date
from pathlib import Path
import re
import tempfile
from typing import Any, Literal

from pydantic import Field

from .models import StrictModel


_INCIDENT_ID = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
_IDENTIFIER = re.compile(r"^[a-z][a-z0-9_.-]*$")
_PRIVATE_GOAL = re.compile(
    r"(?i)(?:/(?:users|volumes|private|tmp)/|"
    r"\b(?:password|passcode|secret|token|api[ _-]?key|clipboard)\b|"
    r"[a-z0-9._%+-]+@[a-z0-9.-]+\.[a-z]{2,})"
)
_LIMIT_KEYS = {
    "duration_s",
    "live_cost_usd",
    "model_responses",
    "observation_bytes",
    "retries",
    "tool_calls",
}
MAX_SOURCE_BYTES = 1_000_000


class CapturedFacts(StrictModel):
    user_goal: str = Field(min_length=1, max_length=500)
    bundle_id: str | None = Field(default=None, max_length=255)
    window_id: int | None = Field(default=None, ge=0)
    proposal_tool: str | None = Field(default=None, max_length=80)
    candidate_count: int | None = Field(default=None, ge=0, le=20)
    receipt_outcome: str | None = Field(default=None, max_length=80)
    receipt_reason: str | None = Field(default=None, max_length=160)
    dispatch_state: str | None = Field(default=None, max_length=80)
    oracle_verdict: str | None = Field(default=None, max_length=80)
    oracle_effect: str | None = Field(default=None, max_length=80)
    limits: dict[str, int | float]
    required_capabilities: tuple[str, ...]


class PromotionPacket(StrictModel):
    schema_version: int = Field(default=1, ge=1, le=1)
    incident_id: str
    review_status: Literal["candidate"] = "candidate"
    captured_facts: CapturedFacts
    missing_setup: tuple[str, ...] = ()
    expected_behavior: None = None
    unresolved_questions: tuple[str, ...] = ()
    manifest_draft: dict[str, Any]


class FrozenIncident(StrictModel):
    id: str = Field(pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$", max_length=80)
    source_session: str = Field(pattern=r"^session_[a-zA-Z0-9]+$", max_length=80)
    source_event: str = Field(min_length=1, max_length=160)
    fixture: str = Field(pattern=r"^tests/fixtures/live_failures/[a-z0-9_.-]+$", max_length=240)
    review_status: Literal["frozen"]
    expected_behavior: str = Field(min_length=1, max_length=500)
    required_capabilities: tuple[str, ...]


class FrozenIncidentSet(StrictModel):
    schema_version: Literal[1]
    incidents: tuple[FrozenIncident, ...]


def load_frozen_incidents(root: Path) -> tuple[FrozenIncident, ...]:
    path = root.resolve(strict=True) / "lab" / "frozen-failures.json"
    payload = path.read_bytes()
    if not payload or len(payload) > MAX_SOURCE_BYTES:
        raise ValueError("frozen_incidents_invalid")
    try:
        value = FrozenIncidentSet.model_validate_json(payload)
    except ValueError as error:
        raise ValueError("frozen_incidents_invalid") from error
    ids = tuple(incident.id for incident in value.incidents)
    if len(ids) != 4 or tuple(sorted(ids)) != ids or len(set(ids)) != len(ids):
        raise ValueError("frozen_incidents_invalid")
    for incident in value.incidents:
        fixture = (root / incident.fixture).resolve(strict=True)
        if not fixture.is_relative_to(root / "tests" / "fixtures" / "live_failures"):
            raise ValueError("frozen_incidents_invalid")
    return value.incidents


def candidate_packet(source: dict, *, incident_id: str) -> PromotionPacket:
    if source.get("sanitized") is not True:
        raise ValueError("promotion_source_not_sanitized")
    if not _INCIDENT_ID.fullmatch(incident_id) or len(incident_id) > 80:
        raise ValueError("promotion_incident_id_invalid")

    app = _mapping(source.get("app"))
    window = _mapping(source.get("window"))
    proposal = _mapping(source.get("model_proposal"))
    observation = _mapping(source.get("observations"))
    receipt = _mapping(source.get("receipt"))
    oracle = _mapping(source.get("oracle"))
    limits = _bounded_limits(_mapping(source.get("limits")))
    capabilities = _capabilities(source.get("required_capabilities"))
    goal = _sanitized_goal(source.get("user_goal"))
    if goal is None:
        raise ValueError("promotion_goal_not_sanitized")

    facts = CapturedFacts(
        user_goal=goal,
        bundle_id=_identifier(app.get("bundle_id"), 255),
        window_id=_integer(window.get("id"), ceiling=2**63 - 1),
        proposal_tool=_identifier(proposal.get("tool"), 80),
        candidate_count=_integer(observation.get("candidate_count"), ceiling=20),
        receipt_outcome=_identifier(receipt.get("outcome"), 80),
        receipt_reason=_identifier(receipt.get("reason_code"), 160),
        dispatch_state=_identifier(receipt.get("dispatch_state"), 80),
        oracle_verdict=_identifier(oracle.get("verdict"), 80),
        oracle_effect=_identifier(oracle.get("effect"), 80),
        limits=limits,
        required_capabilities=capabilities,
    )
    missing = tuple(
        name
        for name, value in (
            ("bundle_id", facts.bundle_id),
            ("proposal_tool", facts.proposal_tool),
            ("receipt", facts.receipt_outcome),
        )
        if value is None
    )
    return PromotionPacket(
        incident_id=incident_id,
        captured_facts=facts,
        missing_setup=missing,
        manifest_draft={
            "id": incident_id,
            "description": goal,
            "expected_receipt": None,
            "oracle": None,
            "review_required": True,
        },
    )


def promote_file(root: Path, source: Path, *, incident_id: str) -> Path:
    root = root.resolve(strict=True)
    data_root = (root / "data").resolve(strict=True)
    source = source.resolve(strict=True)
    if not source.is_relative_to(data_root):
        raise ValueError("promotion_source_outside_data")
    payload = source.read_bytes()
    if not payload or len(payload) > MAX_SOURCE_BYTES:
        raise ValueError("promotion_source_invalid")
    try:
        value = json.loads(payload)
    except ValueError as error:
        raise ValueError("promotion_source_invalid") from error
    if not isinstance(value, dict):
        raise ValueError("promotion_source_invalid")
    packet = candidate_packet(value, incident_id=incident_id)
    promotion_root = data_root / "lab-promotions"
    promotion_root.mkdir(parents=True, exist_ok=True)
    promotion_root = promotion_root.resolve(strict=True)
    if not promotion_root.is_relative_to(data_root):
        raise ValueError("promotion_output_outside_data")
    output_dir = promotion_root / date.today().isoformat()
    output_dir.mkdir(parents=False, exist_ok=True)
    output_dir = output_dir.resolve(strict=True)
    if not output_dir.is_relative_to(promotion_root):
        raise ValueError("promotion_output_outside_data")
    output = output_dir / f"{incident_id}.json"
    if output.exists():
        raise ValueError("promotion_candidate_exists")
    content = packet.model_dump_json(indent=2) + "\n"
    descriptor, temporary = tempfile.mkstemp(
        prefix=f".{incident_id}.", dir=output_dir
    )
    try:
        with os.fdopen(descriptor, "w") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.link(temporary, output)
    finally:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
    return output


def _mapping(value: object) -> dict:
    return value if isinstance(value, dict) else {}


def _text(value: object, limit: int) -> str | None:
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    return stripped if 0 < len(stripped) <= limit else None


def _sanitized_goal(value: object) -> str | None:
    text = _text(value, 500)
    if text is None or _PRIVATE_GOAL.search(text):
        return None
    if any(ord(character) < 32 for character in text):
        return None
    return text


def _identifier(value: object, limit: int) -> str | None:
    text = _text(value, limit)
    return text if text is not None and _IDENTIFIER.fullmatch(text) else None


def _integer(value: object, *, ceiling: int) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value if 0 <= value <= ceiling else None


def _bounded_limits(value: dict) -> dict[str, int | float]:
    limits: dict[str, int | float] = {}
    for key in sorted(_LIMIT_KEYS):
        item = value.get(key)
        if isinstance(item, bool) or not isinstance(item, (int, float)):
            continue
        if item < 0 or item > 10_000_000:
            continue
        limits[key] = item
    return limits


def _capabilities(value: object) -> tuple[str, ...]:
    if not isinstance(value, list) or len(value) > 32:
        return ()
    accepted = []
    for item in value:
        identifier = _identifier(item, 80)
        if identifier is not None and identifier not in accepted:
            accepted.append(identifier)
    return tuple(accepted)
