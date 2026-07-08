"""Context reads via the app's Accessibility grant (S2).

TCC grants bind to the binary. Conn.app holds the Accessibility grant; the
daemon it spawns is .venv/bin/python, a different TCC identity, so
AXIsProcessTrusted() answers false in the daemon and window titles and
selected text die in live use (bug 2 of the 2026-07-07 drive). The app,
which already holds a websocket to the daemon, performs the read instead:
the daemon publishes ax_read, the app answers ax_read_result, and this
bridge carries the round trip. Executors call the sync entry from harness
threads; when no app client is attached the answer is an immediate None so
the python fallback never pays a timeout.
"""

from __future__ import annotations

import asyncio
from typing import Callable

from .events import new_id


class AxBridge:
    def __init__(self, timeout_s: float = 2.0):
        self.timeout_s = timeout_s
        self._loop: asyncio.AbstractEventLoop | None = None
        self._publish: Callable[[dict], None] | None = None
        self._pending: dict[str, asyncio.Future] = {}
        self._app_clients = 0

    def bind(self, loop: asyncio.AbstractEventLoop, publish: Callable[[dict], None]) -> None:
        self._loop = loop
        self._publish = publish

    def app_attached(self) -> None:
        self._app_clients += 1

    def app_detached(self) -> None:
        self._app_clients = max(0, self._app_clients - 1)

    @property
    def app_present(self) -> bool:
        return self._app_clients > 0

    def request_context_sync(self) -> dict | None:
        """Thread-safe context read through the app. None means no app,
        timeout, or malformed answer: the caller falls back to python AX."""
        loop = self._loop
        if loop is None or self._publish is None or not self.app_present:
            return None
        future = asyncio.run_coroutine_threadsafe(self._request(), loop)
        try:
            return future.result(self.timeout_s + 0.5)
        except Exception:
            future.cancel()
            return None

    async def _request(self) -> dict | None:
        assert self._loop is not None and self._publish is not None
        request_id = new_id("axread")
        future: asyncio.Future = self._loop.create_future()
        self._pending[request_id] = future
        try:
            self._publish({"type": "ax_read", "request_id": request_id})
            return await asyncio.wait_for(future, self.timeout_s)
        except asyncio.TimeoutError:
            return None
        finally:
            self._pending.pop(request_id, None)

    def resolve(self, request_id: str, data: object) -> None:
        """Called on the loop when the app answers. Unknown ids (a late answer
        after timeout) are dropped."""
        future = self._pending.get(request_id)
        if future is not None and not future.done():
            future.set_result(data if isinstance(data, dict) else None)
