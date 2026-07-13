from __future__ import annotations

import argparse
import json
from types import SimpleNamespace

import pytest

from conn.config import Config
from conn.events import Gate
from conn.tools.ax import FakeAxBackend, RawNode, SnapshotStore
from conn.tools.base import ExecutionContext, ToolError
from conn.tools.harness import ToolHarness
from conn.tools.registry import build_registry, export_openai
from conn.tools.risk import RiskLevel, gate_for as risk_gate_for
from conn.tools.ax_input import FakeInputBackend


def node(role: str, title: str = "", *, frame=(0, 0, 10, 10), children=(), subrole: str = "", secure_hints=()):
    return RawNode(
        role=role,
        title=title,
        frame=frame,
        subrole=subrole,
        secure_hints=tuple(secure_hints),
        children=tuple(children),
    )


def configure_ax(cfg: Config) -> Config:
    object.__setattr__(
        cfg,
        "ax",
        SimpleNamespace(snapshot_ttl_s=10, max_elements=120, max_depth=12, deny_bundles=[]),
    )
    return cfg


def make_ctx(cfg: Config, tmp_path, tree: RawNode, *, bundle: str = "com.apple.TextEdit"):
    cfg = configure_ax(cfg)
    backend = FakeAxBackend(bundle, 42, tree)
    store = SnapshotStore(backend, cfg)
    snap = store.take()
    ctx = ExecutionContext(cfg=cfg, screenshot_dir=tmp_path / "shots", ax=store)
    harness = ToolHarness(build_registry(), cfg, ctx)
    return harness, ctx, store, backend, snap


def gate(harness: ToolHarness, name: str, args: dict):
    return harness.gate("c1", name, json.dumps(args))


def test_click_gate_defaults_to_confirm_and_enriches_preview(cfg, tmp_path):
    harness, _ctx, _store, _backend, snap = make_ctx(
        cfg,
        tmp_path,
        node("AXWindow", "Compose", children=(node("AXButton", "Send"),)),
        bundle="com.apple.mail",
    )

    call = gate(harness, "computer_click", {"snapshot_id": snap.snapshot_id, "ref": "e2"})

    assert call.gate is Gate.CONFIRM
    assert "Send" in call.preview
    assert "AXButton" in call.preview


def test_click_gate_downgrades_to_auto_for_trusted_bundle_and_role(cfg, tmp_path):
    cfg.interactions.trusted = {"com.apple.mail": ["AXButton"]}
    harness, _ctx, _store, _backend, snap = make_ctx(
        cfg,
        tmp_path,
        node("AXWindow", "Compose", children=(node("AXButton", "Send"),)),
        bundle="com.apple.mail",
    )

    call = gate(harness, "computer_click", {"snapshot_id": snap.snapshot_id, "ref": "e2"})

    assert call.gate is Gate.AUTO


def test_click_gate_blocks_with_stale_ref_when_resolution_fails(cfg, tmp_path):
    harness, _ctx, _store, backend, snap = make_ctx(
        cfg,
        tmp_path,
        node("AXWindow", "Compose", children=(node("AXButton", "Send"),)),
    )
    backend.root.children[0].title = "Actually Different"

    call = gate(harness, "computer_click", {"snapshot_id": snap.snapshot_id, "ref": "e2"})

    assert call.gate is Gate.BLOCKED
    assert call.block_reason == "stale_ref: take a new snapshot"


def test_gate_time_resolution_exceptions_degrade_to_blocked(cfg, tmp_path):
    harness, ctx, _store, _backend, snap = make_ctx(
        cfg,
        tmp_path,
        node("AXWindow", "Compose", children=(node("AXButton", "Send"),)),
    )

    class BrokenStore:
        def resolve(self, *args, **kwargs):
            raise RuntimeError("boom")

    ctx.ax = BrokenStore()

    call = gate(harness, "computer_click", {"snapshot_id": snap.snapshot_id, "ref": "e2"})

    assert call.gate is Gate.BLOCKED
    assert "boom" in (call.block_reason or "")


