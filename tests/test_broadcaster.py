"""Shutdown hygiene for the console broadcaster (bug 5 of the 2026-07-07
drive): every detach must cancel the client's writer task, or the loop
tears down over tasks still pending on queue.get() and asyncio logs
"Task was destroyed but it is pending" per client."""

import asyncio
import json

from conn.server.http import Broadcaster, CLIENT_QUEUE_LIMIT


class FakeWS:
    def __init__(self):
        self.sent = []

    async def send_text(self, data: str) -> None:
        self.sent.append(data)

    async def close(self, code: int) -> None:
        self.close_code = code


def test_detach_cancels_the_writer_task():
    async def scenario():
        bus = Broadcaster()
        ws = FakeWS()
        bus.attach(ws, "console")
        task = bus._clients[ws][1]
        bus.detach(ws)
        await asyncio.sleep(0)  # let the cancellation land
        return task

    task = asyncio.run(scenario())
    assert task.cancelled() or task.done()


def test_publish_reaches_attached_clients_only():
    async def scenario():
        bus = Broadcaster()
        stays, leaves = FakeWS(), FakeWS()
        bus.attach(stays, "console")
        bus.attach(leaves, "console")
        bus.detach(leaves)
        bus.publish({"type": "state"})
        await asyncio.sleep(0.01)  # writer drains the queue
        for _ws, (_queue, task, _role) in list(bus._clients.items()):
            task.cancel()
        return stays.sent, leaves.sent

    stayed, left = asyncio.run(scenario())
    assert len(stayed) == 1
    assert left == []


def test_loop_closes_clean_with_attached_client():
    # The regression itself: end the loop while a client is still attached
    # after a detach; no writer may still be pending on queue.get().
    async def scenario():
        bus = Broadcaster()
        ws = FakeWS()
        bus.attach(ws, "console")
        bus.detach(ws)
        await asyncio.sleep(0)
        return [task for task in asyncio.all_tasks()
                if task is not asyncio.current_task() and not task.done()]

    pending = asyncio.run(scenario())
    assert pending == []


def test_native_rpc_reaches_authenticated_app_role_only():
    async def scenario():
        bus = Broadcaster()
        app, console = FakeWS(), FakeWS()
        bus.attach(app, "app")
        bus.attach(console, "console")
        bus.publish({
            "type": "ax_action",
            "request_id": "request-1",
            "turn_id": "turn-1",
            "observation_epoch": 3,
            "sequence": 8,
        })
        await asyncio.sleep(0.01)
        for _ws, (_queue, task, _role) in list(bus._clients.items()):
            task.cancel()
        return app.sent, console.sent

    app_messages, console_messages = asyncio.run(scenario())
    assert [json.loads(message)["type"] for message in app_messages] == ["ax_action"]
    assert console_messages == []


def test_stalled_client_is_disconnected_at_bounded_queue_limit():
    class SlowWS(FakeWS):
        async def send_text(self, data: str) -> None:
            await asyncio.Future()

    async def scenario():
        bus = Broadcaster()
        ws = SlowWS()
        bus.attach(ws, "console")
        await asyncio.sleep(0)
        for index in range(CLIENT_QUEUE_LIMIT + 2):
            bus.publish({"type": "trace", "index": index})
        await asyncio.sleep(0)
        return ws in bus.clients, getattr(ws, "close_code", None)

    attached, close_code = asyncio.run(scenario())

    assert attached is False
    assert close_code == 1013
