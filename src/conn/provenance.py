from __future__ import annotations

from dataclasses import dataclass, replace

from .events import mono_ms, new_id


@dataclass(frozen=True, slots=True)
class TurnContext:
    turn_id: str
    response_epoch: int
    observation_epoch: int
    frontmost_bundle: str | None
    window_id: int | None
    started_monotonic_ms: int

    @classmethod
    def start(cls, observation_epoch: int) -> TurnContext:
        return cls(
            turn_id=new_id("turn"),
            response_epoch=0,
            observation_epoch=observation_epoch,
            frontmost_bundle=None,
            window_id=None,
            started_monotonic_ms=mono_ms(),
        )

    def next_response(self) -> TurnContext:
        return replace(self, response_epoch=self.response_epoch + 1)

    def invalidate_observation(self) -> TurnContext:
        return replace(self, observation_epoch=self.observation_epoch + 1)

    def with_observation(
        self, *, frontmost_bundle: str | None, window_id: int | None
    ) -> TurnContext:
        return replace(
            self,
            frontmost_bundle=frontmost_bundle,
            window_id=window_id,
        )
