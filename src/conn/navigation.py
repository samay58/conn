from __future__ import annotations

from enum import StrEnum


NAVIGATION_GRANT_GUIDANCE = (
    "Open the Conn menu and click Navigation control: Off."
)


class NavigationEffect(StrEnum):
    REVERSIBLE_NAVIGATION = "reversible_navigation"
    CONSEQUENTIAL = "consequential"
    DESTRUCTIVE = "destructive"
    SECURE_OR_DENIED = "secure_or_denied"
    UNKNOWN = "unknown"


class NavigationLease:
    def __init__(self, session_id: str):
        self._session_id = session_id
        self._connection_id: str | None = None
        self._granted = False
        self._suspended = False
        self._generation = 0

    @property
    def generation(self) -> int:
        return self._generation

    def public_snapshot(self) -> dict:
        return {
            "granted": self._granted,
            "active": self._granted and not self._suspended,
            "suspended": self._suspended,
            "generation": self._generation,
            "guidance": NAVIGATION_GRANT_GUIDANCE,
        }

    def begin_session(self, session_id: str) -> None:
        self._session_id = session_id
        self._invalidate(granted=False, suspended=False)

    def end_session(self) -> None:
        self._invalidate(granted=False, suspended=False)

    def bind_connection(self, connection_id: str) -> None:
        if connection_id == self._connection_id:
            return
        self._connection_id = connection_id
        self._invalidate(granted=False, suspended=False)

    def disconnect(self, connection_id: str) -> bool:
        if connection_id != self._connection_id:
            return False
        self._connection_id = None
        self._invalidate(granted=False, suspended=False)
        return True

    def grant(self, session_id: str, connection_id: str) -> bool:
        if not self._matches(session_id, connection_id) or self._suspended:
            return False
        if not self._granted:
            self._invalidate(granted=True, suspended=False)
        return True

    def revoke(self, session_id: str, connection_id: str) -> bool:
        if not self._matches(session_id, connection_id):
            return False
        if not self._granted and not self._suspended:
            return True
        self._invalidate(granted=False, suspended=False)
        return True

    def suspend(self, session_id: str, connection_id: str) -> bool:
        if not self._matches(session_id, connection_id):
            return False
        if self._suspended:
            return True
        self._invalidate(granted=self._granted, suspended=True)
        return True

    def resume(
        self,
        session_id: str,
        connection_id: str,
        *,
        expected_generation: int | None = None,
    ) -> bool:
        if not self._matches(session_id, connection_id):
            return False
        if expected_generation is not None and expected_generation != self._generation:
            return False
        if not self._suspended:
            return True
        self._invalidate(granted=self._granted, suspended=False)
        return True

    def allows(self, effect: NavigationEffect | str, generation: int) -> bool:
        try:
            effect = NavigationEffect(effect)
        except ValueError:
            return False
        return (
            self._granted
            and not self._suspended
            and generation == self._generation
            and effect is NavigationEffect.REVERSIBLE_NAVIGATION
        )

    def _matches(self, session_id: str, connection_id: str) -> bool:
        return (
            session_id == self._session_id
            and connection_id == self._connection_id
            and self._connection_id is not None
        )

    def binding(self) -> dict:
        return {
            "session_id": self._session_id,
            "connection_id": self._connection_id,
            "generation": self._generation,
        }

    def _invalidate(self, *, granted: bool, suspended: bool) -> None:
        self._generation += 1
        self._granted = granted
        self._suspended = suspended
