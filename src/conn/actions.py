from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from .navigation import NAVIGATION_GRANT_GUIDANCE


class ActionOutcome(StrEnum):
    VERIFIED = "verified"
    DISPATCH_ONLY = "dispatch_only"
    NO_EFFECT = "no_effect"
    BLOCKED = "blocked"
    AMBIGUOUS = "ambiguous"
    FAILED = "failed"


class DispatchState(StrEnum):
    NOT_DISPATCHED = "not_dispatched"
    POSSIBLY_DISPATCHED = "possibly_dispatched"
    DISPATCHED = "dispatched"


class ReasonCode(StrEnum):
    NO_TRUSTWORTHY_WITNESS = "no_trustworthy_witness"
    WITNESS_NOT_MATCHED = "witness_not_matched"
    AMBIGUOUS_AFTER_FULL_LOCATOR = "ambiguous_after_full_locator"
    INVALID_ACTION_RECEIPT = "invalid_action_receipt"


def _wire_bool(value: object, field: str) -> bool:
    if type(value) is not bool:
        raise ValueError(f"{field} must be a boolean")
    return value


def _candidate_description(value: object) -> str | None:
    if isinstance(value, str):
        return value[:160]
    if not isinstance(value, dict):
        return None
    descriptor = value.get("descriptor")
    if isinstance(descriptor, dict):
        display = descriptor.get("display")
        if isinstance(display, str) and display.strip():
            return display.strip()[:160]
    for key in ("display", "label", "title"):
        text = value.get(key)
        if isinstance(text, str) and text.strip():
            return text.strip()[:160]
    return None


@dataclass(frozen=True, slots=True)
class ActionEvidence:
    kind: str
    summary: str
    matched: bool

    def as_dict(self) -> dict:
        return {"kind": self.kind, "summary": self.summary, "matched": self.matched}


