"""conn doctor: verifies the machine before a live session. Checks are honest
about what they can and cannot prove (mic RMS beats stream-opened; Input
Monitoring cannot be probed without side effects, so we try and report).
"""

from __future__ import annotations

import json
import os
import subprocess
import time
from pathlib import Path

from .config import Config

OK = "ok"
WARN = "warn"
FAIL = "fail"


def run_doctor(cfg: Config) -> list[dict]:
    checks = [
        _deps(), _api_key(cfg), _mic(), _input_devices(cfg), _accessibility(),
        _screencapture(), _input_posting(), _qmd(cfg), _obsidian(cfg),
        _mcp(cfg), _input_monitoring_note(),
    ]
    return checks


def _result(name: str, status: str, detail: str) -> dict:
    return {"check": name, "status": status, "detail": detail}


def _deps() -> dict:
    missing = []
    for mod in ("sounddevice", "pynput", "AppKit", "websockets", "starlette"):
        try:
            __import__(mod)
        except Exception:
            missing.append(mod)
    if missing:
        return _result("dependencies", FAIL, f"missing imports: {', '.join(missing)}")
    return _result("dependencies", OK, "sounddevice, pynput, pyobjc, websockets, starlette")


def _api_key(cfg: Config) -> dict:
    if cfg.api_key:
        return _result("openai_api_key", OK, "OPENAI_API_KEY present in environment")
    return _result("openai_api_key", WARN, "not set; only demo mode will work")


def _mic() -> dict:
    try:
        import numpy as np
        import sounddevice as sd

        frames = sd.rec(int(0.4 * 24000), samplerate=24000, channels=1, dtype="int16")
        sd.wait()
        rms = float(np.sqrt(np.mean(frames.astype(np.float64) ** 2)))
        if rms > 1.0:
            return _result("microphone", OK, f"live signal, rms={rms:.0f}")
        return _result("microphone", WARN,
                       f"stream opened but rms={rms:.1f}; if this stays near zero, "
                       "grant Microphone to your terminal in System Settings, Privacy")
    except Exception as e:
        return _result("microphone", FAIL, f"could not record: {e}")


def _input_devices(cfg: Config) -> dict:
    try:
        import sounddevice as sd

        from .audio import resolve_input_device

        devices = list(sd.query_devices())
        selected, warning = resolve_input_device(devices, cfg.audio.input_device)
        if warning:
            return _result("input_devices", WARN, warning)
        try:
            default_input = int(sd.default.device[0])
        except Exception:
            default_input = -1
        names = []
        for index, device in enumerate(devices):
            if int(device.get("max_input_channels", 0) or 0) <= 0:
                continue
            if index == selected:
                marker = " (selected)"
            elif selected is None and index == default_input:
                marker = " (default, in use)"
            else:
                marker = ""
            names.append(f"{device.get('name')}{marker}")
        return _result("input_devices", OK, "; ".join(names) or "no input devices found")
    except Exception as e:
        return _result("input_devices", FAIL, str(e))


def _accessibility() -> dict:
    try:
        from ApplicationServices import AXIsProcessTrusted

        from .identity import describe_identity

        identity = describe_identity()
        if AXIsProcessTrusted():
            return _result("accessibility", OK,
                           "optional Python AX grant is present for diagnostics "
                           f"(process image: {identity['grant_target']})")
        return _result(
            "accessibility",
            OK,
            "Python AX grant is not required by the verified engine. Conn.app "
            "owns production observation and action; its grant is reported when "
            "the authenticated app attaches.",
        )
    except Exception as e:
        return _result("accessibility", FAIL, str(e))


def _input_posting() -> dict:
    try:
        from .tools.ax_input import MacInputBackend

        if MacInputBackend().posting_capability():
            return _result(
                "input_posting",
                OK,
                "CGEvent posting probe passed for this process identity. Run doctor the same way the daemon runs.",
            )
        return _result(
            "input_posting",
            OK,
            "Python CGEvent posting is unavailable and not used in production. "
            "Conn.app owns verified input dispatch.",
        )
    except Exception as e:
        return _result("input_posting", FAIL, str(e))


