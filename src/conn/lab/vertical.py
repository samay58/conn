from __future__ import annotations

import argparse
import asyncio
import base64
import copy
import json
from pathlib import Path
import time
from typing import Callable

from conn.app import ConnApp
from conn.config import Config, load_config
from conn.events import new_id
from conn.events import ModelObservation, VisualObservation
from conn.realtime.fake import FakeRealtimeAdapter
from conn.state import Phase
from conn.tools.base import ExecutionContext
from conn.tools.harness import ToolHarness
from conn.tools.registry import build_registry, export_openai


LAB_COMMAND = "lab create fixture window"
MAX_SCRIPTED_AUDIO_BYTES = 64_000
VERTICAL_SCENARIOS = (
    "control",
    "menu",
    "visual",
    "firefox_open",
    "safari_local",
    "safari_tab",
    "firefox_local",
    "firefox_visual",
    "firefox_space",
    "notes_create",
    "notes_type",
    "notes_select",
    "notes_observe",
)
_VERTICAL_COMMANDS = {
    "control": LAB_COMMAND,
    "firefox_open": "Open Firefox",
    "safari_local": "Open the Conn Lab page in Safari",
    "safari_tab": "Open a new tab in Safari",
    "firefox_local": "Open the Conn Lab page in Firefox",
    "firefox_visual": "Play the video in Firefox",
    "firefox_space": "Press Space in Firefox",
    "notes_create": "Create a new note in Notes",
    "notes_type": "Replace the seed note with scratch text",
    "notes_select": "Select the next note in Notes",
    "notes_observe": "Observe the Notes window",
}
LAB_SCENARIO = {
    "id": "lab-create-fixture-window",
    "default": True,
    "match": [LAB_COMMAND],
    "spoken": LAB_COMMAND,
    "segments": [
        {
            "say": "Grounding the fixture control.",
            "tools": [
                {
                    "name": "computer_ax_snapshot",
                    "arguments": {
                        "query": "Continue",
                        "expected_roles": ["AXCheckBox"],
                        "expected_actions": ["AXPress"],
                        "result_limit": 1,
                    },
                }
            ],
            "usage": {
                "input_tokens": 120,
                "output_tokens": 12,
                "input_token_details": {
                    "text_tokens": 120,
                    "audio_tokens": 0,
                    "cached_tokens": 0,
                },
                "output_token_details": {
                    "text_tokens": 12,
                    "audio_tokens": 0,
                },
            },
        },
        {
            "say": "Activating the grounded control.",
            "tools": [
                {
                    "name": "computer_click",
                    "arguments": {
                        "snapshot_id": "__LAB_SNAPSHOT_ID__",
                        "ref": "__LAB_REF__",
                    },
                }
            ],
            "usage": {
                "input_tokens": 180,
                "output_tokens": 14,
                "input_token_details": {
                    "text_tokens": 180,
                    "audio_tokens": 0,
                    "cached_tokens": 80,
                },
                "output_token_details": {
                    "text_tokens": 14,
                    "audio_tokens": 0,
                },
            },
        },
        {
            "say": "The fixture control changed.",
            "usage": {
                "input_tokens": 220,
                "output_tokens": 10,
                "input_token_details": {
                    "text_tokens": 220,
                    "audio_tokens": 0,
                    "cached_tokens": 120,
                },
                "output_token_details": {
                    "text_tokens": 10,
                    "audio_tokens": 0,
                },
            },
        },
    ],
}
MENU_SCENARIO = {
    "id": "lab-create-fixture-window",
    "default": True,
    "match": [LAB_COMMAND],
    "spoken": LAB_COMMAND,
    "segments": [
        {
            "say": "Creating one fixture window.",
            "tools": [{
                "name": "computer_create",
                "arguments": {"kind": "window"},
            }],
            "usage": LAB_SCENARIO["segments"][0]["usage"],
        },
        {
            "say": "The fixture window changed.",
            "usage": LAB_SCENARIO["segments"][2]["usage"],
        },
    ],
}
VISUAL_SCENARIO = {
    "id": "lab-activate-opaque-media",
    "default": True,
    "match": [LAB_COMMAND],
    "spoken": LAB_COMMAND,
    "segments": [
        {
            "say": "Checking for an accessible Play control.",
            "tools": [{
                "name": "computer_ax_snapshot",
                "arguments": {
                    "query": "Play",
                    "expected_actions": ["AXPress"],
                    "result_limit": 1,
                },
            }],
            "usage": LAB_SCENARIO["segments"][0]["usage"],
        },
        {
            "say": "Looking at the current window.",
            "tools": [{
                "name": "computer_visual_observe",
                "arguments": {},
            }],
            "usage": LAB_SCENARIO["segments"][0]["usage"],
        },
        {
            "say": "Activating the visible Play control.",
            "tools": [{
                "name": "computer_activate",
                "arguments": {
                    "goal": "Play media",
                    "grounding": "__LAB_VISUAL_GROUNDING__",
                },
            }],
            "usage": LAB_SCENARIO["segments"][1]["usage"],
        },
        {
            "say": "The control was activated.",
            "usage": LAB_SCENARIO["segments"][2]["usage"],
        },
    ],
}
FIREFOX_OPEN_SCENARIO = {
    "id": "lab-open-firefox",
    "default": True,
    "match": ["open firefox"],
    "spoken": "Open Firefox",
    "segments": [
        {
            "say": "Opening Firefox.",
            "tools": [{
                "name": "app_open",
                "arguments": {"app": "Firefox"},
            }],
            "usage": LAB_SCENARIO["segments"][0]["usage"],
        },
        {
            "say": "Firefox is open.",
            "usage": LAB_SCENARIO["segments"][2]["usage"],
        },
    ],
}
SAFARI_LOCAL_SCENARIO = {
    "id": "lab-safari-local-page",
    "default": True,
    "match": ["open the conn lab page in safari"],
    "spoken": "Open the Conn Lab page in Safari",
    "segments": [
        {
            "say": "Opening the local page in Safari.",
            "tools": [{
                "name": "browser_navigate",
                "arguments": {
                    "url": "http://127.0.0.1:18888/media",
                    "browser_scope": "Safari",
                },
            }],
            "usage": LAB_SCENARIO["segments"][0]["usage"],
        },
        {
            "say": "The local page is open in Safari.",
            "usage": LAB_SCENARIO["segments"][2]["usage"],
        },
    ],
}
SAFARI_TAB_SCENARIO = {
    "id": "lab-safari-new-tab",
    "default": True,
    "match": ["open a new tab in safari"],
    "spoken": "Open a new tab in Safari",
    "segments": [
        {
            "say": "Opening one new Safari tab.",
            "tools": [{
                "name": "computer_create",
                "arguments": {"kind": "tab", "app": "Safari"},
            }],
            "usage": LAB_SCENARIO["segments"][0]["usage"],
        },
        {
            "say": "The Safari tab was requested.",
            "usage": LAB_SCENARIO["segments"][2]["usage"],
        },
    ],
}
FIREFOX_LOCAL_SCENARIO = {
    "id": "lab-firefox-local-page",
    "default": True,
    "match": ["open the conn lab page in firefox"],
    "spoken": "Open the Conn Lab page in Firefox",
    "segments": [
        {
            "say": "Opening the local page in Firefox.",
            "tools": [{
                "name": "browser_navigate",
                "arguments": {
                    "url": "http://127.0.0.1:18888/media",
                    "browser_scope": "Firefox",
                },
            }],
            "usage": LAB_SCENARIO["segments"][0]["usage"],
        },
        {
            "say": "The local page is open in Firefox.",
            "usage": LAB_SCENARIO["segments"][2]["usage"],
        },
    ],
}
FIREFOX_SPACE_SCENARIO = {
    "id": "lab-firefox-space",
    "default": True,
    "match": ["press space in firefox"],
    "spoken": "Press Space in Firefox",
    "segments": [
        {
            "say": "Pressing Space once.",
            "tools": [{
                "name": "computer_key",
                "arguments": {"key": "space"},
            }],
            "usage": LAB_SCENARIO["segments"][0]["usage"],
        },
        {
            "say": "Space was pressed.",
            "usage": LAB_SCENARIO["segments"][2]["usage"],
        },
    ],
}
NOTES_CREATE_SCENARIO = {
    "id": "lab-notes-create",
    "default": True,
    "match": ["create a new note in notes"],
    "spoken": "Create a new note in Notes",
    "segments": [
        {
            "say": "Creating one new note.",
            "tools": [{
                "name": "computer_create",
                "arguments": {"kind": "note", "app": "Notes"},
            }],
            "usage": LAB_SCENARIO["segments"][0]["usage"],
        },
        {
            "say": "The note was requested.",
            "usage": LAB_SCENARIO["segments"][2]["usage"],
        },
    ],
}
NOTES_TYPE_SCENARIO = {
    "id": "lab-notes-type",
    "default": True,
    "match": ["replace the seed note with scratch text"],
    "spoken": "Replace the seed note with scratch text",
    "segments": [
        {
            "say": "Grounding the seed note.",
            "tools": [{
                "name": "computer_ax_snapshot",
                "arguments": {
                    "query": "conn lab seed",
                    "expected_roles": ["AXTextArea"],
                    "result_limit": 1,
                },
            }],
            "usage": LAB_SCENARIO["segments"][0]["usage"],
        },
        {
            "say": "Replacing the seed note text.",
            "tools": [{
                "name": "computer_type_text",
                "arguments": {
                    "snapshot_id": "__LAB_SNAPSHOT_ID__",
                    "ref": "__LAB_REF__",
                    "text": "conn lab scratch",
                    "submit": False,
                },
            }],
            "usage": LAB_SCENARIO["segments"][1]["usage"],
        },
        {
            "say": "The note text was replaced.",
            "usage": LAB_SCENARIO["segments"][2]["usage"],
        },
    ],
}
NOTES_SELECT_SCENARIO = {
    "id": "lab-notes-select",
    "default": True,
    "match": ["select the next note in notes"],
    "spoken": "Select the next note in Notes",
    "segments": [
        {
            "say": "Selecting the next note.",
            "tools": [{
                "name": "computer_select_relative",
                "arguments": {
                    "relation": "next",
                    "kind": "note",
                    "app": "Notes",
                },
            }],
            "usage": LAB_SCENARIO["segments"][0]["usage"],
        },
        {
            "say": "The next note was requested.",
            "usage": LAB_SCENARIO["segments"][2]["usage"],
        },
    ],
}
NOTES_OBSERVE_SCENARIO = {
    "id": "lab-notes-observe",
    "default": True,
    "match": ["observe the notes window"],
    "spoken": "Observe the Notes window",
    "segments": [
        {
            "say": "Capturing the current Notes window.",
            "tools": [{
                "name": "computer_visual_observe",
                "arguments": {},
            }],
            "usage": LAB_SCENARIO["segments"][0]["usage"],
        },
        {
            "say": "The Notes window was captured.",
            "usage": LAB_SCENARIO["segments"][2]["usage"],
        },
    ],
}


