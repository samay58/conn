"""Apple Shortcuts runner: every run waits for approval, the name must match
a real Shortcut, the Shortcut never sees Conn's secrets, a slow Shortcut is
left running rather than killed, and a finished run claims only that it ran.
"""

from __future__ import annotations

import asyncio
import dataclasses
import json
import os
import subprocess
from unittest.mock import patch

import pytest

from conn.events import Gate
from conn.tools import shortcuts
from conn.tools.base import ToolError
from conn.tools.registry import build_registry, export_openai
from conn.tools.risk import RiskLevel

NAMES = ["Morning Routine", "Log Water", "Dark Mode", "dark mode", "Focus Mode On"]


class FakeProcess:
    def __init__(self, *, returncode=0, stderr="", output=None, hang=False, argv=None):
        self.returncode = returncode
        self._stderr = stderr
        self._output = output
        self._hang = hang
        self.argv = argv or []
        self.killed = False

    def communicate(self, timeout=None):
        if self._hang:
            raise subprocess.TimeoutExpired(self.argv, timeout)
        if self._output is not None:
            path = self.argv[self.argv.index("--output-path") + 1]
            with open(path, "wb") as handle:
                handle.write(self._output)
        return None, self._stderr

    def kill(self):
        self.killed = True

    terminate = kill


def run_with(ctx, args, **process):
    calls = {}

    def popen(argv, **kwargs):
        calls["argv"] = argv
        calls["env"] = kwargs.get("env")
        if "--input-path" in argv:
            with open(argv[argv.index("--input-path") + 1]) as handle:
                calls["input"] = handle.read()
        calls["process"] = FakeProcess(argv=argv, **process)
        return calls["process"]

    with patch.object(shortcuts, "list_names", return_value=NAMES), \
         patch.object(shortcuts.subprocess, "Popen", side_effect=popen):
        result = shortcuts.shortcuts_run(args, ctx)
    return result, calls


def gate(harness, name, args):
    return harness.gate("c1", name, json.dumps(args))


class TestRegistry:
    def test_run_needs_approval_and_is_not_a_native_mutation(self):
        spec = build_registry()["shortcuts_run"]
        assert spec.risk is RiskLevel.ACT_CONFIRM
        assert spec.computer_mutation is False
        assert spec.timeout_s > 30  # above the longest allowed run wait

    def test_both_tools_reach_the_model(self):
        exported = {tool["name"] for tool in export_openai(build_registry())}
        assert {"shortcuts_list", "shortcuts_run"} <= exported
        assert build_registry()["shortcuts_list"].risk is RiskLevel.READ


class TestGate:
    def test_run_waits_for_a_chip_that_shows_the_input(self, harness):
        call = gate(harness, "shortcuts_run", {"name": "Log Water", "input": "500 ml"})
        assert call.gate is Gate.CONFIRM
        assert call.preview == "Shortcut: Log Water with 500 ml"

    @pytest.mark.parametrize("args,reason", [
        ({"name": "  "}, "shortcut_name_missing"),
        ({"name": "Log\nWater"}, "shortcut_name_invalid"),
        ({"name": "x" * 201}, "shortcut_name_invalid"),
        ({"name": "Log Water", "input": "x" * 4001}, "shortcut_input_too_large"),
    ])
    def test_bad_arguments_are_blocked_before_any_chip(self, harness, args, reason):
        call = gate(harness, "shortcuts_run", args)
        assert call.gate is Gate.BLOCKED
        assert reason in (call.block_reason or "")

    def test_config_switch_turns_both_tools_off(self, harness, cfg):
        cfg.shortcuts.enabled = False
        for name, args in (("shortcuts_run", {"name": "Log Water"}), ("shortcuts_list", {})):
            call = gate(harness, name, args)
            assert call.gate is Gate.BLOCKED
            assert "shortcuts_disabled_in_config" in (call.block_reason or "")


class TestResolveName:
    def test_exact_name_wins_over_case_variants(self):
        assert shortcuts.resolve_name("dark mode", NAMES) == "dark mode"

    def test_single_case_insensitive_match_resolves(self):
        assert shortcuts.resolve_name("log water", NAMES) == "Log Water"

    def test_two_case_variants_are_ambiguous(self):
        with pytest.raises(ToolError, match="shortcut_ambiguous"):
            shortcuts.resolve_name("DARK MODE", NAMES)

    def test_unknown_name_names_the_closest(self):
        with pytest.raises(ToolError, match="shortcut_not_found.*Closest: Morning Routine"):
            shortcuts.resolve_name("Morning Routin", NAMES)


class TestListNames:
    def test_lines_are_trimmed_and_deduplicated(self):
        proc = subprocess.CompletedProcess([], 0, stdout="A\n  B \n\nA\n", stderr="")
        with patch.object(shortcuts.subprocess, "run", return_value=proc):
            assert shortcuts.list_names() == ["A", "B"]

    def test_cli_failure_is_a_clear_error(self):
        proc = subprocess.CompletedProcess([], 1, stdout="", stderr="no access")
        with patch.object(shortcuts.subprocess, "run", return_value=proc):
            with pytest.raises(ToolError, match="shortcuts_unavailable: no access"):
                shortcuts.list_names()


