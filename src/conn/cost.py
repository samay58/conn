"""Session cost accounting. One spend trigger exists (response.create) and the
daemon owns it, so the budget gate is a pure function of this meter.

Usage shape, per the Realtime API's response.done event:
  usage.input_tokens / output_tokens
  usage.input_token_details: {text_tokens, audio_tokens, cached_tokens,
                              cached_tokens_details: {text_tokens, audio_tokens}}
  usage.output_token_details: {text_tokens, audio_tokens}
Cached input bills at the cached rate; the cached split reduces the billable
text/audio input counts.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path

from .config import BudgetCfg, PricingCfg
from .trace import write_receipt
from .events import ModelObservation, VisualObservation

DEFAULT_FIRST_TURN_ESTIMATE_USD = 0.03


@dataclass
class TurnCost:
    text_in: int = 0
    text_out: int = 0
    audio_in: int = 0
    audio_out: int = 0
    cached_in: int = 0
    image_in: int = 0
    usd: float = 0.0


@dataclass
class CostMeter:
    pricing: PricingCfg
    budget: BudgetCfg
    started_at: float = field(default_factory=time.time)
    turns: list[TurnCost] = field(default_factory=list)
    tool_calls: int = 0
    tool_proposals: int = 0
    blocked_proposals: int = 0
    user_turns: int = 0
    screenshots: int = 0
    action_outcomes: dict[str, int] = field(default_factory=dict)
    overridden: bool = False
    observation_count: int = 0
    observation_bytes: int = 0
    observation_estimated_tokens: int = 0
    visual_observation_count: int = 0
    visual_observation_bytes: int = 0

    def count_action_outcome(self, outcome: str) -> None:
        self.action_outcomes[outcome] = self.action_outcomes.get(outcome, 0) + 1

    def record_observation(self, observation: ModelObservation) -> None:
        self.observation_count += 1
        self.observation_bytes += observation.byte_count
        self.observation_estimated_tokens += observation.estimated_input_tokens

    def record_visual_observation(self, observation: VisualObservation) -> None:
        self.visual_observation_count += 1
        self.visual_observation_bytes += observation.image_bytes

    def ingest(self, usage: dict) -> TurnCost:
        in_details = usage.get("input_token_details", {})
        out_details = usage.get("output_token_details", {})
        cached = in_details.get("cached_tokens", 0)
        cached_split = in_details.get("cached_tokens_details", {})
        cached_text = cached_split.get("text_tokens", cached)
        cached_audio = cached_split.get("audio_tokens", 0)
        cached_image = cached_split.get("image_tokens", 0)

        text_in = max(in_details.get("text_tokens", 0) - cached_text, 0)
        audio_in = max(in_details.get("audio_tokens", 0) - cached_audio, 0)
        image_in = max(in_details.get("image_tokens", 0) - cached_image, 0)
        turn = TurnCost(
            text_in=text_in,
            audio_in=audio_in,
            cached_in=cached,
            image_in=image_in,
            text_out=out_details.get("text_tokens", 0),
            audio_out=out_details.get("audio_tokens", 0),
        )
        p = self.pricing
        turn.usd = (
            turn.text_in * p.text_in
            + turn.text_out * p.text_out
            + turn.audio_in * p.audio_in
            + turn.audio_out * p.audio_out
            + turn.cached_in * p.cached_in
            + turn.image_in * p.image_in
        ) / 1_000_000
        self.turns.append(turn)
        return turn

    @property
    def spent_usd(self) -> float:
        return sum(t.usd for t in self.turns)

    def estimate_next_turn_usd(self) -> float:
        if not self.turns:
            return DEFAULT_FIRST_TURN_ESTIMATE_USD
        costs = sorted(t.usd for t in self.turns)
        return costs[len(costs) // 2]  # median of past turns

    def would_exceed(self) -> bool:
        if self.overridden:
            return False
        return self.spent_usd + self.estimate_next_turn_usd() >= self.budget.session_cap_usd

    def should_warn(self) -> bool:
        return self.spent_usd >= self.budget.warn_at_usd

    def receipt(self) -> dict:
        total = TurnCost()
        for t in self.turns:
            total.text_in += t.text_in
            total.text_out += t.text_out
            total.audio_in += t.audio_in
            total.audio_out += t.audio_out
            total.cached_in += t.cached_in
            total.image_in += t.image_in
        return {
            "duration_s": round(time.time() - self.started_at, 1),
            "user_turns": self.user_turns,
            "model_responses": len(self.turns),
            "tokens": {
                "text_in": total.text_in, "text_out": total.text_out,
                "audio_in": total.audio_in, "audio_out": total.audio_out,
                "cached_in": total.cached_in,
                "image_in": total.image_in,
            },
            "tool_calls": self.tool_calls,
            "tool_proposals": self.tool_proposals,
            "blocked_proposals": self.blocked_proposals,
            "action_outcomes": dict(self.action_outcomes),
            "screenshots": self.screenshots,
            "observations": {
                "count": self.observation_count,
                "candidate_bytes": self.observation_bytes,
                "estimated_input_tokens": self.observation_estimated_tokens,
            },
            "visual_observations": {
                "count": self.visual_observation_count,
                "image_bytes": self.visual_observation_bytes,
            },
            "estimated_usd": round(self.spent_usd, 4),
            "cap_usd": self.budget.session_cap_usd,
            "per_response_usd": [round(t.usd, 4) for t in self.turns],
        }

    def write_receipt_snapshot(self, data_dir: Path, session_id: str, final: bool = False,
                               trace_path: Path | None = None) -> Path:
        """Writes the current receipt to disk immediately, so a receipt file
        exists from the first turn even if the session never ends cleanly
        (Defect 8: a Jul 3 session spent $0.065 and left no receipt at all).
        Called at every response.done; `final` flips True only at session end.
        When `trace_path` is given, attaches the current latency spans so the
        receipt always carries the freshest reading from the trace so far."""
        r = self.receipt()
        r["final"] = final
        if trace_path is not None:
            from .latency import distributions, spans
            r["latency"] = spans(trace_path)
            r["latency_distributions"] = distributions(trace_path)
        return write_receipt(data_dir, session_id, r)