def read_scripted_audio(path: Path) -> bytes:
    audio = path.read_bytes()
    if not audio:
        raise ValueError("scripted audio is empty")
    if len(audio) > MAX_SCRIPTED_AUDIO_BYTES:
        raise ValueError("scripted audio exceeds byte limit")
    if len(audio) % 2:
        raise ValueError("scripted audio must contain 16-bit PCM samples")
    return audio


async def inject_scripted_audio(app: ConnApp, path: Path) -> None:
    audio = read_scripted_audio(path)
    await app.on_ptt_down(source="lab_audio", gesture_id="lab-audio")
    await app.adapter.append_audio(audio)
    await asyncio.sleep((app.cfg.session.tap_threshold_ms + 25) / 1000)
    await app.on_ptt_up(source="lab_audio", gesture_id="lab-audio")


def grounded_arguments(observation: ModelObservation) -> dict[str, str]:
    try:
        payload = json.loads(observation.text)
    except ValueError as error:
        raise ValueError("lab observation is invalid") from error
    candidates = payload.get("candidates")
    if not isinstance(candidates, list) or len(candidates) != 1:
        raise ValueError("lab observation must contain one candidate")
    ref = candidates[0].get("ref")
    if not isinstance(ref, str) or not ref:
        raise ValueError("lab candidate ref is invalid")
    return {"snapshot_id": observation.snapshot_id, "ref": ref}


