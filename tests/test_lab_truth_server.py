import json

import pytest

from conn.lab.truth_server import (
    LoopbackHTTPServer,
    TruthHandler,
    TruthStore,
    render_atlas_page,
    render_history_page,
    render_media_page,
    render_navigation_page,
    render_target_page,
)


def test_atlas_page_reports_readiness_and_exposes_frozen_shapes() -> None:
    page = render_atlas_page(run_id="run-1")

    assert "http://" not in page
    assert "<button" in page
    assert 'type="search"' in page
    assert '"accessibility_ready"' in page
    assert "Appendix" in page


def test_media_page_reports_load_pointer_and_space_without_external_assets() -> None:
    page = render_media_page(run_id="run-1")

    assert "http://" not in page
    assert "<canvas" in page
    assert '"page_loaded"' in page
    assert '"page_hidden"' in page
    assert '"pointer_play"' in page
    assert '"space_play"' in page
    assert 'canvas.addEventListener("click"' not in page
    assert 'document.addEventListener("click"' in page


def test_navigation_page_reports_when_appendix_enters_the_viewport() -> None:
    page = render_navigation_page(run_id="run-1")

    assert "Appendix" in page
    assert '"appendix_visible"' in page
    assert '"accessibility_ready"' in page
    assert "IntersectionObserver" in page


def test_target_page_has_a_stable_title_and_distinct_visibility_events() -> None:
    page = render_target_page(run_id="run-1")

    assert "<title>Example Domain</title>" in page
    assert '"target_loaded"' in page
    assert '"target_hidden"' in page


def test_history_page_reports_load_and_a_return_from_browser_history() -> None:
    start = render_history_page(run_id="run-1", page="start")
    end = render_history_page(run_id="run-1", page="end")

    assert '"history_start_loaded"' in start
    assert '"history_returned"' in start
    assert '"history_end_loaded"' in end
    assert 'window.location.assign("/history-end")' in start
    assert "if (returned)" in start
    assert "http://" not in start


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
