import json
import asyncio

import pytest

from conn.config import Config
from conn.events import Gate
from conn.tools.registry import build_registry, export_openai
from conn.tools.risk import RiskLevel, gate_for


def gate(harness, name, args):
    return harness.gate("c1", name, json.dumps(args))


class TestGateDecisions:
    @pytest.mark.parametrize(
        "name,args,expected",
        [
            ("computer_get_context", {}, Gate.AUTO),
            ("computer_screenshot", {}, Gate.AUTO),
            ("phoenix_search", {"query": "transformer paper"}, Gate.AUTO),
            ("wait_for_user", {}, Gate.AUTO),
            ("app_open", {"app": "Obsidian"}, Gate.AUTO),
            ("browser_search", {"query": "openai docs"}, Gate.AUTO),
            ("clipboard_set", {"text": "hello"}, Gate.AUTO),
            ("computer_ax_snapshot", {}, Gate.AUTO),
            ("computer_hotkey", {"combo": "cmd+s"}, Gate.BLOCKED),
            ("app_focus_tab", {"title": "Inbox"}, Gate.AUTO),
            ("app_menu", {"path": ["File", "Close"]}, Gate.CONFIRM),
        ],
    )
    def test_static_levels(self, harness, name, args, expected):
        assert gate(harness, name, args).gate is expected

    def test_confirm_allowlisted_hotkey_gates_confirm(self, harness, cfg):
        cfg.hotkeys.confirm = ["cmd+t", "cmd+w", "cmd+n"]
        call = gate(harness, "computer_hotkey", {"combo": "cmd+t"})
        assert call.gate is Gate.CONFIRM

    def test_meta_alias_matches_cmd_allowlist_entry(self, harness, cfg):
        # Both sides of the comparison normalize, so the model's "meta+t"
        # matches an allowlist written as "cmd+t".
        cfg.hotkeys.confirm = ["cmd+t"]
        call = gate(harness, "computer_hotkey", {"combo": "meta+t"})
        assert call.gate is Gate.CONFIRM
        assert call.preview == "Press keys: cmd+t"

    def test_hotkey_refusal_names_the_allowlist(self, harness, cfg):
        cfg.hotkeys.confirm = ["cmd+t", "cmd+w"]
        call = gate(harness, "computer_hotkey", {"combo": "cmd+s"})
        assert call.gate is Gate.BLOCKED
        reason = harness.block_reason(call)
        assert "hotkey_not_allowlisted" in reason
        assert "cmd+t, cmd+w" in reason
        assert "app_menu" in reason

    def test_hotkey_refusal_with_empty_allowlist_says_none(self, harness):
        call = gate(harness, "computer_hotkey", {"combo": "cmd+s"})
        reason = harness.block_reason(call)
        assert "Allowed: none" in reason

    def test_app_not_on_allowlist_is_blocked(self, harness):
        call = gate(harness, "app_open", {"app": "Disk Utility"})
        assert call.gate is Gate.BLOCKED
        assert "app_not_allowlisted" in harness.block_reason(call)

    def test_present_only_allowlist_blocks_named_optional_app(self, harness):
        call = gate(harness, "app_focus_tab", {"title": "Inbox", "app": "Disk Utility"})
        assert call.gate is Gate.BLOCKED
        assert "app_not_allowlisted" in harness.block_reason(call)

    def test_path_escape_is_blocked(self, harness):
        call = gate(harness, "phoenix_open_note", {"path": "../../etc/hosts"})
        assert call.gate is Gate.BLOCKED
        assert "path_outside_vault" in harness.block_reason(call)

    def test_vault_path_is_allowed(self, harness):
        call = gate(harness, "phoenix_open_note", {"path": "01-active/tasks.md"})
        assert call.gate is Gate.AUTO

    def test_oversized_clipboard_is_blocked(self, harness):
        call = gate(harness, "clipboard_set", {"text": "x" * 100_001})
        assert call.gate is Gate.BLOCKED
        assert "clipboard_payload_too_large" in harness.block_reason(call)

    def test_unknown_tool_is_blocked(self, harness):
        call = harness.gate("c1", "shell.exec", '{"cmd": "rm -rf /"}')
        assert call.gate is Gate.BLOCKED
        assert "unknown_tool" in harness.block_reason(call)

    def test_malformed_json_is_blocked(self, harness):
        call = harness.gate("c1", "app_open", "{not json")
        assert call.gate is Gate.BLOCKED

    def test_missing_required_arg_is_blocked(self, harness):
        call = harness.gate("c1", "app_open", "{}")
        assert call.gate is Gate.BLOCKED
        assert "invalid_arguments" in harness.block_reason(call)

    @pytest.mark.parametrize(
        "arguments",
        [
            {"snapshot_id": "s", "ref": "r", "direction": "sideways", "amount": 1},
            {"snapshot_id": "s", "ref": "r", "direction": "down", "amount": 0},
            {"snapshot_id": "s", "ref": "r", "direction": "down", "amount": 11},
        ],
    )
    def test_scroll_schema_enforces_direction_and_amount_bounds(self, harness, arguments):
        call = gate(harness, "computer_scroll", arguments)

        assert call.gate is Gate.BLOCKED
        assert "invalid_arguments" in harness.block_reason(call)

    def test_scroll_direction_and_amount_must_be_supplied_together(self, harness):
        call = gate(harness, "computer_scroll", {
            "snapshot_id": "s", "ref": "r", "direction": "down"
        })

        assert call.gate is Gate.BLOCKED
        assert "required_together" in harness.block_reason(call)

    def test_wrong_arg_type_is_blocked(self, harness):
        call = gate(harness, "phoenix_search", {"query": 42})
        assert call.gate is Gate.BLOCKED