def visual_grounding_arguments(observation: VisualObservation) -> dict:
    return {
        "capture_id": observation.capture_id,
        "region": {
            "x": 0.4,
            "y": 0.4,
            "width": 0.2,
            "height": 0.2,
        },
        "label": "Play",
        "confidence": 0.99,
    }


class GroundedLabAdapter(FakeRealtimeAdapter):
    def __init__(self, scenario: dict | None = None):
        super().__init__([copy.deepcopy(scenario or LAB_SCENARIO)], pace_s=0)
        self._grounding: dict[str, str] | None = None

    async def send_tool_result(
        self,
        call_id: str,
        output: str,
        model_observation=None,
        visual_observation=None,
    ) -> None:
        await super().send_tool_result(
            call_id,
            output,
            model_observation=model_observation,
            visual_observation=visual_observation,
        )
        if model_observation is not None:
            self._grounding = grounded_arguments(model_observation)

    async def create_response(self) -> None:
        if (
            self._pending_input is None
            and self._active is not None
            and self._grounding is not None
            and self._cursor < len(self._active["segments"])
        ):
            segment = self._active["segments"][self._cursor]
            for tool in segment.get("tools", []):
                arguments = tool.get("arguments", {})
                if arguments.get("snapshot_id") == "__LAB_SNAPSHOT_ID__":
                    arguments["snapshot_id"] = self._grounding["snapshot_id"]
                if arguments.get("ref") == "__LAB_REF__":
                    arguments["ref"] = self._grounding["ref"]
        await super().create_response()


