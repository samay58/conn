"""Sanitized last-command report: the one-keypress failure artifact.

The report is built entirely from trace events, which already exclude raw
secure values, clipboard bodies, bridge tokens, audio, and image bytes. The
classifier assigns each turn a pipeline stage from the reliability spec's
failure taxonomy so recurring failures cluster without hand triage.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

from .trace import runtime_identity

PIPELINE_STAGES = (
    "voice_capture",
    "transcription",
    "turn_or_context_transport",
    "intent_selection",
    "capability_discovery",
    "target_resolution",
    "plan_compilation",
    "risk_or_approval",
    "dispatch",
    "verification",
    "recovery",
    "bridge_or_lifecycle",
    "ui_state",
    "latency",
)

_PLAN_REASONS = (
    "invalid_effect_target", "native_plan_invalid", "invalid_arguments",
    "unsupported_operation", "action_request_invalid", "stale_plan",
    "stale_snapshot", "effect_already_satisfied",
)
_POLICY_REASONS = (
    "hotkey_not_allowlisted", "app_not_allowlisted", "denied_by_user",
    "blocked_by_policy", "blocked_by_config_override", "secure_field",
    "denied_bundle", "app_signer_not_configured", "app_bundle_id_missing",
    "approval_timeout", "mutation_chain_closed", "sequential_action_required",
)


def last_turn_events(events: list[dict]) -> list[dict]:
    """Events from the most recent turn_context onward; the whole tail when
    the session never opened a turn."""
    for index in range(len(events) - 1, -1, -1):
        if events[index].get("kind") == "turn_context":
            return events[index:]
    return events


def _result_outcome(event: dict) -> str | None:
    try:
        payload = json.loads(event.get("output") or "")
    except (TypeError, ValueError):
        return None
    if isinstance(payload, dict):
        outcome = payload.get("outcome")
        return outcome if isinstance(outcome, str) else None
    return None


def classify_failure(events: list[dict]) -> str | None:
    """One pipeline stage per turn, None when the turn shows no failure.
    Ordered: the earliest broken stage wins, because later stages never ran
    honestly if an earlier one failed."""
    kinds = [e.get("kind") for e in events]
    if "upstream_error" in kinds:
        return "turn_or_context_transport"
    if any(k in kinds for k in ("turn_context_unavailable",)):
        return "bridge_or_lifecycle"
    had_ptt = "ptt_down" in kinds
    had_input = any(e.get("kind") == "input" for e in events)
    if had_ptt and not had_input:
        if "low_signal" in kinds or "audio_silent" in kinds:
            return "voice_capture"
        return "transcription"
    for event in events:
        if event.get("kind") == "approval_decision" and event.get("approved") is False:
            return "risk_or_approval"
        reason = event.get("block_reason")
        if isinstance(reason, str):
            if any(reason.startswith(r) for r in _PLAN_REASONS):
                return "plan_compilation"
            if any(reason.startswith(r) for r in _POLICY_REASONS):
                return "risk_or_approval"
        if event.get("kind") == "tool_result":
            outcome = _result_outcome(event)
            if outcome == "ambiguous":
                return "target_resolution"
            if outcome == "no_effect":
                return "verification"
            if outcome == "dispatch_only":
                return "dispatch"
            if outcome in {"blocked", "failed"}:
                return "risk_or_approval" if outcome == "blocked" else "dispatch"
    return None


def write_last_command_report(
    data_dir: Path,
    session_id: str,
    events: list[dict],
    *,
    config_path: Path | None = None,
    receipt: dict | None = None,
) -> Path:
    turn = last_turn_events(events)
    day = time.strftime("%Y-%m-%d")
    out_dir = data_dir / "reports" / day
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{session_id}-{time.time_ns()}.json"
    identity = runtime_identity(config_path)
    payload = {
        "session_id": session_id,
        "failure_category": classify_failure(turn),
        "events": turn,
        "receipt": receipt,
        **identity,
    }
    path.write_text(json.dumps(payload, indent=2, default=str))
    return path
