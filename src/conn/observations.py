from __future__ import annotations

import base64
import binascii
import hashlib
import json
import math
import re
from dataclasses import dataclass

from .events import ModelObservation, VisualObservation

MAX_MODEL_OBSERVATION_BYTES = 16_384
MAX_CANDIDATES = 20
MAX_VISUAL_IMAGE_BYTES = 1_200_000
MAX_VISUAL_DATA_URL_BYTES = 1_600_023
MAX_VISUAL_LONG_EDGE = 1_280
_SCOPE = {"current_window", "current_app", "descendant"}
_SYMBOL = re.compile(r"^AX[A-Za-z0-9_]{1,62}$")


class ObservationValidationError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class ObservationQuery:
    search_terms: tuple[str, ...] = ()
    expected_roles: tuple[str, ...] = ()
    expected_actions: tuple[str, ...] = ()
    scope: str = "current_window"
    ancestor_ref: str | None = None
    result_limit: int = 20
    include_menu: bool = False

    @classmethod
    def from_tool_arguments(cls, arguments: dict | None) -> ObservationQuery:
        arguments = arguments if isinstance(arguments, dict) else {}
        query = arguments.get("query")
        raw_terms = arguments.get("search_terms")
        if not isinstance(raw_terms, list):
            raw_terms = str(query or "").split()
        scope = arguments.get("scope")
        ancestor = arguments.get("ancestor_ref")
        limit = arguments.get("result_limit", 20)
        if not isinstance(limit, int) or isinstance(limit, bool):
            limit = 20
        return cls(
            search_terms=_bounded_strings(raw_terms, count=8, length=128),
            expected_roles=_bounded_symbols(arguments.get("expected_roles")),
            expected_actions=_bounded_symbols(arguments.get("expected_actions")),
            scope=scope if scope in _SCOPE else "current_window",
            ancestor_ref=_bounded_text(ancestor, 128),
            result_limit=min(max(limit, 1), MAX_CANDIDATES),
            include_menu=arguments.get("include_menu") is True,
        )

    def as_wire(self) -> dict:
        return {
            "search_terms": list(self.search_terms),
            "expected_roles": list(self.expected_roles),
            "expected_actions": list(self.expected_actions),
            "scope": self.scope,
            "ancestor_ref": self.ancestor_ref,
            "result_limit": self.result_limit,
            "include_menu": self.include_menu,
        }