class VisualLabAdapter(FakeRealtimeAdapter):
    def __init__(self, scenario: dict | None = None):
        super().__init__([copy.deepcopy(scenario or VISUAL_SCENARIO)], pace_s=0)
        self._grounding: dict | None = None
        self.observation: VisualObservation | None = None

    async def send_tool_result(
        self,
        call_id: str,
        output: str,
        model_observation=None,
        visual_observation=None,
    ) -> None:
        await super().send_tool_result(
            call_id,
            output,
            model_observation=model_observation,
            visual_observation=visual_observation,
        )
        if visual_observation is not None:
            self.observation = visual_observation
            self._grounding = visual_grounding_arguments(visual_observation)

    async def create_response(self) -> None:
        if (
            self._pending_input is None
            and self._active is not None
            and self._grounding is not None
            and self._cursor < len(self._active["segments"])
        ):
            segment = self._active["segments"][self._cursor]
            for tool in segment.get("tools", []):
                arguments = tool.get("arguments", {})
                if arguments.get("grounding") == "__LAB_VISUAL_GROUNDING__":
                    arguments["grounding"] = self._grounding
        await super().create_response()


def build_vertical_app(
    cfg: Config,
    *,
    scenario: str = "control",
    model_mode: str = "scripted",
) -> ConnApp:
    if scenario not in VERTICAL_SCENARIOS:
        raise ValueError("lab vertical scenario is invalid")
    if model_mode not in {"scripted", "live"}:
        raise ValueError("lab model mode is invalid")
    registry = build_registry()
    context = ExecutionContext(
        cfg=cfg,
        screenshot_dir=cfg.data_dir / "screenshots" / new_id("lab"),
        ax=None,
    )
    harness = ToolHarness(registry, cfg, context)
    if model_mode == "live":
        from conn.prompt import INSTRUCTIONS
        from conn.realtime.openai_ws import OpenAIRealtimeAdapter

        adapter = OpenAIRealtimeAdapter(
            cfg,
            export_openai(registry),
            INSTRUCTIONS,
        )
    elif scenario == "control":
        adapter = GroundedLabAdapter()
    elif scenario == "menu":
        adapter = FakeRealtimeAdapter([copy.deepcopy(MENU_SCENARIO)], pace_s=0)
    elif scenario == "visual":
        adapter = VisualLabAdapter()
    elif scenario == "firefox_visual":
        visual_scenario = copy.deepcopy(VISUAL_SCENARIO)
        visual_scenario.update({
            "id": "lab-firefox-visual",
            "match": ["play the video in firefox"],
            "spoken": "Play the video in Firefox",
        })
        adapter = VisualLabAdapter(visual_scenario)
    elif scenario == "firefox_open":
        adapter = FakeRealtimeAdapter(
            [copy.deepcopy(FIREFOX_OPEN_SCENARIO)],
            pace_s=0,
        )
    elif scenario == "safari_local":
        adapter = FakeRealtimeAdapter(
            [copy.deepcopy(SAFARI_LOCAL_SCENARIO)],
            pace_s=0,
        )
    elif scenario == "safari_tab":
        adapter = FakeRealtimeAdapter(
            [copy.deepcopy(SAFARI_TAB_SCENARIO)],
            pace_s=0,
        )
    elif scenario == "firefox_local":
        adapter = FakeRealtimeAdapter(
            [copy.deepcopy(FIREFOX_LOCAL_SCENARIO)],
            pace_s=0,
        )
    elif scenario == "firefox_space":
        adapter = FakeRealtimeAdapter(
            [copy.deepcopy(FIREFOX_SPACE_SCENARIO)],
            pace_s=0,
        )
    elif scenario == "notes_create":
        adapter = FakeRealtimeAdapter(
            [copy.deepcopy(NOTES_CREATE_SCENARIO)],
            pace_s=0,
        )
    elif scenario == "notes_type":
        adapter = GroundedLabAdapter(NOTES_TYPE_SCENARIO)
    elif scenario == "notes_select":
        adapter = FakeRealtimeAdapter(
            [copy.deepcopy(NOTES_SELECT_SCENARIO)],
            pace_s=0,
        )
    elif scenario == "notes_observe":
        adapter = VisualLabAdapter(NOTES_OBSERVE_SCENARIO)
    return ConnApp(cfg, adapter, harness)