class TestRun:
    def test_finished_run_reports_only_that_it_ran_plus_output(self, ctx):
        result, calls = run_with(ctx, {"name": "log water", "input": "500 ml"},
                                 output=b"Logged 500 ml")
        assert calls["argv"][:3] == [shortcuts.SHORTCUTS_BIN, "run", "Log Water"]
        assert calls["input"] == "500 ml"
        assert result == {
            "shortcut": "Log Water",
            "status": "finished",
            "safe_user_message": "Ran Log Water.",
            "output": "Logged 500 ml",
        }

    def test_shortcut_never_sees_conn_secrets(self, ctx):
        secrets = {"OPENAI_API_KEY": "k", "CONN_BRIDGE_TOKEN": "t",
                   "CONN_CONSOLE_CAPABILITY": "c", "HOME": "/Users/test"}
        with patch.dict(os.environ, secrets):
            _result, calls = run_with(ctx, {"name": "Dark Mode"})
        assert calls["env"]["HOME"] == "/Users/test"
        for key in ("OPENAI_API_KEY", "CONN_BRIDGE_TOKEN", "CONN_CONSOLE_CAPABILITY"):
            assert key not in calls["env"]

    def test_slow_shortcut_is_left_running_not_killed(self, ctx):
        result, calls = run_with(ctx, {"name": "Morning Routine"}, hang=True)
        assert result["status"] == "still_running"
        assert result["safe_user_message"] == "Morning Routine is still running."
        assert calls["process"].killed is False

    def test_failed_shortcut_is_an_error_not_a_success(self, ctx):
        with pytest.raises(ToolError, match="shortcut_failed: Dark Mode: boom"):
            run_with(ctx, {"name": "Dark Mode"}, returncode=1, stderr="boom")

    def test_long_and_binary_output_is_bounded(self, ctx):
        result, _ = run_with(ctx, {"name": "Dark Mode"}, output=b"x" * 5000)
        assert len(result["output"]) == shortcuts.OUTPUT_MAX_CHARS + 1
        result, _ = run_with(ctx, {"name": "Dark Mode"}, output=b"\xff\xfe\x00")
        assert result["output"] == "[non-text output, 3 bytes]"

    def test_unknown_name_never_starts_a_process(self, ctx):
        with patch.object(shortcuts, "list_names", return_value=NAMES), \
             patch.object(shortcuts.subprocess, "Popen") as popen:
            with pytest.raises(ToolError, match="shortcut_not_found"):
                shortcuts.shortcuts_run({"name": "Launch Missiles"}, ctx)
        popen.assert_not_called()


class TestHarnessEnvelope:
    def test_approved_run_returns_an_ok_envelope_with_the_receipt(self, harness, ctx):
        call = gate(harness, "shortcuts_run", {"name": "Log Water"})
        call = dataclasses.replace(call, gate=Gate.AUTO)
        with patch.object(shortcuts, "list_names", return_value=NAMES), \
             patch.object(shortcuts.subprocess, "Popen",
                          side_effect=lambda argv, **kw: FakeProcess(argv=argv)):
            finished = asyncio.run(harness.run(call))
        envelope = json.loads(finished.output)
        assert finished.ok is True
        assert envelope["data"]["safe_user_message"] == "Ran Log Water."


class TestSerialization:
    """A Shortcut run takes the turn's single action slot, like a native
    action, and closes the chain once it resolves: nothing verified it."""

    @staticmethod
    def machine():
        from conn.state import SessionStateMachine
        from conn.tools.registry import computer_mutation_names
        return SessionStateMachine(
            computer_mutations=computer_mutation_names(build_registry()),
            local_actions=frozenset({"shortcuts_run"}),
        )

    @staticmethod
    def proposed(call_id, name, gate):
        from conn.events import ToolCall, ToolProposed
        return ToolProposed(call=ToolCall(
            call_id=call_id, name=name, arguments={"name": "Log Water"},
            gate=gate, preview=name))

    @staticmethod
    def start(m):
        from conn.events import PttDown, PttUp
        m.handle(PttDown(ts_ms=1000))
        m.handle(PttUp(ts_ms=2000))

    def test_second_action_in_the_same_response_is_refused(self):
        from conn.state import CallStatus
        m = self.machine()
        self.start(m)
        m.handle(self.proposed("c1", "shortcuts_run", Gate.CONFIRM))
        m.handle(self.proposed("c2", "app_open", Gate.AUTO))
        assert m.ledger["c1"].status is CallStatus.PROPOSED
        assert m.ledger["c2"].status is CallStatus.BLOCKED
        assert "sequential_action_required" in m.ledger["c2"].output

    def test_finished_run_closes_the_chain_for_the_turn(self):
        from conn.events import ApprovalDecision, ResponseDone, ToolFinished
        from conn.state import CallStatus
        m = self.machine()
        self.start(m)
        m.handle(self.proposed("c1", "shortcuts_run", Gate.CONFIRM))
        m.handle(ResponseDone(had_tool_calls=True))
        m.handle(ApprovalDecision(call_id="c1", approved=True))
        running = m.ledger["c1"].call
        m.handle(ToolFinished(
            call_id="c1", ok=True, output='{"ok": true}',
            turn_id=running.turn_id, response_epoch=running.response_epoch,
            observation_epoch=running.observation_epoch,
            execution_id=running.execution_id,
        ))
        assert m.ledger["c1"].status is CallStatus.COMPLETED
        m.handle(self.proposed("c2", "app_open", Gate.AUTO))
        assert m.ledger["c2"].status is CallStatus.BLOCKED
        assert "mutation_chain_closed" in m.ledger["c2"].output