def parse_visual_observation(data: object) -> VisualObservation:
    if not isinstance(data, dict):
        raise ObservationValidationError("visual_observation_not_object")
    data_url = data.get("image_data_url")
    prefix = "data:image/jpeg;base64,"
    if not isinstance(data_url, str) or not data_url.startswith(prefix):
        raise ObservationValidationError("invalid_visual_image_url")
    if len(data_url.encode()) > MAX_VISUAL_DATA_URL_BYTES:
        raise ObservationValidationError("visual_payload_too_large")
    try:
        image = base64.b64decode(data_url[len(prefix):], validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ObservationValidationError("invalid_visual_image_base64") from exc
    if not image.startswith(b"\xff\xd8\xff"):
        raise ObservationValidationError("invalid_visual_image_format")
    if not image or len(image) > MAX_VISUAL_IMAGE_BYTES:
        raise ObservationValidationError("visual_payload_too_large")
    if data.get("image_bytes") != len(image):
        raise ObservationValidationError("image_size_mismatch")
    digest = hashlib.sha256(image).hexdigest()
    if data.get("image_sha256") != digest:
        raise ObservationValidationError("image_digest_mismatch")
    width = data.get("pixel_width")
    height = data.get("pixel_height")
    if any(not isinstance(value, int) or isinstance(value, bool) or value <= 0
           for value in (width, height)):
        raise ObservationValidationError("invalid_visual_dimensions")
    if max(width, height) > MAX_VISUAL_LONG_EDGE:
        raise ObservationValidationError("visual_dimensions_exceeded")
    scale = data.get("scale")
    if not isinstance(scale, (int, float)) or isinstance(scale, bool) or not math.isfinite(scale) or scale <= 0:
        raise ObservationValidationError("invalid_visual_scale")
    frame = data.get("window_frame")
    if not isinstance(frame, dict) or set(frame) != {"x", "y", "width", "height"}:
        raise ObservationValidationError("invalid_visual_window_frame")
    for key, value in frame.items():
        if not isinstance(value, (int, float)) or isinstance(value, bool) or not math.isfinite(value):
            raise ObservationValidationError("invalid_visual_window_frame")
        if key in {"width", "height"} and value <= 0:
            raise ObservationValidationError("invalid_visual_window_frame")
    if data.get("excluded_conn_surfaces") is not True:
        raise ObservationValidationError("conn_surfaces_not_excluded")
    if data.get("mime_type") != "image/jpeg":
        raise ObservationValidationError("invalid_visual_mime_type")
    bundle_id = data.get("bundle_id")
    if not isinstance(bundle_id, str) or not 0 < len(bundle_id) <= 255:
        raise ObservationValidationError("invalid_bundle_id")
    window_id = data.get("window_id")
    if not isinstance(window_id, int) or isinstance(window_id, bool) or not 0 < window_id <= 0xFFFFFFFF:
        raise ObservationValidationError("invalid_window_id")
    captured_ms = data.get("captured_ms")
    if not isinstance(captured_ms, int) or isinstance(captured_ms, bool) or captured_ms < 0:
        raise ObservationValidationError("invalid_visual_capture_time")
    metadata = {
        "capture_id": data.get("capture_id"),
        "image_sha256": digest,
        "image_bytes": len(image),
        "mime_type": "image/jpeg",
        "pixel_width": width,
        "pixel_height": height,
        "scale": float(scale),
        "window_id": window_id,
        "bundle_id": bundle_id,
        "window_frame": {key: float(value) for key, value in frame.items()},
        "captured_ms": captured_ms,
        "excluded_conn_surfaces": True,
    }
    return VisualObservation(
        capture_id=_required_id(data.get("capture_id"), "capture_id"),
        image_data_url=data_url,
        image_sha256=digest,
        image_bytes=len(image),
        pixel_size=(width, height),
        scale=float(scale),
        window_id=window_id,
        bundle_id=bundle_id,
        window_frame={key: float(value) for key, value in frame.items()},
        captured_ms=captured_ms,
        metadata=metadata,
    )


def parse_model_observation(data: object) -> ModelObservation:
    if not isinstance(data, dict):
        raise ObservationValidationError("observation_not_object")
    if "nodes" in data:
        raise ObservationValidationError("raw_tree_forbidden")
    candidates = data.get("candidates")
    if not isinstance(candidates, list):
        raise ObservationValidationError("candidates_not_array")
    if len(candidates) > MAX_CANDIDATES:
        raise ObservationValidationError("candidate_limit_exceeded")
    if data.get("candidate_count") != len(candidates):
        raise ObservationValidationError("candidate_count_mismatch")
    for candidate in candidates:
        _validate_candidate(candidate)
    projection = {
        key: data[key]
        for key in (
            "snapshot_id",
            "observation_id",
            "turn_id",
            "observation_epoch",
            "bundle_id",
            "window_id",
            "candidate_count",
            "total_match_count",
            "candidate_bytes",
            "truncated",
            "candidates",
        )
        if key in data
    }
    encoded = _canonical_json(projection)
    if len(encoded) > MAX_MODEL_OBSERVATION_BYTES:
        raise ObservationValidationError("payload_too_large")
    snapshot_id = _required_id(data.get("snapshot_id"), "snapshot_id")
    observation_id = _required_id(data.get("observation_id"), "observation_id")
    bundle_id = data.get("bundle_id")
    if not isinstance(bundle_id, str) or not 0 < len(bundle_id) <= 255:
        raise ObservationValidationError("invalid_bundle_id")
    window_id = data.get("window_id")
    if not isinstance(window_id, int) or isinstance(window_id, bool) or not 0 < window_id <= 0xFFFFFFFF:
        raise ObservationValidationError("invalid_window_id")
    candidate_bytes = data.get("candidate_bytes")
    expected_candidate_bytes = len(_canonical_json(candidates))
    if candidate_bytes != expected_candidate_bytes:
        raise ObservationValidationError("candidate_bytes_mismatch")
    text = encoded.decode()
    return ModelObservation(
        observation_id=observation_id,
        snapshot_id=snapshot_id,
        bundle_id=bundle_id,
        window_id=window_id,
        text=text,
        byte_count=candidate_bytes,
        estimated_input_tokens=(len(encoded) + 3) // 4,
    )


def _validate_candidate(candidate: object) -> None:
    if not isinstance(candidate, dict):
        raise ObservationValidationError("candidate_not_object")
    for key, limit in (("ref", 128), ("label", 160), ("role", 64)):
        value = candidate.get(key)
        if not isinstance(value, str) or not 0 < len(value) <= limit:
            raise ObservationValidationError(f"invalid_candidate_{key}")
    actions = candidate.get("supported_actions")
    if not isinstance(actions, list) or len(actions) > 16 or any(
        not isinstance(item, str) or not _SYMBOL.fullmatch(item) for item in actions
    ):
        raise ObservationValidationError("invalid_candidate_actions")
    trail = candidate.get("ancestor_trail")
    if not isinstance(trail, list) or len(trail) > 4 or any(
        not isinstance(item, str) or len(item) > 80 for item in trail
    ):
        raise ObservationValidationError("invalid_ancestor_trail")
    score = candidate.get("score")
    if not isinstance(score, int) or isinstance(score, bool):
        raise ObservationValidationError("invalid_candidate_score")
    reasons = candidate.get("score_reasons")
    if not isinstance(reasons, list) or len(reasons) > 16 or any(
        not isinstance(item, str) or len(item) > 64 for item in reasons
    ):
        raise ObservationValidationError("invalid_score_reasons")
    if not isinstance(candidate.get("descriptor"), dict):
        raise ObservationValidationError("invalid_candidate_descriptor")


def _bounded_strings(values: object, *, count: int, length: int) -> tuple[str, ...]:
    if not isinstance(values, list):
        return ()
    result: list[str] = []
    seen: set[str] = set()
    for raw in values:
        if not isinstance(raw, str):
            continue
        value = raw.strip()[:length]
        key = value.casefold()
        if not value or key in seen:
            continue
        seen.add(key)
        result.append(value)
        if len(result) == count:
            break
    return tuple(result)


def _bounded_symbols(values: object) -> tuple[str, ...]:
    return tuple(value for value in _bounded_strings(values, count=16, length=64) if _SYMBOL.fullmatch(value))


def _bounded_text(value: object, limit: int) -> str | None:
    if not isinstance(value, str):
        return None
    value = value.strip()
    return value[:limit] or None


def _required_id(value: object, field: str) -> str:
    if not isinstance(value, str) or not 0 < len(value) <= 128 or not all(
        character.isascii() and (character.isalnum() or character in "-_")
        for character in value
    ):
        raise ObservationValidationError(f"invalid_{field}")
    return value


def _canonical_json(value: object) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, separators=(",", ":"), sort_keys=True
    ).encode()