def vertical_command(scenario: str, *, model_mode: str) -> str:
    if scenario not in VERTICAL_SCENARIOS:
        raise ValueError("lab vertical scenario is invalid")
    if model_mode not in {"scripted", "live"}:
        raise ValueError("lab model mode is invalid")
    if scenario == "control" and model_mode == "live":
        return "Click Continue in the current window"
    if scenario == "firefox_visual" and model_mode == "live":
        return "Click the visible Play button in Firefox"
    return _VERTICAL_COMMANDS.get(scenario, LAB_COMMAND)


def summarize_vertical(
    *,
    trace_events: list[dict],
    truth_events: list[dict],
    tool_outputs: list[dict],
    expected_effect: str = "control_changed",
    expected_value: str | None = "on",
) -> dict:
    transactions = [
        event for event in trace_events
        if event.get("kind") == "action_transaction"
    ]
    receipt = tool_outputs[-1] if tool_outputs else {}
    effect_events = [
        event for event in truth_events
        if event.get("effect") == expected_effect
        and (expected_value is None or event.get("value") == expected_value)
    ]
    oracle = {
        "verdict": "matched" if len(effect_events) == 1 else "not_matched",
        "effect": expected_effect,
        "effect_count": len(effect_events),
        "value": effect_events[0].get("value") if len(effect_events) == 1 else None,
    }
    outcome = receipt.get("outcome")
    dispatch_count = sum(
        event.get("dispatch_state") in {"dispatched", "possibly_dispatched"}
        for event in transactions
    )
    tool_families = sorted({
        event["name"]
        for event in trace_events
        if (
            event.get("kind") == "tool_proposed"
            and isinstance(event.get("name"), str)
        )
    })
    return {
        "machine_receipt": receipt or None,
        "independent_oracle": oracle,
        "transaction_count": len(transactions),
        "dispatch_count": dispatch_count,
        "tool_families": tool_families,
        "passed": (
            outcome == "verified"
            and oracle["verdict"] == "matched"
            and len(transactions) == 1
            and dispatch_count == 1
        ),
    }


def action_result_recorded(events: list[dict]) -> bool:
    if any(event.get("kind") == "action_transaction" for event in events):
        return True
    for event in events:
        if event.get("kind") != "tool_result":
            continue
        output = event.get("output")
        if not isinstance(output, str) or len(output) > 64_000:
            continue
        try:
            payload = json.loads(output)
        except ValueError:
            continue
        if (
            isinstance(payload, dict)
            and isinstance(payload.get("outcome"), str)
            and isinstance(payload.get("dispatch_state"), str)
        ):
            return True
    return False


async def _wait_until(
    predicate: Callable[[], bool],
    *,
    timeout_s: float,
    reason: str,
) -> None:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if predicate():
            return
        await asyncio.sleep(0.05)
    raise TimeoutError(reason)


async def _wait_for_server(host: str, port: int, timeout_s: float) -> None:
    async def can_connect() -> bool:
        try:
            reader, writer = await asyncio.open_connection(host, port)
        except OSError:
            return False
        writer.close()
        await writer.wait_closed()
        return True

    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if await can_connect():
            return
        await asyncio.sleep(0.05)
    raise TimeoutError("lab_server_not_ready")


def _tool_outputs(events: list[dict]) -> list[dict]:
    outputs = []
    for event in events:
        if event.get("kind") != "tool_result":
            continue
        artifact_path = event.get("output_artifact")
        if not isinstance(artifact_path, str):
            continue
        try:
            wrapper = json.loads(Path(artifact_path).read_text())
        except (OSError, ValueError):
            continue
        output = wrapper.get("output")
        if isinstance(output, dict):
            outputs.append(output)
    return outputs


def _truth_events(path: Path) -> list[dict]:
    if not path.exists():
        return []
    events = []
    for line in path.read_text().splitlines():
        try:
            value = json.loads(line)
        except ValueError:
            continue
        if isinstance(value, dict):
            events.append(value)
    return events


