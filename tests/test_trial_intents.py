"""Daemon side of the 2026-11-12 voice-trial fixes: a witness for opening an
Obsidian note, launch-length verification for direct navigation, and the
zoom and close-tabs intents with their gates, guards, and spoken outcomes."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from conn.actions import ActionOutcome, ActionReceipt, DispatchState
from conn.events import Gate
from conn.navigation import NavigationLease
from conn.prompt import INSTRUCTIONS
from conn.tools.native_actions import compile_action_request
from conn.tools.registry import build_registry, export_openai
from conn.tools.risk import RiskLevel, gate_for_prepared


def _compile(harness, name: str, args: dict) -> dict:
    return compile_action_request(harness.registry[name], args, harness.cfg)


class TestObsidianNoteWitness:
    def test_existing_note_carries_the_title_obsidian_will_show(self, harness):
        vault = Path(harness.cfg.phoenix.vault_root)
        (vault / "research").mkdir()
        (vault / "research" / "notebook.md").write_text("# notes\n")

        request = _compile(harness, "phoenix_open_note",
                           {"path": "research/notebook.md"})

        assert request["operation"] == "open_url"
        assert request["payload"] == {
            "url": "obsidian://open?vault=phoenix&file=research/notebook.md",
            "witness_bundle_id": "md.obsidian",
            "witness_window_title_prefix": "notebook - phoenix - Obsidian",
        }
        assert request["timeout_ms"] == harness.cfg.actions.launch_verify_ms

    def test_extensionless_path_uses_the_markdown_note_basename(self, harness):
        vault = Path(harness.cfg.phoenix.vault_root)
        (vault / "v1.2 plan.md").write_text("plan\n")

        payload = _compile(harness, "phoenix_open_note",
                           {"path": "v1.2 plan"})["payload"]

        assert payload["witness_window_title_prefix"] == (
            "v1.2 plan - phoenix - Obsidian")

    def test_missing_note_gets_no_witness_and_stays_unverifiable(self, harness):
        payload = _compile(harness, "phoenix_open_note",
                           {"path": "nowhere/ghost.md"})["payload"]

        assert set(payload) == {"url"}

    def test_witness_needs_a_configured_obsidian_bundle(self, harness):
        vault = Path(harness.cfg.phoenix.vault_root)
        (vault / "a.md").write_text("a\n")
        harness.cfg.apps.bundle_ids = {"Safari": "com.apple.Safari"}

        payload = _compile(harness, "phoenix_open_note", {"path": "a.md"})["payload"]

        assert "witness_bundle_id" not in payload


def test_browser_navigate_waits_long_enough_for_a_page_to_commit(harness):
    request = _compile(harness, "browser_navigate",
                       {"url": "https://example.com", "browser_scope": "Safari"})

    assert request["timeout_ms"] == harness.cfg.actions.launch_verify_ms


class TestZoomIntent:
    def test_compiles_to_a_goal_slot_intent(self, harness):
        request = _compile(harness, "computer_zoom",
                           {"direction": "out", "steps": 3, "app": "Safari"})

        assert request["operation"] == "semantic_intent"
        assert request["payload"] == {
            "family": "zoom", "direction": "out", "steps": 3,
            "app_name": "Safari", "bundle_id_hint": "com.apple.Safari",
        }
        assert request["risk"] == "act_low"
        assert "desired_effect" not in request

    def test_is_reversible_and_never_asks_for_approval(self, harness):
        spec = harness.registry["computer_zoom"]
        assert spec.risk is RiskLevel.ACT_LOW
        lease = NavigationLease("session-a")
        lease.bind_connection("app-a")
        lease.grant("session-a", "app-a")
        plan = {"preview": "Zoom out 3 steps", "effect_class": "reversible_navigation",
                "navigation_generation": lease.generation}

        gate, reason, preview = gate_for_prepared(
            "computer_zoom", spec.risk, {"direction": "out", "steps": 3},
            plan, harness.cfg, lease)

        assert (gate, reason, preview) == (Gate.AUTO, None, "Zoom out 3 steps")

    @pytest.mark.parametrize("args", [
        {"direction": "out", "steps": 6},
        {"direction": "out", "steps": 0},
        {"direction": "sideways"},
        {"steps": 2},
    ])
    def test_schema_refuses_out_of_range_or_missing_slots(self, harness, args):
        call = harness.gate("zoom", "computer_zoom", json.dumps(args))

        assert call.gate is Gate.BLOCKED
        assert call.block_reason.startswith("invalid_arguments")


class TestCloseTabsIntent:
    def test_position_and_count_compile_to_slots(self, harness):
        request = _compile(harness, "computer_close_tabs",
                           {"position": "first", "count": 2})

        assert request["payload"] == {
            "family": "close_tabs", "position": "first", "count": 2,
        }
        assert request["risk"] == "act_confirm"

    def test_title_compiles_to_a_named_target(self, harness):
        request = _compile(harness, "computer_close_tabs", {"title": "Example"})

        assert request["payload"] == {"family": "close_tabs", "target_name": "Example"}

    @pytest.mark.parametrize("args,reason", [
        ({}, "close_tabs_needs_position_or_title"),
        ({"position": "first", "title": "Example"},
         "close_tabs_needs_position_or_title"),
        ({"title": "Example", "count": 2}, "close_tabs_count_needs_position"),
        ({"position": "current", "count": 2}, "close_tabs_current_is_one_tab"),
    ])
    def test_guard_refuses_ambiguous_selections(self, harness, args, reason):
        call = harness.gate("close", "computer_close_tabs", json.dumps(args))

        assert call.gate is Gate.BLOCKED
        assert call.block_reason == reason

    def test_consequential_close_waits_for_a_pointer_click_even_with_navigation_on(
        self, harness
    ):
        spec = harness.registry["computer_close_tabs"]
        lease = NavigationLease("session-a")
        lease.bind_connection("app-a")
        lease.grant("session-a", "app-a")
        plan = {"preview": "Close 2 tabs: Example, Docs",
                "effect_class": "consequential",
                "navigation_generation": lease.generation}

        gate, reason, preview = gate_for_prepared(
            "computer_close_tabs", spec.risk, {"position": "first", "count": 2},
            plan, harness.cfg, lease)

        assert (gate, reason) == (Gate.CONFIRM, None)
        assert preview == "Close 2 tabs: Example, Docs"

    def test_without_navigation_control_it_still_needs_approval(self, harness):
        spec = harness.registry["computer_close_tabs"]
        plan = {"preview": "Close tab: Example"}

        gate, _reason, _preview = gate_for_prepared(
            "computer_close_tabs", spec.risk, {"title": "Example"}, plan, harness.cfg)

        assert gate is Gate.CONFIRM

    def test_a_destructive_native_class_is_still_refused(self, harness):
        spec = harness.registry["computer_close_tabs"]
        lease = NavigationLease("session-a")
        lease.bind_connection("app-a")
        lease.grant("session-a", "app-a")
        plan = {"preview": "Close window", "effect_class": "destructive",
                "navigation_generation": lease.generation}

        gate, reason, _ = gate_for_prepared(
            "computer_close_tabs", spec.risk, {"position": "current"},
            plan, harness.cfg, lease)

        assert (gate, reason) == (Gate.BLOCKED, "destructive_effect")


def test_model_surface_names_goals_not_mechanisms():
    tools = {tool["name"]: tool for tool in export_openai(build_registry())}

    for name in ("computer_zoom", "computer_close_tabs"):
        properties = tools[name]["parameters"]["properties"]
        assert not {"path", "menu_path", "combo", "keys", "desired_effect"} & set(properties)


@pytest.mark.parametrize("reason,message", [
    ("effect_already_satisfied", "That is already the case."),
    ("partial_dispatch", "Only part of that went through. Check before retrying."),
    ("zoom_limit_reached", "Zoom is already at its limit."),
    ("not_enough_tabs", "There are not that many tabs open."),
    ("no_matching_tab", "I can't find a tab with that name."),
])
def test_new_failure_reasons_have_plain_spoken_messages(reason, message):
    dispatch = (DispatchState.DISPATCHED if reason == "partial_dispatch"
                else DispatchState.NOT_DISPATCHED)
    receipt = ActionReceipt(
        outcome=ActionOutcome.FAILED, dispatch_state=dispatch, strategy="none",
        lane="semantic", target="tabs", effect="none", evidence=(),
        retry_safe=dispatch is DispatchState.NOT_DISPATCHED, duration_ms=0,
        reason_code=reason,
    )

    assert receipt.safe_user_message() == message


def test_refusing_to_close_the_window_says_why():
    receipt = ActionReceipt(
        outcome=ActionOutcome.BLOCKED, dispatch_state=DispatchState.NOT_DISPATCHED,
        strategy="none", lane="semantic", target="tabs", effect="none",
        evidence=(), retry_safe=True, duration_ms=0,
        reason_code="would_close_window",
    )

    assert receipt.safe_user_message() == (
        "That would close the whole window, so I left it open.")


def test_prompt_routes_zoom_and_tab_closing_but_keeps_destructive_refusal():
    assert "Use computer_zoom to zoom in, out, or back to actual size" in INSTRUCTIONS
    assert "computer_close_tabs to close tabs by position or title" in INSTRUCTIONS
    assert "closing tabs is not one of them" in INSTRUCTIONS
    assert "Delete, remove, close without saving, and overwrite" in INSTRUCTIONS


def test_corpus_pins_the_trial_intents():
    corpus = json.loads(
        (Path(__file__).parents[1] / "evals" / "intent_corpus.json").read_text())
    items = {item["utterance"]: item["expect"] for item in corpus["items"]}

    assert items["Open my note called weekly review"]["tool_any"] == [
        "phoenix_search", "phoenix_open_note"]
    zoom_out = items["Can you zoom out a few times so I can read the whole thing?"]
    assert zoom_out["tool_any"] == ["computer_zoom"]
    assert zoom_out["slots"]["direction"] == "out"
    assert items["Zoom in twice"]["slots"] == {"direction": "in", "steps": 2}
    assert items["Close this tab"]["slots"] == {"position": "current"}
    assert items["Can you close the first two tabs now?"]["slots"] == {
        "position": "first", "count": 2}
    refusal = items["Close the document without saving"]
    assert refusal["allow_no_tool"] is True
    assert refusal["speech_equals"] == "I can't help with destructive actions yet."