def test_gate_for_resolution_exception_returns_blocked_tuple(cfg, tmp_path):
    _harness, ctx, _store, backend, snap = make_ctx(
        cfg,
        tmp_path,
        node("AXWindow", "Compose", children=(node("AXButton", "Send"),)),
    )
    backend.root.children[0].title = "Changed"

    gate_value, reason, preview = risk_gate_for(
        "computer_click",
        RiskLevel.ACT_CONFIRM,
        {"snapshot_id": snap.snapshot_id, "ref": "e2"},
        cfg,
        ctx,
    )

    assert gate_value is Gate.BLOCKED
    assert reason == "stale_ref: take a new snapshot"
    assert preview is None


def test_type_text_secure_field_is_blocked_and_not_downgradable(cfg, tmp_path):
    cfg.interactions.trusted = {"com.google.Chrome": ["AXTextField", "AXSecureTextField"]}
    cfg.risk_overrides["computer_type_text"] = "auto"
    harness, _ctx, _store, _backend, snap = make_ctx(
        cfg,
        tmp_path,
        node(
            "AXWindow",
            "Login",
            children=(node("AXTextField", "Password", subrole="AXSecureTextField"),),
        ),
        bundle="com.google.Chrome",
    )

    call = gate(
        harness,
        "computer_type_text",
        {"snapshot_id": snap.snapshot_id, "ref": "e2", "text": "secret"},
    )

    assert call.gate is Gate.BLOCKED
    assert call.block_reason == "secure_field: Conn never types into password fields"


def test_scroll_gate_is_act_low(cfg, tmp_path):
    harness, _ctx, _store, _backend, snap = make_ctx(
        cfg,
        tmp_path,
        node("AXWindow", "Main", children=(node("AXStaticText", "Target"),)),
    )

    call = gate(harness, "computer_scroll", {"snapshot_id": snap.snapshot_id, "ref": "e2"})

    assert call.gate is Gate.AUTO


def test_menu_gate_defaults_to_confirm_and_can_be_trusted(cfg, tmp_path):
    harness, _ctx, _store, _backend, _snap = make_ctx(cfg, tmp_path, node("AXWindow", "Main"), bundle="com.apple.mail")

    default_call = gate(harness, "app_menu", {"path": ["File", "New Tab"]})
    assert default_call.gate is Gate.CONFIRM

    cfg.interactions.trusted = {"com.apple.mail": ["AXMenuItem"]}
    trusted_call = gate(harness, "app_menu", {"path": ["File", "New Tab"]})
    assert trusted_call.gate is Gate.AUTO


def test_menu_gate_invalid_path_type_blocks_without_preview_crash(cfg, tmp_path):
    harness, _ctx, _store, _backend, _snap = make_ctx(cfg, tmp_path, node("AXWindow", "Main"), bundle="com.apple.mail")

    call = gate(harness, "app_menu", {"path": 42})

    assert call.gate is Gate.BLOCKED
    assert "invalid_arguments" in harness.block_reason(call)
    assert isinstance(call.preview, str) and call.preview


def test_menu_gate_empty_path_blocks_before_executor(cfg, tmp_path):
    harness, _ctx, _store, _backend, _snap = make_ctx(cfg, tmp_path, node("AXWindow", "Main"), bundle="com.apple.mail")

    call = gate(harness, "app_menu", {"path": []})

    assert call.gate is Gate.BLOCKED
    assert "invalid_arguments" in harness.block_reason(call)


def test_gate_for_app_frontmost_unavailable_returns_blocked_tuple(cfg, tmp_path):
    _harness, ctx, _store, backend, _snap = make_ctx(
        cfg,
        tmp_path,
        node("AXWindow", "Main"),
        bundle="com.apple.Safari",
    )

    def unavailable():
        raise ToolError("frontmost_unavailable")

    backend.frontmost = unavailable

    for name, args in (
        ("app_focus_tab", {"title": "Inbox", "app": "Safari"}),
        ("app_menu", {"path": ["File", "Close"], "app": "Safari"}),
    ):
        gate_value, reason, preview = risk_gate_for(name, RiskLevel.ACT_LOW, args, cfg, ctx)
        assert gate_value is Gate.BLOCKED
        assert reason == "app_frontmost_unavailable: Safari"
        assert preview is None