async def run_vertical(
    *,
    artifact_dir: Path,
    truth_log: Path,
    input_mode: str = "typed",
    audio_file: Path | None = None,
    scenario: str = "control",
    model_mode: str = "scripted",
    timeout_s: float = 30,
) -> dict:
    from conn.server.http import serve

    artifact_dir.mkdir(parents=True, exist_ok=True)
    cfg = load_config()
    app = build_vertical_app(
        cfg,
        scenario=scenario,
        model_mode=model_mode,
    )
    shutdown = asyncio.Event()
    await app.start()
    server_task = asyncio.create_task(serve(app, shutdown))
    try:
        await _wait_for_server(cfg.server.host, cfg.server.port, timeout_s)
        (artifact_dir / "daemon-ready.json").write_text(json.dumps({
            "session_id": app.session_id,
            "port": cfg.server.port,
        }))
        await _wait_until(
            lambda: app.ax_bridge.app_present,
            timeout_s=timeout_s,
            reason="signed_app_not_connected",
        )
        await _wait_until(
            lambda: app.navigation.public_snapshot()["active"],
            timeout_s=timeout_s,
            reason="navigation_grant_not_active",
        )
        if input_mode == "typed":
            command = vertical_command(
                scenario,
                model_mode=model_mode,
            )
            await app.on_text(command)
        elif input_mode == "audio" and audio_file is not None:
            await inject_scripted_audio(app, audio_file)
        else:
            raise ValueError("lab input mode is invalid")
        await _wait_until(
            lambda: (
                app.machine.phase is Phase.DONE
                and (
                    isinstance(app.adapter, VisualLabAdapter)
                    and app.adapter.observation is not None
                    if scenario == "notes_observe"
                    else action_result_recorded(app.trace.read())
                )
            ),
            timeout_s=timeout_s,
            reason="vertical_transaction_not_complete",
        )
        events = app.trace.read()
        if (
            scenario in {"visual", "firefox_visual", "notes_observe"}
            and isinstance(app.adapter, VisualLabAdapter)
            and app.adapter.observation is not None
        ):
            prefix = "data:image/jpeg;base64,"
            encoded = app.adapter.observation.image_data_url.removeprefix(prefix)
            (artifact_dir / "before.jpg").write_bytes(
                base64.b64decode(encoded, validate=True)
            )
        summary = summarize_vertical(
            trace_events=events,
            truth_events=_truth_events(truth_log),
            tool_outputs=_tool_outputs(events),
            expected_effect=(
                "window_created"
                if scenario == "menu"
                else "playback_changed"
                if scenario in {"visual", "firefox_visual"}
                else "control_changed"
            ),
            expected_value=(
                None
                if scenario == "menu"
                else "pause"
                if scenario in {"visual", "firefox_visual"}
                else "on"
            ),
        )
        summary.update({
            "session_id": app.session_id,
            "trace_path": str(app.trace.path),
            "cost": app.cost.receipt(),
            "input_mode": input_mode,
            "scenario": scenario,
            "model_mode": model_mode,
        })
        (artifact_dir / "vertical-result.json").write_text(
            json.dumps(summary, indent=2, sort_keys=True)
        )
        return summary
    finally:
        shutdown.set()
        await server_task
        await app.stop()


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m conn.lab.vertical")
    parser.add_argument("--artifact-dir", type=Path, required=True)
    parser.add_argument("--truth-log", type=Path, required=True)
    parser.add_argument(
        "--input-mode",
        choices=("typed", "audio"),
        default="typed",
    )
    parser.add_argument("--audio-file", type=Path)
    parser.add_argument(
        "--scenario",
        choices=VERTICAL_SCENARIOS,
        default="control",
    )
    parser.add_argument(
        "--model-mode",
        choices=("scripted", "live"),
        default="scripted",
    )
    parser.add_argument("--timeout", type=float, default=30)
    args = parser.parse_args()
    try:
        result = asyncio.run(run_vertical(
            artifact_dir=args.artifact_dir,
            truth_log=args.truth_log,
            input_mode=args.input_mode,
            audio_file=args.audio_file,
            scenario=args.scenario,
            model_mode=args.model_mode,
            timeout_s=args.timeout,
        ))
    except Exception as error:
        print(json.dumps({
            "ok": False,
            "error": f"{type(error).__name__}:{error}",
        }))
        raise
    print(json.dumps({"ok": bool(result["passed"]), "result": result}))


if __name__ == "__main__":
    main()