class TestPreviewBudget:
    """Chip previews fit the island whole: bounded lambdas at the source, a
    hard clamp in the harness as the safety net, never a mid-word cut."""

    def test_clipboard_preview_is_fixed_copy(self, harness):
        call = gate(harness, "clipboard_set", {"text": "x" * 500})
        assert call.preview == "Copy to clipboard"

    def test_long_query_clamps_at_a_word_boundary(self, harness):
        from conn.tools.harness import PREVIEW_BUDGET

        query = "transformer paper attention notes " * 20
        call = gate(harness, "browser_search", {"query": query})
        full = f"Search the web: {query}".strip()
        assert len(call.preview) <= PREVIEW_BUDGET
        assert call.preview.endswith("…")
        stem = call.preview[:-1]
        assert full.startswith(stem)
        assert full[len(stem)] == " ", "clamp cut mid-word"

    def test_unbroken_token_still_bounded(self):
        from conn.tools.harness import PREVIEW_BUDGET, clamp_preview

        clamped = clamp_preview("x" * 500)
        assert len(clamped) <= PREVIEW_BUDGET
        assert clamped.endswith("…")

    def test_within_budget_passes_through(self):
        from conn.tools.harness import clamp_preview

        assert clamp_preview("Open app: Obsidian") == "Open app: Obsidian"


class TestOverrides:
    def test_config_can_escalate_to_confirm(self, harness, cfg):
        cfg.risk_overrides["clipboard_set"] = "confirm"
        call = gate(harness, "clipboard_set", {"text": "hello"})
        assert call.gate is Gate.CONFIRM

    def test_blocked_tools_stay_blocked_even_with_config_override(self):
        gate_value, reason, preview = gate_for("imaginary_blocked", RiskLevel.BLOCKED, {}, Config(), None)
        assert gate_value is Gate.BLOCKED
        assert "tool_disabled_in_v0" in (reason or "")
        assert preview is None

    def test_config_can_block_outright(self, harness, cfg):
        cfg.risk_overrides["browser_search"] = "blocked"
        call = gate(harness, "browser_search", {"query": "x"})
        assert call.gate is Gate.BLOCKED


class TestRunFailClosed:
    def test_blocked_call_never_reaches_executor(self, harness):
        seen = {"called": False}

        def should_not_run(args, ctx):
            seen["called"] = True
            return {"unexpected": True}

        harness._executors = {"computer_hotkey": should_not_run}
        call = gate(harness, "computer_hotkey", {"combo": "cmd+s"})

        assert call.gate is Gate.BLOCKED

        result = asyncio.run(harness.run(call))
        env = json.loads(result.output)

        assert seen["called"] is False
        assert result.ok is False
        assert env["ok"] is False
        assert env["error"] == harness.block_reason(call)
        assert "duration_ms" in env


    def test_run_converts_regating_exception_to_false_envelope(self, harness):
        from conn.events import ToolCall

        call = ToolCall(
            call_id="c1",
            name="computer_hotkey",
            arguments={"combo": "cmd+shift"},
            gate=Gate.CONFIRM,
            preview="Press keys",
        )

        result = asyncio.run(harness.run(call))
        env = json.loads(result.output)

        assert result.ok is False
        assert env["ok"] is False
        assert env["error"] == "invalid_hotkey: expected exactly one primary key"


    def test_run_revalidates_arguments_before_executor(self, harness):
        from conn.events import ToolCall

        seen = {"called": False}

        def should_not_run(args, ctx):
            seen["called"] = True
            return {"unexpected": True}

        harness._executors = {"app_menu": should_not_run}
        call = ToolCall(
            call_id="c1",
            name="app_menu",
            arguments={"path": []},
            gate=Gate.CONFIRM,
            preview="Use menu",
        )

        result = asyncio.run(harness.run(call))
        env = json.loads(result.output)

        assert seen["called"] is False
        assert result.ok is False
        assert env["ok"] is False
        assert env["error"] == "invalid_arguments: argument 'path' should have at least 1 item"


class TestRegistryShape:
    def test_tool_names_match_openai_wire_pattern(self):
        import re

        pattern = re.compile(r"^[a-zA-Z0-9_-]{1,64}$")
        for name in build_registry():
            assert pattern.match(name), f"{name!r} would be rejected by the API"

    def test_every_spec_exports_valid_openai_tool(self):
        registry = build_registry()
        exported = export_openai(registry)
        assert len(exported) == len(registry)
        for tool in exported:
            assert tool["type"] == "function"
            assert tool["name"] and tool["description"]
            schema = tool["parameters"]
            assert schema["type"] == "object"
            assert set(schema["required"]).issubset(schema["properties"].keys())

    def test_grounded_registry_shape_matches_contract(self):
        registry = build_registry()
        for name in [
            "computer_ax_snapshot",
            "computer_click",
            "computer_type_text",
            "computer_scroll",
            "computer_hotkey",
            "app_focus_tab",
            "app_menu",
        ]:
            assert name in registry
        assert "computer_ax_tree" not in registry

    def test_previews_render_for_all_specs(self):
        for spec in build_registry().values():
            text = spec.preview(
                {
                    "app": "Obsidian",
                    "query": "q",
                    "text": "t",
                    "path": "p",
                    "ref": "e2",
                    "snapshot_id": "snap1234",
                    "combo": "c",
                }
            )
            assert isinstance(text, str) and text
