from __future__ import annotations

import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import re
import threading
import time
from urllib.parse import urlparse
from socketserver import TCPServer


_RUN_ID = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
_EVENT = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
MAX_EVENT_BYTES = 4_096


class TruthStore:
    def __init__(self, path: Path, *, run_id: str):
        if not _RUN_ID.fullmatch(run_id):
            raise ValueError("run id is invalid")
        self.path = path
        self.run_id = run_id
        self._lock = threading.Lock()
        self._sequence = 0
        path.parent.mkdir(parents=True, exist_ok=True)
        path.touch(exist_ok=True)

    def record(self, raw: dict) -> dict:
        if raw.get("run_id") != self.run_id:
            raise ValueError("run id does not match")
        event = raw.get("event")
        value = raw.get("value")
        if not isinstance(event, str) or not _EVENT.fullmatch(event):
            raise ValueError("event name is invalid")
        if value is not None and (
            not isinstance(value, str) or len(value) > 256
        ):
            raise ValueError("event value is invalid")
        with self._lock:
            self._sequence += 1
            payload = {
                "run_id": self.run_id,
                "sequence": self._sequence,
                "monotonic_ns": time.monotonic_ns(),
                "event": event,
            }
            if value is not None:
                payload["value"] = value
            encoded = json.dumps(
                payload,
                separators=(",", ":"),
                sort_keys=True,
            ).encode()
            if len(encoded) > MAX_EVENT_BYTES:
                raise ValueError("event exceeds byte limit")
            with self.path.open("ab") as handle:
                handle.write(encoded + b"\n")
        return payload


def render_media_page(*, run_id: str) -> str:
    if not _RUN_ID.fullmatch(run_id):
        raise ValueError("run id is invalid")
    return f"""<!doctype html>
<html lang="en">
<meta charset="utf-8">
<title>Conn Lab Media</title>
<style>
html, body {{ margin: 0; height: 100%; background: #f7f7f2; }}
body {{ display: grid; place-items: center; font: 20px system-ui; }}
canvas {{ width: 720px; height: 420px; background: #202124; }}
</style>
<canvas id="media" width="720" height="420" aria-hidden="true"></canvas>
<script>
const runID = {json.dumps(run_id)};
const canvas = document.getElementById("media");
const context = canvas.getContext("2d");
let playing = false;
function report(event, value) {{
  fetch("/event", {{
    method: "POST",
    headers: {{"Content-Type": "application/json"}},
    body: JSON.stringify({{run_id: runID, event, value}})
  }});
}}
function draw() {{
  context.fillStyle = "#202124";
  context.fillRect(0, 0, canvas.width, canvas.height);
  context.fillStyle = "#ffffff";
  context.font = "32px system-ui";
  context.textAlign = "center";
  context.fillText(playing ? "Pause" : "Play", 360, 220);
}}
function activate(source) {{
  playing = !playing;
  draw();
  report(source, playing ? "playing" : "paused");
}}
canvas.addEventListener("click", () => activate("pointer_play"));
document.addEventListener("keydown", event => {{
  if (event.code === "Space") {{
    event.preventDefault();
    activate("space_play");
  }}
}});
let hiddenReported = false;
document.addEventListener("visibilitychange", () => {{
  if (document.hidden && !hiddenReported) {{
    hiddenReported = true;
    report("page_hidden", "hidden");
  }}
}});
draw();
report("page_loaded", "ready");
</script>
</html>
"""


class TruthHandler(BaseHTTPRequestHandler):
    store: TruthStore

    def do_GET(self) -> None:
        path = urlparse(self.path).path
        if path == "/health":
            self._send(200, b'{"ok":true}', "application/json")
            return
        if path == "/media":
            page = render_media_page(run_id=self.store.run_id).encode()
            self._send(200, page, "text/html; charset=utf-8")
            return
        self._send(404, b'{"ok":false}', "application/json")

    def do_POST(self) -> None:
        if urlparse(self.path).path != "/event":
            self._send(404, b'{"ok":false}', "application/json")
            return
        length = self.headers.get("Content-Length")
        if not isinstance(length, str) or not length.isdigit():
            self._send(400, b'{"ok":false}', "application/json")
            return
        size = int(length)
        if not 1 <= size <= MAX_EVENT_BYTES:
            self._send(413, b'{"ok":false}', "application/json")
            return
        try:
            raw = json.loads(self.rfile.read(size))
            if not isinstance(raw, dict):
                raise ValueError("event is not an object")
            event = self.store.record(raw)
        except (ValueError, json.JSONDecodeError):
            self._send(400, b'{"ok":false}', "application/json")
            return
        self._send(
            200,
            json.dumps(event, separators=(",", ":")).encode(),
            "application/json",
        )

    def log_message(self, format: str, *args) -> None:
        return

    def _send(self, status: int, body: bytes, content_type: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)


class LoopbackHTTPServer(ThreadingHTTPServer):
    def server_bind(self) -> None:
        TCPServer.server_bind(self)
        host, port = self.server_address[:2]
        self.server_name = host
        self.server_port = port


def serve(*, host: str, port: int, store: TruthStore) -> None:
    handler = type("BoundTruthHandler", (TruthHandler,), {"store": store})
    server = LoopbackHTTPServer((host, port), handler)
    server.serve_forever()


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m conn.lab.truth_server")
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--truth-log", type=Path, required=True)
    parser.add_argument("--port", type=int, default=18888)
    args = parser.parse_args()
    if not 1_024 <= args.port <= 65_535:
        raise ValueError("truth server port is invalid")
    serve(
        host="127.0.0.1",
        port=args.port,
        store=TruthStore(args.truth_log, run_id=args.run_id),
    )


if __name__ == "__main__":
    main()