@dataclass(frozen=True, slots=True)
class ActionReceipt:
    outcome: ActionOutcome
    dispatch_state: DispatchState
    strategy: str
    lane: str
    target: str
    effect: str
    evidence: tuple[ActionEvidence, ...]
    retry_safe: bool
    duration_ms: int
    reason_code: str | None = None
    data: dict | None = None

    def __post_init__(self) -> None:
        if self.outcome is ActionOutcome.VERIFIED:
            if self.dispatch_state is not DispatchState.DISPATCHED:
                raise ValueError("verified action must be dispatched")
            if not self.evidence or not all(item.matched for item in self.evidence):
                raise ValueError("verified action requires matched effect evidence")
        if (
            self.outcome in {ActionOutcome.DISPATCH_ONLY, ActionOutcome.NO_EFFECT}
            and self.dispatch_state is not DispatchState.DISPATCHED
        ):
            raise ValueError(f"{self.outcome.value} has impossible dispatch state")
        if (
            self.outcome in {ActionOutcome.BLOCKED, ActionOutcome.AMBIGUOUS}
            and self.dispatch_state is not DispatchState.NOT_DISPATCHED
        ):
            raise ValueError(f"{self.outcome.value} has impossible dispatch state")
        if self.retry_safe and self.dispatch_state is not DispatchState.NOT_DISPATCHED:
            raise ValueError("retry safe action must be proven not dispatched")
        if self.outcome is not ActionOutcome.VERIFIED:
            if not isinstance(self.reason_code, str) or not self.reason_code.strip():
                raise ValueError("non-verified action requires a reason code")

    @property
    def ok(self) -> bool:
        return self.outcome is ActionOutcome.VERIFIED

    def safe_user_message(self) -> str:
        """What Conn may say about this outcome: the safe reason and next
        move, with no internal terminology."""
        if self.reason_code == "navigation_grant_required":
            return NAVIGATION_GRANT_GUIDANCE
        match self.outcome:
            case ActionOutcome.VERIFIED:
                return "Done."
            case ActionOutcome.DISPATCH_ONLY:
                return "I sent it, but could not confirm it worked."
            case ActionOutcome.NO_EFFECT:
                return "I sent it, but it did not take effect."
            case ActionOutcome.AMBIGUOUS:
                candidates = [
                    _candidate_description(item)
                    for item in (self.data or {}).get("candidates", [])[:3]
                ]
                candidates = [item for item in candidates if item]
                if candidates:
                    return (f"I found more than one match: "
                            f"{', '.join(candidates)}. Which one?")
                return "I found more than one match. Which one?"
            case ActionOutcome.BLOCKED:
                return "That action is outside what Conn is allowed to do."
        if self.dispatch_state is DispatchState.POSSIBLY_DISPATCHED:
            return "The action may have been sent. Check before retrying."
        reason = self.reason_code or ""
        if reason.startswith("stale"):
            return "The app changed before I could act. Try again."
        if reason in {"native_app_unavailable", "native_app_disconnected",
                      "native_bridge_timeout"}:
            return "Conn lost its app connection before sending anything."
        if reason == "no_live_affordance":
            return "This app does not offer a way to do that."
        if reason == "no_current_selection":
            return "Nothing is selected to move from."
        if reason == "no_relative_item":
            return "There is no item in that direction."
        return "It did not run."

    def as_dict(self) -> dict:
        payload = {
            "outcome": self.outcome.value,
            "ok": self.ok,
            "dispatch_state": self.dispatch_state.value,
            "strategy": self.strategy,
            "lane": self.lane,
            "target": self.target,
            "effect": self.effect,
            "evidence": [item.as_dict() for item in self.evidence],
            "retry_safe": self.retry_safe,
            "duration_ms": self.duration_ms,
            "reason_code": self.reason_code,
            "safe_user_message": self.safe_user_message(),
        }
        if self.data is not None:
            payload["data"] = self.data
            if isinstance(self.data.get("error"), str):
                payload["error"] = self.data["error"]
        return payload

    @classmethod
    def from_dict(cls, data: dict) -> ActionReceipt:
        outcome = ActionOutcome(data["outcome"])
        reason_code = data.get("reason_code")
        if outcome is not ActionOutcome.VERIFIED and not reason_code:
            error = (data.get("data") or {}).get("error")
            if isinstance(error, str) and error:
                reason_code = _reason_from_summary(error)
            else:
                reason_code = {
                    ActionOutcome.DISPATCH_ONLY: ReasonCode.NO_TRUSTWORTHY_WITNESS,
                    ActionOutcome.NO_EFFECT: ReasonCode.WITNESS_NOT_MATCHED,
                    ActionOutcome.AMBIGUOUS: ReasonCode.AMBIGUOUS_AFTER_FULL_LOCATOR,
                    ActionOutcome.BLOCKED: "legacy_blocked",
                    ActionOutcome.FAILED: ReasonCode.INVALID_ACTION_RECEIPT,
                }[outcome]
        return cls(
            outcome=outcome,
            dispatch_state=DispatchState(data["dispatch_state"]),
            strategy=str(data.get("strategy", "unknown")),
            lane=str(data.get("lane", "semantic")),
            target=str(data.get("target", "current target")),
            effect=str(data.get("effect", "unverified effect")),
            evidence=tuple(
                ActionEvidence(
                    kind=str(item.get("kind") or item.get("predicate") or "unknown"),
                    summary=str(item.get("summary") or item.get("detail") or ""),
                    matched=_wire_bool(item.get("matched"), "evidence.matched"),
                )
                for item in data.get("evidence", [])
                if isinstance(item, dict)
            ),
            retry_safe=_wire_bool(data.get("retry_safe"), "retry_safe"),
            duration_ms=int(data.get("duration_ms", 0)),
            reason_code=str(reason_code) if reason_code is not None else None,
            data=data.get("data") if isinstance(data.get("data"), dict) else None,
        )


def _reason_from_summary(summary: str) -> str:
    token = summary.split(":", 1)[0].strip().lower().replace(" ", "_")
    return token or ReasonCode.INVALID_ACTION_RECEIPT


def dispatch_only_receipt(*, target: str, strategy: str, duration_ms: int) -> ActionReceipt:
    return ActionReceipt(
        outcome=ActionOutcome.DISPATCH_ONLY,
        dispatch_state=DispatchState.DISPATCHED,
        strategy=strategy,
        lane="semantic",
        target=target,
        effect="effect not observed",
        evidence=(ActionEvidence(
            kind="dispatch_return",
            summary="executor accepted request without effect evidence",
            matched=False,
        ),),
        retry_safe=False,
        duration_ms=duration_ms,
        reason_code=ReasonCode.NO_TRUSTWORTHY_WITNESS,
    )


