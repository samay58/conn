"""Upstream close honesty: a clean end of the OpenAI socket iterator must
surface as a real disconnect event, and `connected` must never lie about a
dead socket. Covers the Jul 3 wedge: upstream sends an error event, then
closes the socket cleanly, and the old code died silently instead of
reaching the disconnect path.
"""

from __future__ import annotations

import asyncio
import json

import websockets

from conn.config import Config
from conn.realtime.base import RtClosed, RtError, RtSessionReady
from conn.realtime.openai_ws import OpenAIRealtimeAdapter


class FakeWS:
    """Minimal async-iterable stand-in for a websockets client connection.

    Yields `messages` in order, then either raises `raise_exc`, or runs
    `on_exhausted` (to simulate a concurrent `close()` landing mid-iteration),
    or just ends the iteration cleanly (StopAsyncIteration) if neither is set.
    """

    def __init__(self, messages=None, raise_exc=None, on_exhausted=None):
        self._messages = list(messages or [])
        self._raise_exc = raise_exc
        self._on_exhausted = on_exhausted

    def __aiter__(self):
        return self

    async def __anext__(self):
        if self._messages:
            return self._messages.pop(0)
        if self._raise_exc is not None:
            raise self._raise_exc
        if self._on_exhausted is not None:
            await self._on_exhausted()
        raise StopAsyncIteration

    async def close(self) -> None:
        pass


def make_adapter(ws) -> OpenAIRealtimeAdapter:
    adapter = OpenAIRealtimeAdapter(Config(), tools=[], instructions="")
    adapter._ws = ws
    return adapter


async def _collect(adapter):
    return [ev async for ev in adapter.events()]


def test_clean_iterator_end_yields_rtclosed():
    adapter = make_adapter(FakeWS())
    events = asyncio.run(_collect(adapter))
    assert events == [RtClosed(reason="connection closed: clean")]


def test_connected_false_after_clean_end():
    adapter = make_adapter(FakeWS())
    asyncio.run(_collect(adapter))
    assert adapter.connected is False


def test_connected_false_after_exception_end():
    adapter = make_adapter(FakeWS(raise_exc=RuntimeError("boom")))
    events = asyncio.run(_collect(adapter))
    assert events == [RtError(message="boom", fatal=True)]
    assert adapter.connected is False


def test_connected_false_after_connection_closed_exception():
    adapter = make_adapter(FakeWS(raise_exc=websockets.ConnectionClosed(None, None)))
    asyncio.run(_collect(adapter))
    assert adapter.connected is False


def test_connected_false_after_close():
    adapter = make_adapter(FakeWS())

    async def run():
        await adapter.close()

    asyncio.run(run())
    assert adapter.connected is False


def test_no_rtclosed_when_close_initiated_the_end():
    # Simulates the real race: events() is already iterating the live socket
    # when close() lands (e.g. from the PTT-release path in app.py), and the
    # socket then ends its iteration as a direct result of that close() call.
    adapter = make_adapter(None)
    adapter._ws = FakeWS(on_exhausted=adapter.close)

    events = asyncio.run(_collect(adapter))

    assert events == []
    assert adapter.connected is False


def _session_msg(session_id: str) -> str:
    return json.dumps({"type": "session.created", "session": {"id": session_id}})


def test_connected_false_after_generator_abandoned_mid_iteration():
    # A caller (e.g. the app's read loop) can stop consuming events() before
    # the socket itself ends, e.g. via `async for` breaking early or the
    # asyncio task being cancelled. Either path throws GeneratorExit at the
    # generator's current yield point. connected must go False here just
    # like on any other exit.
    adapter = make_adapter(FakeWS(messages=[_session_msg("s1"), _session_msg("s2")]))

    async def run():
        gen = adapter.events()
        first = await gen.__anext__()
        assert first == RtSessionReady(session_id="s1")
        await gen.aclose()

    asyncio.run(run())
    assert adapter.connected is False


def test_reconnect_during_abandoned_generator_is_not_clobbered():
    # If a reconnect lands (new socket assigned to self._ws) while the OLD
    # generator is still mid-iteration and then gets abandoned, the old
    # generator's cleanup must not null out the NEW socket. The identity
    # guard (capture ws at entry, only clear self._ws if it still is that
    # same object) is what makes this safe.
    old_ws = FakeWS(messages=[_session_msg("s1"), _session_msg("s2")])
    adapter = make_adapter(old_ws)
    new_ws = FakeWS()

    async def run():
        gen = adapter.events()
        first = await gen.__anext__()
        assert first == RtSessionReady(session_id="s1")
        adapter._ws = new_ws  # simulate a reconnect landing mid-flight
        await gen.aclose()

    asyncio.run(run())
    assert adapter.connected is True
    assert adapter._ws is new_ws