@pytest.mark.parametrize(
    ("combo", "auto", "confirm", "expected"),
    [
        ("CMD+Shift+T", ["cmd+shift+t"], [], Gate.AUTO),
        ("cmd+p", [], ["cmd+p"], Gate.CONFIRM),
        ("cmd+alt+u", [], [], Gate.BLOCKED),
    ],
)
def test_hotkey_gate_uses_normalized_allowlists(cfg, harness, combo, auto, confirm, expected):
    cfg.hotkeys.auto = auto
    cfg.hotkeys.confirm = confirm

    call = gate(harness, "computer_hotkey", {"combo": combo})

    assert call.gate is expected
    if expected is Gate.BLOCKED:
        assert call.block_reason.startswith("hotkey_not_allowlisted")


def test_present_only_allowlist_guard_for_app_qualified_tools(cfg, tmp_path):
    harness, _ctx, _store, _backend, _snap = make_ctx(cfg, tmp_path, node("AXWindow", "Main"))

    assert gate(harness, "app_focus_tab", {"title": "Inbox"}).gate is Gate.AUTO
    assert gate(harness, "app_menu", {"path": ["File", "Close"]}).gate is Gate.CONFIRM

    focus_blocked = gate(harness, "app_focus_tab", {"title": "Inbox", "app": "Disk Utility"})
    menu_blocked = gate(harness, "app_menu", {"path": ["File", "Close"], "app": "Disk Utility"})

    assert focus_blocked.gate is Gate.BLOCKED
    assert menu_blocked.gate is Gate.BLOCKED
    assert "app_not_allowlisted" in (focus_blocked.block_reason or "")
    assert "app_not_allowlisted" in (menu_blocked.block_reason or "")


def test_app_qualified_tools_block_when_frontmost_app_does_not_match(cfg, tmp_path):
    harness, _ctx, _store, _backend, _snap = make_ctx(
        cfg,
        tmp_path,
        node("AXWindow", "Main"),
        bundle="com.unallowed.App",
    )

    focus_blocked = gate(harness, "app_focus_tab", {"title": "Inbox", "app": "Safari"})
    menu_blocked = gate(harness, "app_menu", {"path": ["File", "Close"], "app": "Safari"})

    assert focus_blocked.gate is Gate.BLOCKED
    assert menu_blocked.gate is Gate.BLOCKED
    assert focus_blocked.block_reason == "app_not_frontmost: Safari"
    assert menu_blocked.block_reason == "app_not_frontmost: Safari"


def test_app_qualified_tools_allow_matching_frontmost_app(cfg, tmp_path):
    harness, _ctx, _store, _backend, _snap = make_ctx(
        cfg,
        tmp_path,
        node("AXWindow", "Main"),
        bundle="com.apple.Safari",
    )

    focus_call = gate(harness, "app_focus_tab", {"title": "Inbox", "app": "Safari"})
    menu_call = gate(harness, "app_menu", {"path": ["File", "Close"], "app": "Safari"})

    assert focus_call.gate is Gate.AUTO
    assert menu_call.gate is Gate.CONFIRM


def test_app_qualified_tools_use_exact_configured_bundle(cfg, tmp_path):
    cfg.apps.allowlist = cfg.apps.allowlist + ["Terminal"]
    cfg.apps.bundle_ids["Terminal"] = "com.apple.Terminal"
    harness, _ctx, _store, _backend, _snap = make_ctx(
        cfg,
        tmp_path,
        node("AXWindow", "Main"),
        bundle="com.apple.Terminal",
    )

    menu_call = gate(harness, "app_menu", {"path": ["Shell", "New Tab"], "app": "Terminal"})

    assert menu_call.gate is Gate.CONFIRM
    assert menu_call.block_reason is None


def test_app_qualified_tools_reject_same_bundle_tail(cfg, tmp_path):
    cfg.apps.allowlist = cfg.apps.allowlist + ["Terminal"]
    cfg.apps.bundle_ids["Terminal"] = "com.apple.Terminal"
    harness, _ctx, _store, _backend, _snap = make_ctx(
        cfg,
        tmp_path,
        node("AXWindow", "Main"),
        bundle="evil.Terminal",
    )

    menu_call = gate(harness, "app_menu", {"path": ["Shell", "New Tab"], "app": "Terminal"})

    assert menu_call.gate is Gate.BLOCKED
    assert menu_call.block_reason == "app_not_frontmost: Terminal"