def _screencapture() -> dict:
    path = Path(f"/tmp/conn-doctor-{int(time.time())}.png")
    try:
        subprocess.run(["/usr/sbin/screencapture", "-x", "-t", "png", str(path)],
                       capture_output=True, timeout=10)
        size = path.stat().st_size if path.exists() else 0
        path.unlink(missing_ok=True)
        if size > 0:
            return _result("screenshot", OK,
                           f"captured {size} bytes. Note: other apps' windows appear "
                           "only with Screen Recording granted")
        return _result("screenshot", WARN, "screencapture produced no file")
    except Exception as e:
        return _result("screenshot", FAIL, str(e))


def _qmd(cfg: Config) -> dict:
    # Same resolution phoenix_search uses, so the doctor reports what runs.
    from .tools.base import ToolError
    from .tools.phoenix import _qmd_command, _qmd_index_env

    configured = cfg.phoenix.qmd_bin
    try:
        exe, _env = _qmd_command(configured)
    except ToolError:
        return _result("qmd", FAIL, f"qmd not found (configured {configured}); "
                                    "phoenix_search will fail")
    if Path(configured).is_absolute() and not Path(configured).exists():
        return _result("qmd", WARN, f"configured {configured} is missing; using {exe}. "
                                    'Set qmd_bin = "qmd" to follow node upgrades')
    try:
        index = Path(_qmd_index_env(cfg)["INDEX_PATH"])
    except ToolError as e:
        return _result("qmd", FAIL, str(e))
    age_days = (time.time() - index.stat().st_mtime) / 86400
    if age_days > 3:
        return _result("qmd", WARN, f"Phoenix index is {int(age_days)} days old; "
                                    "Phoenix's qmd-refresh job may be failing")
    return _result("qmd", OK, f"{exe}; index {index}")


def _obsidian(cfg: Config) -> dict:
    conf = Path.home() / "Library/Application Support/obsidian/obsidian.json"
    try:
        vaults = json.loads(conf.read_text()).get("vaults", {})
        roots = {Path(v.get("path", "")).resolve() for v in vaults.values()}
        if Path(cfg.phoenix.vault_root).resolve() in roots:
            return _result("obsidian_vault", OK,
                           f"vault registered: {cfg.phoenix.vault_root}")
        return _result("obsidian_vault", WARN,
                       "vault root not in Obsidian's registry; obsidian:// URLs may "
                       "open the wrong vault")
    except Exception:
        return _result("obsidian_vault", WARN, "Obsidian registry not readable; "
                                               "open_note falls back to the default app")


def _mcp(cfg: Config) -> dict:
    # Config and Keychain presence only; no network, so it cannot prove a token still works.
    from .mcp_auth import has_tokens

    if not cfg.mcp.servers:
        return _result("mcp", OK, "no MCP servers configured")
    parts, status = [], OK
    for server in cfg.mcp.servers:
        if server.command:
            parts.append(f"{server.name}: stdio")
        elif server.auth != "oauth":
            parts.append(f"{server.name}: no sign-in needed")
        elif has_tokens(server.name):
            parts.append(f"{server.name}: signed in")
        else:
            parts.append(f"{server.name}: not signed in; run --mcp-login {server.name}")
            status = WARN
    return _result("mcp", status, " | ".join(parts))


def _input_monitoring_note() -> dict:
    host = os.environ.get("TERM_PROGRAM", "your terminal")
    return _result("global_hotkey", WARN,
                   f"cannot be probed safely. If global PTT stays dead, grant "
                   f"Input Monitoring to {host} and restart conn. Secure Keyboard "
                   f"Entry (iTerm setting or any password field) also disables it")


def format_report(checks: list[dict]) -> str:
    icons = {OK: "pass", WARN: "warn", FAIL: "FAIL"}
    width = max(len(c["check"]) for c in checks)
    lines = [f"  {icons[c['status']]:>4}  {c['check']:<{width}}  {c['detail']}"
             for c in checks]
    return "conn doctor\n" + "\n".join(lines)
