"""Risk policy. The harness owns permissions; the model only proposes.

A tool's static risk level maps to a gate. Argument guards run first and can
force BLOCKED regardless of level (allowlist violations, path escapes). Config
overrides may move a generic tool between auto and confirm, but a BLOCKED tool
can never be downgraded from config.
"""

from __future__ import annotations

from enum import StrEnum
from pathlib import Path
from typing import Callable

from ..config import Config
from ..events import Gate
from .ax_input import _normalize_combo
from .base import ExecutionContext, app_matches_bundle


class RiskLevel(StrEnum):
    READ = "read"
    ACT_LOW = "act_low"
    ACT_CONFIRM = "act_confirm"
    BLOCKED = "blocked"


_LEVEL_TO_GATE = {
    RiskLevel.READ: Gate.AUTO,
    RiskLevel.ACT_LOW: Gate.AUTO,
    RiskLevel.ACT_CONFIRM: Gate.CONFIRM,
    RiskLevel.BLOCKED: Gate.BLOCKED,
}

CLIPBOARD_MAX_CHARS = 100_000


def _guard_app_allowlist(args: dict, cfg: Config) -> str | None:
    app = args.get("app", "")
    if app not in cfg.apps.allowlist:
        allowed = ", ".join(cfg.apps.allowlist)
        return f"app_not_allowlisted: {app!r}. Allowed apps: {allowed}"
    return None


def _guard_present_app_allowlist(args: dict, cfg: Config) -> str | None:
    if "app" not in args:
        return None
    app = str(args.get("app") or "").strip()
    if not app:
        return None
    return _guard_app_allowlist({"app": app}, cfg)


def _guard_present_app_frontmost(args: dict, cfg: Config, ctx: ExecutionContext | None) -> str | None:
    reason = _guard_present_app_allowlist(args, cfg)
    if reason:
        return reason
    if "app" not in args:
        return None
    app = str(args.get("app") or "").strip()
    if not app:
        return None
    bundle_id = _current_bundle_id(ctx)
    if bundle_id is None:
        return f"app_frontmost_unavailable: {app}"
    if _app_matches_bundle(app, bundle_id):
        return None
    return f"app_not_frontmost: {app}"


def _app_matches_bundle(app: str, bundle_id: str) -> bool:
    return app_matches_bundle(app, bundle_id)


def _exception_reason(exc: Exception) -> str:
    if not str(exc):
        return f"gating_failed: {type(exc).__name__}"
    if type(exc).__name__ in {"StaleRef", "ToolError"} or ":" in str(exc):
        return str(exc)
    return f"gating_failed: {type(exc).__name__}: {exc}"


def _guard_vault_path(args: dict, cfg: Config) -> str | None:
    raw = str(args.get("path", "")).lstrip("/")
    root = Path(cfg.phoenix.vault_root).resolve()
    target = (root / raw).resolve()
    if not target.is_relative_to(root):
        return f"path_outside_vault: {raw!r}"
    return None


def _guard_clipboard_size(args: dict, cfg: Config) -> str | None:
    if len(str(args.get("text", ""))) > CLIPBOARD_MAX_CHARS:
        return f"clipboard_payload_too_large: over {CLIPBOARD_MAX_CHARS} characters"
    return None


ARG_GUARDS: dict[str, Callable[[dict, Config], str | None]] = {
    "app_open": _guard_app_allowlist,
    "app_switch": _guard_app_allowlist,
    "phoenix_open_note": _guard_vault_path,
    "clipboard_set": _guard_clipboard_size,
    "app_focus_tab": _guard_present_app_allowlist,
    "app_menu": _guard_present_app_allowlist,
}


def _trusted_roles(cfg: Config, bundle_id: str) -> set[str]:
    return set(cfg.interactions.trusted.get(bundle_id, []))


def _current_bundle_id(ctx: ExecutionContext | None) -> str | None:
    if ctx is None or ctx.ax is None:
        return None
    try:
        bundle_id, _pid = ctx.ax.backend.frontmost()
        return bundle_id
    except Exception:
        return None


def _resolution_preview(action: str, element, snapshot) -> str:
    label = element.label or element.ref
    app = snapshot.window_title if snapshot is not None else "current window"
    return f'{action} "{label}" ({element.role}) in {app}'


def _resolution_snapshot(ctx: ExecutionContext | None, snapshot_id: str):
    if ctx is None or ctx.ax is None:
        raise RuntimeError("ax_unavailable")
    stored = getattr(ctx.ax, "_snapshots", {}).get(snapshot_id)
    return stored.snapshot if stored is not None else None


