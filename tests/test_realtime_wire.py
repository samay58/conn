"""R1 wire contract: the live adapter against a strict Realtime server.

These tests drive the real OpenAIRealtimeAdapter over an in-memory socket
that enforces the rules the July 12 session broke. The exit bar is zero
protocol errors across 1,000 replayed normal turns, including the exact
July 12 command sequence.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
from pathlib import Path

import pytest

from conn.config import Config
from conn.realtime.openai_ws import OpenAIRealtimeAdapter
from conn.observations import parse_model_observation, parse_visual_observation
from tests.strict_realtime import StrictRealtimeServer

CASSETTE = Path(__file__).parent / "cassettes" / "2026-07-12-session_a4f5c83703.json"


def model_observation(index: int):
    return parse_model_observation({
        "snapshot_id": f"snapshot_{index}",
        "observation_id": f"observation_{index}",
        "turn_id": "turn",
        "observation_epoch": index,
        "bundle_id": "com.apple.Safari",
        "window_id": 1,
        "candidate_count": 0,
        "candidate_bytes": 2,
        "candidates": [],
    })


def visual_observation(index: int):
    image = b"\xff\xd8\xff" + f"image-{index}".encode()
    return parse_visual_observation({
        "capture_id": f"capture_{index}",
        "image_data_url": "data:image/jpeg;base64," + base64.b64encode(image).decode(),
        "image_sha256": hashlib.sha256(image).hexdigest(),
        "image_bytes": len(image),
        "mime_type": "image/jpeg",
        "pixel_width": 20,
        "pixel_height": 10,
        "scale": 1.0,
        "window_id": 1,
        "bundle_id": "com.conn.fixture",
        "window_frame": {"x": 0, "y": 0, "width": 20, "height": 10},
        "captured_ms": index,
        "excluded_conn_surfaces": True,
    })


def make_adapter(monkeypatch, server: StrictRealtimeServer) -> OpenAIRealtimeAdapter:
    cfg = Config()
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")

    async def fake_connect(url, additional_headers=None, max_size=None):
        return server.connect()

    import conn.realtime.openai_ws as ws_module
    monkeypatch.setattr(ws_module.websockets, "connect", fake_connect)
    return OpenAIRealtimeAdapter(cfg, tools=[], instructions="test")


async def drain_ready(adapter):
    """Consume queued server events without blocking on an open socket."""
    events = []
    ws = adapter._ws
    while ws is not None and not ws.queue.empty():
        raw = await ws.queue.get()
        if raw is None:
            break
        for ev in adapter._normalize(json.loads(raw)):
            events.append(ev)
    return events


async def settle(adapter, awaitable):
    task = asyncio.create_task(awaitable)
    for _ in range(100):
        await drain_ready(adapter)
        await asyncio.sleep(0)
        if task.done():
            return await task
    task.cancel()
    raise AssertionError("adapter operation did not settle")


class TestItemLedger:
    def test_visual_context_sends_image_content_and_replaces_prior_image(self):
        async def run():
            adapter = OpenAIRealtimeAdapter(Config(), [], "test")
            sent = []

            async def capture(payload):
                sent.append(payload)

            adapter._send = capture
            for index in (1, 2):
                task = asyncio.create_task(
                    adapter.replace_visual_context(visual_observation(index))
                )
                await asyncio.sleep(0)
                create = sent[-1]
                content = create["item"]["content"]
                image = next(part for part in content if part["type"] == "input_image")
                assert image["image_url"].startswith("data:image/jpeg;base64,")
                assert not image["image_url"].startswith("file:")
                new_id = create["item"]["id"]
                adapter._normalize({
                    "type": "conversation.item.created", "item": {"id": new_id}
                })
                for _ in range(10):
                    await asyncio.sleep(0)
                    deletes = [f for f in sent if f["type"] == "conversation.item.delete"]
                    if len(deletes) == index - 1:
                        break
                if index == 2:
                    old_id = deletes[-1]["item_id"]
                    adapter._normalize({
                        "type": "conversation.item.deleted", "item_id": old_id
                    })
                await task
            return adapter, sent

        adapter, sent = asyncio.run(run())
        assert len([f for f in sent if f["type"] == "conversation.item.create"]) == 2
        assert len([f for f in sent if f["type"] == "conversation.item.delete"]) == 1
        assert len(adapter._items) == 1
        assert adapter._visual_item_id in adapter._items

    def test_context_item_ids_obey_the_live_limit(self, monkeypatch):
        async def run():
            server = StrictRealtimeServer()
            adapter = make_adapter(monkeypatch, server)
            await adapter.connect()
            await settle(adapter, adapter.upsert_semantic_context("ctx one"))
            return server

        server = asyncio.run(run())
        creates = [f for f in server.client_frames
                   if f["type"] == "conversation.item.create"]
        assert creates, "context create must reach the server"
        item_id = creates[0]["item"]["id"]
        assert len(item_id) <= 32
        assert server.protocol_errors == []

    def test_only_acknowledged_items_are_deleted(self, monkeypatch):
        async def run():
            server = StrictRealtimeServer()
            adapter = make_adapter(monkeypatch, server)
            await adapter.connect()
            await settle(adapter, adapter.upsert_semantic_context("ctx one"))
            for ev in await drain_ready(adapter):
                pass
            await settle(adapter, adapter.upsert_semantic_context("ctx two"))
            return server

        server = asyncio.run(run())
        deletes = [f for f in server.client_frames
                   if f["type"] == "conversation.item.delete"]
        assert len(deletes) == 1
        assert server.protocol_errors == []

    def test_failed_create_never_becomes_active_context(self, monkeypatch):
        """A rejected create must not be remembered and deleted later: the
        July 12 session sent 16 deletes for items that never existed."""
        async def run():
            server = StrictRealtimeServer()
            server.ITEM_ID_MAX = 4  # force every create to fail
            adapter = make_adapter(monkeypatch, server)
            await adapter.connect()
            with pytest.raises(RuntimeError, match="observation item create failed"):
                await settle(adapter, adapter.upsert_semantic_context("ctx one"))
            for ev in await drain_ready(adapter):
                pass
            with pytest.raises(RuntimeError, match="observation item create failed"):
                await settle(adapter, adapter.upsert_semantic_context("ctx two"))
            for ev in await drain_ready(adapter):
                pass
            return server

        server = asyncio.run(run())
        deletes = [f for f in server.client_frames
                   if f["type"] == "conversation.item.delete"]
        assert deletes == [], "no delete may target an unacknowledged item"
        errors = [e for e in server.protocol_errors if "deleting" in e]
        assert errors == []

    def test_snapshot_tool_result_takes_the_same_ledger_path(self, monkeypatch):
        async def run():
            server = StrictRealtimeServer()
            adapter = make_adapter(monkeypatch, server)
            await adapter.connect()
            output = json.dumps({"ok": True,
                                 "data": {"snapshot_id": "snap1", "render": "x"}})
            await settle(adapter, adapter.send_tool_result(
                "call_1", output, model_observation=model_observation(1)
            ))
            for ev in await drain_ready(adapter):
                pass
            await settle(adapter, adapter.send_tool_result(
                "call_2", json.dumps({"ok": True,
                                      "data": {"snapshot_id": "snap2"}}),
                model_observation=model_observation(2),
            ))
            return server

        server = asyncio.run(run())
        creates = [f for f in server.client_frames
                   if f["type"] == "conversation.item.create"]
        assert all(len(f["item"].get("id", "")) <= 32 for f in creates
                   if "id" in f["item"])
        assert server.protocol_errors == []

    def test_replacement_waits_for_create_ack_before_deleting_current(self):
        async def run():
            adapter = OpenAIRealtimeAdapter(Config(), [], "test")
            adapter._ws = type("Socket", (), {"send": lambda self, value: None})()
            sent = []

            async def capture(payload):
                sent.append(payload)

            adapter._send = capture
            first = asyncio.create_task(adapter.upsert_semantic_context("first"))
            await asyncio.sleep(0)
            first_id = sent[-1]["item"]["id"]
            adapter._normalize({"type": "conversation.item.created", "item": {"id": first_id}})
            await first

            second = asyncio.create_task(adapter.upsert_semantic_context("second"))
            await asyncio.sleep(0)
            second_id = sent[-1]["item"]["id"]
            assert adapter._semantic_item_id == first_id
            assert not any(frame["type"] == "conversation.item.delete" for frame in sent)

            adapter._normalize({"type": "conversation.item.created", "item": {"id": second_id}})
            for _ in range(10):
                await asyncio.sleep(0)
                if sent[-1]["type"] == "conversation.item.delete":
                    break
            delete = sent[-1]
            assert delete["type"] == "conversation.item.delete"
            assert delete["item_id"] == first_id
            adapter._normalize({"type": "conversation.item.deleted", "item_id": first_id})
            await second
            return adapter, first_id, second_id

        adapter, first_id, second_id = asyncio.run(run())
        assert adapter._semantic_item_id == second_id
        assert first_id not in adapter._items

    def test_live_item_added_event_acknowledges_context_create(self):
        async def run():
            adapter = OpenAIRealtimeAdapter(Config(), [], "test")
            adapter._ws = type("Socket", (), {"send": lambda self, value: None})()
            sent = []

            async def capture(payload):
                sent.append(payload)

            adapter._send = capture
            task = asyncio.create_task(adapter.upsert_semantic_context("context"))
            await asyncio.sleep(0)
            item_id = sent[-1]["item"]["id"]
            adapter._normalize({
                "type": "conversation.item.added",
                "item": {"id": item_id},
            })
            await asyncio.wait_for(task, timeout=0.1)
            return adapter, item_id

        adapter, item_id = asyncio.run(run())
        assert adapter._semantic_item_id == item_id
        assert item_id in adapter._items

    def test_failed_replacement_create_preserves_acknowledged_current(self):
        async def run():
            adapter = OpenAIRealtimeAdapter(Config(), [], "test")
            sent = []

            async def capture(payload):
                sent.append(payload)

            adapter._send = capture
            first = asyncio.create_task(adapter.upsert_semantic_context("first"))
            await asyncio.sleep(0)
            first_frame = sent[-1]
            first_id = first_frame["item"]["id"]
            adapter._normalize({"type": "conversation.item.created", "item": {"id": first_id}})
            await first

            second = asyncio.create_task(adapter.upsert_semantic_context("second"))
            await asyncio.sleep(0)
            second_frame = sent[-1]
            error = adapter._normalize({
                "type": "error",
                "error": {"message": "forced", "event_id": second_frame["event_id"]},
            })
            with pytest.raises(RuntimeError, match="observation item create failed"):
                await second
            return adapter, sent, first_id, error

        adapter, sent, first_id, error = asyncio.run(run())
        assert adapter._semantic_item_id == first_id
        assert not any(
            frame["type"] == "conversation.item.delete"
            and frame["item_id"] == first_id
            for frame in sent
        )
        assert error[0].related.startswith("item_create:")

    def test_twenty_observations_leave_one_current_item(self):
        async def run():
            adapter = OpenAIRealtimeAdapter(Config(), [], "test")
            sent = []

            async def capture(payload):
                sent.append(payload)

            adapter._send = capture
            for index in range(20):
                task = asyncio.create_task(adapter.upsert_semantic_context(str(index)))
                await asyncio.sleep(0)
                create = sent[-1]
                new_id = create["item"]["id"]
                adapter._normalize({
                    "type": "conversation.item.created", "item": {"id": new_id}
                })
                for _ in range(10):
                    await asyncio.sleep(0)
                    if len([
                        frame for frame in sent
                        if frame["type"] == "conversation.item.delete"
                    ]) == index:
                        break
                deletes = [frame for frame in sent if frame["type"] == "conversation.item.delete"]
                if deletes and deletes[-1]["item_id"] in adapter._items:
                    old_id = deletes[-1]["item_id"]
                    adapter._normalize({"type": "conversation.item.deleted", "item_id": old_id})
                await task
            return adapter, sent

        adapter, sent = asyncio.run(run())
        assert len([frame for frame in sent if frame["type"] == "conversation.item.create"]) == 20
        assert len([frame for frame in sent if frame["type"] == "conversation.item.delete"]) == 19
        assert len(adapter._items) == 1
        assert adapter._semantic_item_id in adapter._items


class TestCancelBinding:
    def test_cancel_without_active_response_sends_nothing(self, monkeypatch):
        async def run():
            server = StrictRealtimeServer()
            adapter = make_adapter(monkeypatch, server)
            await adapter.connect()
            await adapter.cancel_response()
            return server

        server = asyncio.run(run())
        cancels = [f for f in server.client_frames
                   if f["type"] == "response.cancel"]
        assert cancels == []
        assert server.protocol_errors == []

    def test_cancel_of_active_response_includes_its_id(self, monkeypatch):
        async def run():
            server = StrictRealtimeServer()
            adapter = make_adapter(monkeypatch, server)
            await adapter.connect()
            # Make a response active from the adapter's point of view but not
            # yet complete: feed only response.created through _normalize.
            server.active_response_id = "resp_live"
            for ev in adapter._normalize({"type": "response.created",
                                          "response": {"id": "resp_live"}}):
                pass
            await adapter.cancel_response()
            return server

        server = asyncio.run(run())
        cancels = [f for f in server.client_frames
                   if f["type"] == "response.cancel"]
        assert len(cancels) == 1
        assert cancels[0]["response_id"] == "resp_live"
        assert server.protocol_errors == []

    def test_completed_response_clears_the_binding(self, monkeypatch):
        async def run():
            server = StrictRealtimeServer()
            adapter = make_adapter(monkeypatch, server)
            await adapter.connect()
            for msg in ({"type": "response.created",
                         "response": {"id": "resp_1"}},
                        {"type": "response.done",
                         "response": {"id": "resp_1", "status": "completed",
                                      "usage": {}}}):
                for ev in adapter._normalize(msg):
                    pass
            await adapter.cancel_response()
            return server

        server = asyncio.run(run())
        assert [f for f in server.client_frames
                if f["type"] == "response.cancel"] == []


class TestReplayProof:
    def _turn(self, server, adapter):
        async def one_turn(text: str, barge_in: bool):
            await settle(
                adapter, adapter.upsert_semantic_context(f"[context] {text}")
            )
            await adapter.append_audio(b"\x00\x02" * 480)
            await adapter.commit_input()
            await adapter.create_response()
            for ev in await drain_ready(adapter):
                pass
            if barge_in:
                await adapter.cancel_response()
                for ev in await drain_ready(adapter):
                    pass
        return one_turn

    def test_thousand_replayed_turns_zero_protocol_errors(self, monkeypatch):
        async def run():
            server = StrictRealtimeServer()
            adapter = make_adapter(monkeypatch, server)
            await adapter.connect()
            turn = self._turn(server, adapter)
            for n in range(1000):
                await turn(f"turn {n}", barge_in=(n % 7 == 0))
            return server

        server = asyncio.run(run())
        assert server.protocol_errors == []

    @pytest.mark.skipif(not CASSETTE.exists(), reason="cassette not generated")
    def test_july_12_cassette_replays_clean(self, monkeypatch):
        cassette = json.loads(CASSETTE.read_text())

        async def run():
            server = StrictRealtimeServer()
            adapter = make_adapter(monkeypatch, server)
            await adapter.connect()
            for turn in cassette["turns"]:
                for call in turn["tool_calls"]:
                    server.script_tool_calls.append(
                        {"call_id": f"call_{turn['turn']}",
                         "name": call["name"],
                         "arguments": call.get("arguments") or {}})
                await settle(adapter, adapter.upsert_semantic_context(
                    f"[context] turn {turn['turn']}"))
                if turn.get("hold_ms") and turn["hold_ms"] >= 300:
                    await adapter.append_audio(b"\x00\x02" * 480)
                    await adapter.commit_input()
                    await adapter.create_response()
                for ev in await drain_ready(adapter):
                    pass
                for call in turn["tool_calls"]:
                    await adapter.send_tool_result(
                        f"call_{turn['turn']}",
                        json.dumps({"ok": False, "error": "blocked"}))
                for ev in await drain_ready(adapter):
                    pass
            return server

        server = asyncio.run(run())
        assert server.protocol_errors == []


class TestLedgerHygiene:
    def test_event_causes_and_items_stay_bounded_over_turns(self, monkeypatch):
        async def run():
            server = StrictRealtimeServer()
            adapter = make_adapter(monkeypatch, server)
            await adapter.connect()
            for n in range(200):
                await settle(adapter, adapter.upsert_semantic_context(f"turn {n}"))
                for ev in await drain_ready(adapter):
                    pass
            return adapter, server

        adapter, server = asyncio.run(run())
        assert server.protocol_errors == []
        assert len(adapter._items) <= 1
        assert len(adapter._event_causes) <= 2, (
            f"{len(adapter._event_causes)} leaked event causes")

    def test_failed_creates_leave_no_ghost_records(self, monkeypatch):
        async def run():
            server = StrictRealtimeServer()
            server.ITEM_ID_MAX = 4
            adapter = make_adapter(monkeypatch, server)
            await adapter.connect()
            for n in range(5):
                with pytest.raises(RuntimeError, match="observation item create failed"):
                    await settle(
                        adapter, adapter.upsert_semantic_context(f"turn {n}")
                    )
                for ev in await drain_ready(adapter):
                    pass
            return adapter

        adapter = asyncio.run(run())
        assert adapter._items == {}, f"ghost records: {adapter._items}"
        assert adapter._event_causes == {}