def uncertain_failure_receipt(
    *, target: str, strategy: str, duration_ms: int, summary: str
) -> ActionReceipt:
    return ActionReceipt(
        outcome=ActionOutcome.FAILED,
        dispatch_state=DispatchState.POSSIBLY_DISPATCHED,
        strategy=strategy,
        lane="semantic",
        target=target,
        effect="dispatch may have occurred",
        evidence=(ActionEvidence(
            kind="executor_failure",
            summary=summary,
            matched=False,
        ),),
        retry_safe=False,
        duration_ms=duration_ms,
        reason_code=_reason_from_summary(summary),
        data={"error": summary},
    )


def not_dispatched_failure_receipt(
    *, target: str, strategy: str, duration_ms: int, summary: str
) -> ActionReceipt:
    return ActionReceipt(
        outcome=ActionOutcome.FAILED,
        dispatch_state=DispatchState.NOT_DISPATCHED,
        strategy=strategy,
        lane="semantic",
        target=target,
        effect="action was not dispatched",
        evidence=(ActionEvidence(
            kind="native_bridge",
            summary=summary,
            matched=False,
        ),),
        retry_safe=True,
        duration_ms=duration_ms,
        reason_code=_reason_from_summary(summary),
        data={"error": summary},
    )


def blocked_receipt(*, target: str, summary: str, duration_ms: int) -> ActionReceipt:
    return ActionReceipt(
        outcome=ActionOutcome.BLOCKED,
        dispatch_state=DispatchState.NOT_DISPATCHED,
        strategy="policy_gate",
        lane="semantic",
        target=target,
        effect="action was not dispatched",
        evidence=(ActionEvidence(
            kind="policy_gate",
            summary=summary,
            matched=False,
        ),),
        retry_safe=False,
        duration_ms=duration_ms,
        reason_code=_reason_from_summary(summary),
        data={"error": summary},
    )


def ambiguous_receipt(*, target: str, data: dict, duration_ms: int) -> ActionReceipt:
    return ActionReceipt(
        outcome=ActionOutcome.AMBIGUOUS,
        dispatch_state=DispatchState.NOT_DISPATCHED,
        strategy="semantic_resolution",
        lane="semantic",
        target=target,
        effect="target must resolve uniquely",
        evidence=(ActionEvidence(
            kind="candidate_set",
            summary=f"{len(data.get('candidates', []))} candidates",
            matched=False,
        ),),
        retry_safe=True,
        duration_ms=duration_ms,
        reason_code=ReasonCode.AMBIGUOUS_AFTER_FULL_LOCATOR,
        data=data,
    )


def preparation_failure_receipt(
    *, outcome: str, target: str, summary: str, data: dict | None = None
) -> ActionReceipt:
    parsed_outcome = ActionOutcome(outcome)
    if parsed_outcome not in {
        ActionOutcome.AMBIGUOUS,
        ActionOutcome.BLOCKED,
        ActionOutcome.FAILED,
    }:
        parsed_outcome = ActionOutcome.FAILED
    details = dict(data or {})
    details["error"] = summary
    return ActionReceipt(
        outcome=parsed_outcome,
        dispatch_state=DispatchState.NOT_DISPATCHED,
        strategy="native_plan",
        lane="semantic",
        target=target,
        effect="action was not dispatched",
        evidence=(ActionEvidence(
            kind="native_plan",
            summary=summary,
            matched=False,
        ),),
        retry_safe=True,
        duration_ms=0,
        reason_code=_reason_from_summary(summary),
        data=details,
    )


def simulated_verified_receipt(*, target: str, effect: str, data: dict) -> dict:
    return ActionReceipt(
        outcome=ActionOutcome.VERIFIED,
        dispatch_state=DispatchState.DISPATCHED,
        strategy="simulated_fixture",
        lane="semantic",
        target=target,
        effect=effect,
        evidence=(ActionEvidence(kind="fixture_state", summary=effect, matched=True),),
        retry_safe=False,
        duration_ms=0,
        data=data,
    ).as_dict()
