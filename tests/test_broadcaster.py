"""Shutdown hygiene for the console broadcaster (bug 5 of the 2026-07-07
drive): every detach must cancel the client's writer task, or the loop
tears down over tasks still pending on queue.get() and asyncio logs
"Task was destroyed but it is pending" per client."""

import asyncio

from conn.server.http import Broadcaster


class FakeWS:
    def __init__(self):
        self.sent = []

    async def send_text(self, data: str) -> None:
        self.sent.append(data)


def test_detach_cancels_the_writer_task():
    async def scenario():
        bus = Broadcaster()
        ws = FakeWS()
        bus.attach(ws)
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
        bus.attach(stays)
        bus.attach(leaves)
        bus.detach(leaves)
        bus.publish({"type": "state"})
        await asyncio.sleep(0.01)  # writer drains the queue
        for _ws, (_queue, task) in list(bus._clients.items()):
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
        bus.attach(ws)
        bus.detach(ws)
        await asyncio.sleep(0)
        return [task for task in asyncio.all_tasks()
                if task is not asyncio.current_task() and not task.done()]

    pending = asyncio.run(scenario())
    assert pending == []
