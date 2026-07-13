"""R1 lifecycle proof against real daemon processes on a test port.

Run explicitly: PYTHONPATH=src .venv/bin/python -m pytest tests -m lifecycle -q

Covers the R1 exit bars that unit tests cannot: repeated graceful
quit-and-relaunch cycles with no manual cleanup, crash-and-relaunch
recovery, and bounded orphan exit after parent loss.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
PYTHON = str(REPO / ".venv" / "bin" / "python")
PORT = 18787
TOKEN = "lifecycle-test-token"

pytestmark = pytest.mark.lifecycle


def write_config(tmp_path: Path) -> Path:
    data_dir = tmp_path / "data"
    data_dir.mkdir(exist_ok=True)
    config = tmp_path / "config.toml"
    config.write_text(
        f'data_dir = "{data_dir}"\n[server]\nhost = "127.0.0.1"\nport = {PORT}\n'
    )
    return config


def spawn_daemon(config: Path, *, parent_env: dict | None = None) -> subprocess.Popen:
    env = {**os.environ, "PYTHONPATH": "src", "CONN_BRIDGE_TOKEN": TOKEN}
    env.update(parent_env or {})
    return subprocess.Popen(
        [PYTHON, "-m", "conn", "--demo", "--simulate-tools",
         "--config", str(config)],
        cwd=REPO, env=env,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )


def port_open() -> bool:
    with socket.socket() as sock:
        sock.settimeout(0.2)
        return sock.connect_ex(("127.0.0.1", PORT)) == 0


def wait_for(predicate, timeout_s: float, what: str) -> None:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.05)
    raise AssertionError(f"timed out waiting for {what}")


def send_authenticated_shutdown() -> None:
    """Minimal app-role WS client: answer the HMAC challenge, then send the
    shutdown frame the Swift app sends on quit."""
    import websockets.sync.client as ws_client

    with ws_client.connect(f"ws://127.0.0.1:{PORT}/ws") as ws:
        challenge = json.loads(ws.recv())["challenge"]
        proof = hmac.new(
            TOKEN.encode(),
            f"conn-app-websocket-v1:{challenge}".encode(),
            hashlib.sha256,
        ).hexdigest()
        ws.send(json.dumps({"type": "client_hello", "role": "app",
                            "proof": proof}))
        hello = json.loads(ws.recv())
        assert hello["type"] == "hello"
        ws.send(json.dumps({"type": "shutdown"}))
        time.sleep(0.1)


def test_fifty_graceful_quit_and_reopen_cycles(tmp_path):
    config = write_config(tmp_path)
    assert not port_open(), "test port must start free"
    for cycle in range(50):
        daemon = spawn_daemon(config)
        try:
            wait_for(port_open, 10, f"daemon up (cycle {cycle})")
            send_authenticated_shutdown()
            wait_for(lambda: daemon.poll() is not None, 5,
                     f"graceful exit (cycle {cycle})")
            assert daemon.returncode == 0, f"cycle {cycle}: exit {daemon.returncode}"
            wait_for(lambda: not port_open(), 5, f"port freed (cycle {cycle})")
        finally:
            if daemon.poll() is None:
                daemon.kill()
                daemon.wait(timeout=5)


def test_twenty_crash_and_relaunch_cycles(tmp_path):
    config = write_config(tmp_path)
    assert not port_open(), "test port must start free"
    for cycle in range(20):
        daemon = spawn_daemon(config)
        try:
            wait_for(port_open, 10, f"daemon up (cycle {cycle})")
        finally:
            daemon.kill()
        daemon.wait(timeout=5)
        wait_for(lambda: not port_open(), 5, f"port freed after kill (cycle {cycle})")


def test_orphaned_daemon_exits_after_bounded_grace(tmp_path):
    config = write_config(tmp_path)
    assert not port_open(), "test port must start free"
    for cycle in range(3):
        launcher = subprocess.Popen(
            [PYTHON, "-c", (
                "import os, subprocess, sys, time\n"
                f"env = dict(os.environ, PYTHONPATH='src',"
                f" CONN_BRIDGE_TOKEN='{TOKEN}',"
                " CONN_PARENT_PID=str(os.getpid()),"
                " CONN_ORPHAN_GRACE_S='1')\n"
                f"child = subprocess.Popen([{PYTHON!r}, '-m', 'conn', '--demo',"
                f" '--simulate-tools', '--config', {str(config)!r}],"
                f" cwd={str(REPO)!r}, env=env,"
                " stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)\n"
                "print(child.pid, flush=True)\n"
                "time.sleep(120)\n"
            )],
            stdout=subprocess.PIPE, text=True,
        )
        assert launcher.stdout is not None
        daemon_pid = int(launcher.stdout.readline().strip())
        try:
            wait_for(port_open, 10, f"owned daemon up (cycle {cycle})")
            launcher.send_signal(signal.SIGKILL)
            launcher.wait(timeout=5)

            def daemon_gone() -> bool:
                try:
                    os.kill(daemon_pid, 0)
                    return False
                except ProcessLookupError:
                    return True

            # poll 2s + grace 1s + shutdown margin
            wait_for(daemon_gone, 15, f"orphan exit (cycle {cycle})")
            wait_for(lambda: not port_open(), 5,
                     f"port freed after orphan exit (cycle {cycle})")
        finally:
            if launcher.poll() is None:
                launcher.kill()
            try:
                os.kill(daemon_pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
