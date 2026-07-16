import json

import pytest

from conn.lab.truth_server import (
    LoopbackHTTPServer,
    TruthHandler,
    TruthStore,
    render_media_page,
)


def test_media_page_reports_load_pointer_and_space_without_external_assets() -> None:
    page = render_media_page(run_id="run-1")

    assert "http://" not in page
    assert "<canvas" in page
    assert '"page_loaded"' in page
    assert '"page_hidden"' in page
    assert '"pointer_play"' in page
    assert '"space_play"' in page


def test_truth_store_appends_bounded_events(tmp_path) -> None:
    store = TruthStore(tmp_path / "browser-truth.jsonl", run_id="run-1")

    event = store.record({
        "run_id": "run-1",
        "event": "page_loaded",
        "value": "ready",
    })

    assert event["sequence"] == 1
    assert json.loads((tmp_path / "browser-truth.jsonl").read_text())[
        "event"
    ] == "page_loaded"
    with pytest.raises(ValueError, match="run"):
        store.record({"run_id": "wrong", "event": "page_loaded"})


def test_loopback_server_bind_never_waits_for_reverse_dns(monkeypatch) -> None:
    monkeypatch.setattr(
        "socket.getfqdn",
        lambda _host: (_ for _ in ()).throw(AssertionError("DNS used")),
    )

    server = LoopbackHTTPServer(("127.0.0.1", 0), TruthHandler)
    server.server_close()