def test_expired_auto_grounded_call_is_reblocked_at_run_time(cfg, tmp_path, monkeypatch):
    import asyncio
    import conn.tools.ax as ax

    now = [100.0]
    monkeypatch.setattr(ax.time, "monotonic", lambda: now[0])
    cfg.interactions.trusted = {"com.apple.TextEdit": ["AXButton"]}
    harness, ctx, _store, _backend, snap = make_ctx(
        cfg,
        tmp_path,
        node("AXWindow", "Main", frame=(0, 0, 500, 400), children=(node("AXButton", "Send", frame=(10, 10, 80, 24)),)),
    )
    input_backend = FakeInputBackend()
    ctx.input_backend = input_backend

    call = gate(harness, "computer_click", {"snapshot_id": snap.snapshot_id, "ref": "e2"})
    assert call.gate is Gate.AUTO
    now[0] = 111.0

    result = asyncio.run(harness.run(call))
    envelope = json.loads(result.output)

    assert result.ok is False
    assert envelope["ok"] is False
    assert envelope["error"] == "snapshot_expired: take a new snapshot"
    assert input_backend.actions == []


def test_app_qualified_focus_tab_rechecks_frontmost_at_run_time(cfg, tmp_path):
    import asyncio

    harness, ctx, _store, backend, _snap = make_ctx(
        cfg,
        tmp_path,
        node("AXWindow", "Main", children=(node("AXTab", "Inbox"),)),
        bundle="com.apple.Safari",
    )
    input_backend = FakeInputBackend()
    ctx.input_backend = input_backend

    call = gate(harness, "app_focus_tab", {"title": "Inbox", "app": "Safari"})
    assert call.gate is Gate.AUTO
    backend.bundle_id = "com.unallowed.App"

    result = asyncio.run(harness.run(call))
    envelope = json.loads(result.output)

    assert result.ok is False
    assert envelope["error"] == "app_not_frontmost: Safari"
    assert input_backend.actions == []


def test_app_qualified_menu_rechecks_frontmost_at_run_time(cfg, tmp_path):
    import asyncio

    harness, ctx, _store, backend, _snap = make_ctx(
        cfg,
        tmp_path,
        node("AXWindow", "Main"),
        bundle="com.apple.Safari",
    )
    backend.menu_root = node("AXMenuBar", "Menu", children=(node("AXMenu", "File", children=(node("AXMenuItem", "Close"),)),))
    input_backend = FakeInputBackend()
    ctx.input_backend = input_backend

    call = gate(harness, "app_menu", {"path": ["File", "Close"], "app": "Safari"})
    assert call.gate is Gate.CONFIRM
    backend.bundle_id = "com.unallowed.App"

    result = asyncio.run(harness.run(call))
    envelope = json.loads(result.output)

    assert result.ok is False
    assert envelope["error"] == "app_not_frontmost: Safari"
    assert input_backend.actions == []


def test_export_payload_stays_under_20kb():
    payload = json.dumps(export_openai(build_registry()))
    assert len(payload) < 20_000


def test_verified_live_main_does_not_construct_python_ax_store(monkeypatch, tmp_path):
    import conn.__main__ as main_mod

    cfg = Config()
    cfg.data_dir = tmp_path / "data"

    seen = {"ctx_ax": "unset"}

    class FakeMacAxBackend:
        pass

    class FakeSnapshotStore:
        def __init__(self, backend, passed_cfg):
            raise AssertionError("verified production constructed Python AX store")

    class FakeAdapter:
        def __init__(self, *args, **kwargs):
            pass

    class FakeApp:
        def __init__(self, cfg, adapter, harness, audio=None):
            self.session_id = "s1"
            seen["ctx_ax"] = harness.ctx.ax

        async def start(self):
            return None

        async def stop(self):
            return None

    async def fake_serve(app, shutdown_event=None):
        return None

    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setattr("conn.tools.ax.MacAxBackend", FakeMacAxBackend)
    monkeypatch.setattr("conn.tools.ax.SnapshotStore", FakeSnapshotStore)
    monkeypatch.setattr(main_mod, "ConnApp", FakeApp)
    monkeypatch.setattr("conn.realtime.openai_ws.OpenAIRealtimeAdapter", FakeAdapter)
    monkeypatch.setattr("conn.server.http.serve", fake_serve)

    args = argparse.Namespace(
        demo=False,
        simulate_tools=False,
        no_audio=True,
        no_hotkey=True,
    )

    import asyncio

    asyncio.run(main_mod._serve(cfg, args))

    assert seen["ctx_ax"] is None
