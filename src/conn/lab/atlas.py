from __future__ import annotations

from enum import StrEnum
from functools import cached_property
import json
from pathlib import Path
from typing import Literal

from pydantic import Field, computed_field, field_validator

from .models import StrictModel


MAX_ATLAS_BYTES = 262_144
MAX_SURFACES = 16
MAX_JOBS = 32


class CapabilityRow(StrictModel):
    surface: str = Field(pattern=r"^[a-z][a-z0-9_]*$", max_length=80)
    job: str = Field(pattern=r"^[a-z][a-z0-9_]*$", max_length=80)


class CapabilityMatrix(StrictModel):
    schema_version: Literal[1]
    frozen: Literal[True]
    surfaces: tuple[str, ...]
    jobs: tuple[str, ...]

    @field_validator("surfaces")
    @classmethod
    def surfaces_are_fixed(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        return _identifiers(value, "surfaces", MAX_SURFACES)

    @field_validator("jobs")
    @classmethod
    def jobs_are_fixed(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        return _identifiers(value, "jobs", MAX_JOBS)

    @computed_field
    @cached_property
    def rows(self) -> tuple[CapabilityRow, ...]:
        return tuple(
            CapabilityRow(surface=surface, job=job)
            for surface in self.surfaces
            for job in self.jobs
        )


class CommandCase(StrictModel):
    id: str = Field(pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$", max_length=80)
    surface: str = Field(pattern=r"^[a-z][a-z0-9_]*$", max_length=80)
    job: str = Field(pattern=r"^[a-z][a-z0-9_]*$", max_length=80)
    utterance: str = Field(min_length=1, max_length=240)


class CommandCorpus(StrictModel):
    schema_version: Literal[1]
    frozen: Literal[True]
    commands: tuple[CommandCase, ...]

    @field_validator("commands")
    @classmethod
    def commands_are_fixed(
        cls, value: tuple[CommandCase, ...]
    ) -> tuple[CommandCase, ...]:
        if len(value) != 20:
            raise ValueError("v1 command corpus must contain exactly 20 commands")
        if len({command.id for command in value}) != len(value):
            raise ValueError("v1 command corpus contains duplicate ids")
        return value


class AtlasExposure(StrEnum):
    EXPOSED = "exposed"
    NOT_EXPOSED = "not_exposed"
    BLOCKED = "blocked"
    UNMEASURED = "unmeasured"


class AtlasRow(StrictModel):
    surface: str = Field(pattern=r"^[a-z][a-z0-9_]*$", max_length=80)
    job: str = Field(pattern=r"^[a-z][a-z0-9_]*$", max_length=80)
    exposure: AtlasExposure
    candidate_count: int | None = Field(default=None, ge=0, le=100_000)
    total_match_count: int | None = Field(default=None, ge=0, le=100_000)
    truncated: bool | None = None
    lane: str | None = Field(default=None, max_length=80)
    witness_family: str | None = Field(default=None, max_length=80)
    latency_ms: int | None = Field(default=None, ge=0, le=3_600_000)
    tool_count: int | None = Field(default=None, ge=0, le=40)
    reason: str = Field(min_length=1, max_length=160)


class AtlasReport(StrictModel):
    schema_version: Literal[1] = 1
    matrix_rows: int = Field(ge=1, le=512)
    rows: tuple[AtlasRow, ...]


class AtlasBlocker(StrictModel):
    job: str
    blocked_surfaces: int = Field(ge=0, le=32)
    surfaces: tuple[str, ...]


def compile_atlas(
    matrix: CapabilityMatrix,
    observations: dict[str, object],
) -> AtlasReport:
    rows = tuple(
        _compile_row(row, observations.get(row.surface))
        for row in matrix.rows
    )
    return AtlasReport(matrix_rows=len(matrix.rows), rows=rows)


def rank_blockers(report: AtlasReport) -> tuple[AtlasBlocker, ...]:
    jobs = sorted({row.job for row in report.rows})
    ranking = []
    for job in jobs:
        surfaces = tuple(sorted(
            row.surface
            for row in report.rows
            if row.job == job and row.exposure is not AtlasExposure.EXPOSED
        ))
        ranking.append(AtlasBlocker(
            job=job,
            blocked_surfaces=len(surfaces),
            surfaces=surfaces,
        ))
    return tuple(sorted(
        ranking,
        key=lambda item: (-item.blocked_surfaces, item.job),
    ))


def _compile_row(row: CapabilityRow, surface_value: object) -> AtlasRow:
    if not isinstance(surface_value, dict):
        return _atlas_row(row, AtlasExposure.UNMEASURED, "surface_not_measured")
    jobs = surface_value.get("jobs")
    if not isinstance(jobs, dict) or row.job not in jobs:
        return _atlas_row(row, AtlasExposure.UNMEASURED, "job_not_measured")
    value = jobs[row.job]
    if not isinstance(value, dict):
        return _atlas_row(row, AtlasExposure.BLOCKED, "observation_invalid")
    if value.get("denied") is True:
        return _atlas_row(row, AtlasExposure.BLOCKED, "native_access_denied")
    if row.job == "app_window_selection":
        exposed = bool(value.get("bundle_id")) and value.get("window_present") is True
        return _atlas_row(
            row,
            AtlasExposure.EXPOSED if exposed else AtlasExposure.NOT_EXPOSED,
            "signed_window_observed" if exposed else "signed_window_not_observed",
        )
    if row.job in {"visual_fallback", "multi_step"}:
        exposed = value.get("available") is True
        reason = value.get("reason_code")
        if not isinstance(reason, str) or not reason:
            reason = "capability_available" if exposed else "capability_not_available"
        return _atlas_row(
            row,
            AtlasExposure.EXPOSED if exposed else AtlasExposure.NOT_EXPOSED,
            reason,
            value,
        )
    count = _bounded_count(value.get("candidate_count"))
    total = _bounded_count(value.get("total_match_count"))
    if count is None or total is None:
        return _atlas_row(row, AtlasExposure.BLOCKED, "candidate_count_invalid")
    return _atlas_row(
        row,
        AtlasExposure.EXPOSED if total > 0 else AtlasExposure.NOT_EXPOSED,
        "named_native_candidate_observed" if total > 0 else "no_named_native_candidate",
        value,
    )


def _atlas_row(
    row: CapabilityRow,
    exposure: AtlasExposure,
    reason: str,
    value: dict | None = None,
) -> AtlasRow:
    value = value or {}
    return AtlasRow(
        surface=row.surface,
        job=row.job,
        exposure=exposure,
        candidate_count=_bounded_count(value.get("candidate_count")),
        total_match_count=_bounded_count(value.get("total_match_count")),
        truncated=(value.get("truncated") if isinstance(value.get("truncated"), bool) else None),
        reason=reason,
    )


def _bounded_count(value: object) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value if 0 <= value <= 100_000 else None


def load_capability_matrix(root: Path) -> CapabilityMatrix:
    return CapabilityMatrix.model_validate(
        _read_bounded(root / "lab" / "capability-matrix.json")
    )


def load_command_corpus(root: Path) -> CommandCorpus:
    return CommandCorpus.model_validate(
        _read_bounded(root / "lab" / "v1-command-corpus.json")
    )


def _read_bounded(path: Path) -> object:
    payload = path.resolve(strict=True).read_bytes()
    if not payload or len(payload) > MAX_ATLAS_BYTES:
        raise RuntimeError("lab_atlas_invalid")
    try:
        return json.loads(payload)
    except ValueError as error:
        raise RuntimeError("lab_atlas_invalid") from error


def _identifiers(
    value: tuple[str, ...], field: str, limit: int
) -> tuple[str, ...]:
    if not 1 <= len(value) <= limit or len(set(value)) != len(value):
        raise ValueError(f"{field} must be unique and bounded")
    if tuple(sorted(value)) != value:
        raise ValueError(f"{field} must be sorted")
    for item in value:
        if (
            not item
            or len(item) > 80
            or not item[0].isalpha()
            or not item.replace("_", "").isalnum()
        ):
            raise ValueError(f"{field} contains an invalid identifier")
    return value
