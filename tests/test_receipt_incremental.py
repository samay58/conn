"""Incremental receipts exist on disk from the first response.done. A process
killed mid-session still leaves a real receipt (Defect 8: Jul 3 session spent
$0.065 and left nothing behind).
"""

from __future__ import annotations

import asyncio
import json
import pathlib

import pytest

from conn.app import ConnApp
from conn.realtime.fake import FakeRealtimeAdapter
from conn.state import Phase
from conn.tools.fake_executors import FAKE_EXECUTORS
from conn.tools.harness import ToolHarness
from conn.tools.registry import build_registry
from conn.trace import write_receipt


def build_app(cfg, ctx):
    cfg.data_dir = ctx.screenshot_dir.parent / "data"
    harness = ToolHarness(build_registry(), cfg, ctx, executors=FAKE_EXECUTORS)
    adapter = FakeRealtimeAdapter(pace_s=0.0)
    app = ConnApp(cfg, adapter, harness)
    messages = []
    app.publisher = messages.append
    return app, messages


async def wait_for_phase(app, phase, timeout=3.0):
    async def poll():
        while app.machine.phase is not phase:
            await asyncio.sleep(0.01)
    await asyncio.wait_for(poll(), timeout)


def receipt_files(app):
    receipts_dir = app.cfg.data_dir / "receipts"
    if not receipts_dir.exists():
        return []
    return list(receipts_dir.glob(f"*/{app.session_id}.json"))


class TestIncrementalReceipt:
    def test_receipt_file_exists_after_first_response_done_not_final(self, cfg, ctx):
        async def run():
            app, _ = build_app(cfg, ctx)
            await app.start()
            await app.on_text("something unmatched by any scripted scenario")
            await wait_for_phase(app, Phase.DONE)
            return app

        app = asyncio.run(run())
        files = receipt_files(app)
        assert files, "receipt file should exist after the first response_done"
        data = json.loads(files[0].read_text())
        assert data["model_responses"] >= 1
        assert data["final"] is False

    def test_receipt_finalizes_on_clean_stop(self, cfg, ctx):
        async def run():
            app, _ = build_app(cfg, ctx)
            await app.start()
            await app.on_text("something unmatched by any scripted scenario")
            await wait_for_phase(app, Phase.DONE)
            await app.stop()
            return app

        app = asyncio.run(run())
        files = receipt_files(app)
        assert files
        data = json.loads(files[0].read_text())
        assert data["final"] is True

    def test_kill_mid_session_leaves_a_valid_parseable_receipt(self, cfg, ctx):
        async def run():
            app, _ = build_app(cfg, ctx)
            await app.start()
            await app.on_text("another unmatched utterance for the fallback scenario")
            await wait_for_phase(app, Phase.DONE)
            # Simulate a kill: no app.stop(), no clean session_end trace event,
            # no final flip. The incremental snapshot from response_done must
            # already be a complete, parseable receipt on disk.
            return app

        app = asyncio.run(run())
        files = receipt_files(app)
        assert files, "a killed session must still leave a receipt on disk"
        data = json.loads(files[0].read_text())
        assert isinstance(data, dict)
        assert data["model_responses"] >= 1
        assert "estimated_usd" in data
        assert data["final"] is False


class TestAtomicReceiptWrite:
    def test_partial_write_failure_does_not_corrupt_existing_receipt(self, tmp_path, monkeypatch):
        # write_receipt is truncate-then-write onto the real receipt path, so
        # a kill mid-write (process dies after the file is opened for write
        # but before all bytes land) leaves a truncated, unparseable file in
        # place of what was previously a valid receipt. Simulate that kill by
        # making write_text land half its bytes on disk, then raise.
        first = {"model_responses": 1, "estimated_usd": 0.01, "final": False}
        path = write_receipt(tmp_path, "session_x", first)
        assert json.loads(path.read_text()) == first

        real_write_text = pathlib.Path.write_text

        def flaky_write_text(self, data, *args, **kwargs):
            real_write_text(self, data[: len(data) // 2])
            raise OSError("simulated kill mid-write")

        monkeypatch.setattr(pathlib.Path, "write_text", flaky_write_text)

        second = {"model_responses": 2, "estimated_usd": 0.02, "final": False}
        with pytest.raises(OSError):
            write_receipt(tmp_path, "session_x", second)

        # An atomic write lands the crash on a temp file, not the real
        # receipt path, so the original valid snapshot must still be there.
        data = json.loads(path.read_text())
        assert data == first