def _gate_click(args: dict, cfg: Config, ctx: ExecutionContext | None) -> tuple[Gate, str | None, str | None]:
    if ctx is None or ctx.ax is None:
        raise RuntimeError("ax_unavailable")
    element, _raw = ctx.ax.resolve(args["snapshot_id"], args["ref"], for_execution=False)
    bundle_id = _current_bundle_id(ctx) or ""
    gate = Gate.AUTO if element.role in _trusted_roles(cfg, bundle_id) else Gate.CONFIRM
    preview = _resolution_preview("Click", element, _resolution_snapshot(ctx, args["snapshot_id"]))
    return gate, None, preview


def _gate_type_text(args: dict, cfg: Config, ctx: ExecutionContext | None) -> tuple[Gate, str | None, str | None]:
    if ctx is None or ctx.ax is None:
        raise RuntimeError("ax_unavailable")
    element, _raw = ctx.ax.resolve(args["snapshot_id"], args["ref"], for_execution=False)
    if element.secure:
        return Gate.BLOCKED, "secure_field: Conn never types into password fields", None
    preview = _resolution_preview("Type into", element, _resolution_snapshot(ctx, args["snapshot_id"]))
    return Gate.CONFIRM, None, preview


def _gate_scroll(args: dict, cfg: Config, ctx: ExecutionContext | None) -> tuple[Gate, str | None, str | None]:
    if ctx is None or ctx.ax is None:
        raise RuntimeError("ax_unavailable")
    element, _raw = ctx.ax.resolve(args["snapshot_id"], args["ref"], for_execution=False)
    preview = _resolution_preview("Scroll to", element, _resolution_snapshot(ctx, args["snapshot_id"]))
    return Gate.AUTO, None, preview


RESOLUTION_GATES: dict[str, Callable[[dict, Config, ExecutionContext | None], tuple[Gate, str | None, str | None]]] = {
    "computer_click": _gate_click,
    "computer_type_text": _gate_type_text,
    "computer_scroll": _gate_scroll,
}


def _gate_hotkey(args: dict, cfg: Config) -> tuple[Gate, str | None, str | None]:
    combo = _normalize_combo(str(args["combo"]))
    if combo in {_normalize_combo(item) for item in cfg.hotkeys.auto}:
        return Gate.AUTO, None, f"Press keys: {combo}"
    if combo in {_normalize_combo(item) for item in cfg.hotkeys.confirm}:
        return Gate.CONFIRM, None, f"Press keys: {combo}"
    # The refusal names the allowlist so the model can reroute (usually to
    # app_menu) instead of retrying spellings of the same dead combo.
    allowed = ", ".join([*cfg.hotkeys.auto, *cfg.hotkeys.confirm]) or "none"
    return (Gate.BLOCKED,
            f"hotkey_not_allowlisted: {combo}. Allowed: {allowed}. Use app_menu for other menu actions",
            f"Press keys: {combo}")


def gate_for(
    name: str,
    level: RiskLevel,
    args: dict,
    cfg: Config,
    ctx: ExecutionContext | None = None,
) -> tuple[Gate, str | None, str | None]:
    """Returns (gate, block_reason, preview_override)."""
    if level is RiskLevel.BLOCKED:
        return Gate.BLOCKED, "tool_disabled_in_v0: enabled only behind a per-app profile", None

    if name in {"app_focus_tab", "app_menu"}:
        reason = _guard_present_app_frontmost(args, cfg, ctx)
        if reason:
            return Gate.BLOCKED, reason, None

    guard = ARG_GUARDS.get(name)
    if guard is not None:
        reason = guard(args, cfg)
        if reason:
            return Gate.BLOCKED, reason, None

    if name == "computer_hotkey":
        try:
            return _gate_hotkey(args, cfg)
        except Exception as e:
            return Gate.BLOCKED, _exception_reason(e), None

    resolution_gate = RESOLUTION_GATES.get(name)
    if resolution_gate is not None:
        try:
            return resolution_gate(args, cfg, ctx)
        except Exception as e:
            return Gate.BLOCKED, _exception_reason(e), None

    if name == "app_menu":
        bundle_id = _current_bundle_id(ctx) or ""
        gate = Gate.AUTO if "AXMenuItem" in _trusted_roles(cfg, bundle_id) else Gate.CONFIRM
        return gate, None, None

    override = cfg.risk_overrides.get(name)
    if override in ("auto", "confirm"):
        return Gate(override), None, None
    if override == "blocked":
        return Gate.BLOCKED, "blocked_by_config_override", None
    return _LEVEL_TO_GATE[level], None, None
