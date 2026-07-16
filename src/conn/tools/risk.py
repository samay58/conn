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
from urllib.parse import urlsplit

from ..config import Config
from ..events import Gate
from ..navigation import NavigationEffect, NavigationLease
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
BROWSER_URL_MAX_CHARS = 4096


def _guard_app_allowlist(args: dict, cfg: Config) -> str | None:
    app = args.get("app", "")
    if app not in cfg.apps.allowlist:
        allowed = ", ".join(cfg.apps.allowlist)
        return f"app_not_allowlisted: {app!r}. Allowed apps: {allowed}"
    return None


def _guard_app_name(args: dict, cfg: Config) -> str | None:
    app = str(args.get("app") or "").strip()
    if not app:
        return "app_name_missing"
    if len(app) > 128 or any(ord(char) < 32 or ord(char) == 127 for char in app):
        return "app_name_invalid"
    return None


def _guard_browser_url(args: dict, cfg: Config) -> str | None:
    raw = str(args.get("url") or "")
    if not raw:
        return "browser_url_missing"
    if len(raw) > BROWSER_URL_MAX_CHARS:
        return "browser_url_too_large"
    if raw != raw.strip() or any(ord(char) < 32 or ord(char) == 127 for char in raw):
        return "browser_url_invalid"
    candidate = raw if "://" in raw else f"https://{raw}"
    try:
        parsed = urlsplit(candidate)
        _ = parsed.port
    except ValueError:
        return "browser_url_invalid"
    if parsed.scheme.lower() not in {"http", "https"}:
        return "browser_url_unsupported_scheme"
    if not parsed.hostname:
        return "browser_url_missing_host"
    if parsed.username is not None or parsed.password is not None:
        return "browser_url_credentials_refused"
    scope = str(args.get("browser_scope") or "").strip()
    if scope and (
        len(scope) > 128
        or any(ord(char) < 32 or ord(char) == 127 for char in scope)
    ):
        return "browser_url_invalid_browser_scope"
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
    if _app_matches_bundle(app, bundle_id, cfg):
        return None
    return f"app_not_frontmost: {app}"


def _app_matches_bundle(app: str, bundle_id: str, cfg: Config) -> bool:
    return app_matches_bundle(app, bundle_id, cfg.apps.bundle_ids)


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


def _guard_scroll(args: dict, cfg: Config) -> str | None:
    if ("direction" in args) != ("amount" in args):
        return "scroll_direction_and_amount_required_together"
    return None


ARG_GUARDS: dict[str, Callable[[dict, Config], str | None]] = {
    "app_open": _guard_app_name,
    "app_switch": _guard_app_name,
    "browser_navigate": _guard_browser_url,
    "phoenix_open_note": _guard_vault_path,
    "clipboard_set": _guard_clipboard_size,
    "computer_scroll": _guard_scroll,
    "app_focus_tab": _guard_present_app_allowlist,
    "app_menu": _guard_present_app_allowlist,
}


def argument_guard(name: str, args: dict, cfg: Config) -> str | None:
    guard = ARG_GUARDS.get(name)
    return guard(args, cfg) if guard is not None else None


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

    reason = argument_guard(name, args, cfg)
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


def gate_for_prepared(
    name: str,
    level: RiskLevel,
    args: dict,
    plan: dict,
    cfg: Config,
    navigation: NavigationLease | None = None,
) -> tuple[Gate, str | None, str | None]:
    if level is RiskLevel.BLOCKED:
        return Gate.BLOCKED, "tool_disabled_in_v0", None
    if bool(plan.get("denied")):
        return Gate.BLOCKED, "denied_bundle: native policy refused target", None
    if name == "computer_type_text" and bool(plan.get("secure")):
        return Gate.BLOCKED, "secure_field: Conn never types into password fields", None

    reason = argument_guard(name, args, cfg)
    if reason:
        return Gate.BLOCKED, reason, None

    if name in {"app_focus_tab", "app_menu"}:
        app = str(args.get("app") or "").strip()
        bundle_id = str(plan.get("bundle_id") or "")
        if app and (not bundle_id or not _app_matches_bundle(app, bundle_id, cfg)):
            return Gate.BLOCKED, f"app_not_frontmost: {app}", None

    if navigation is not None:
        try:
            effect = NavigationEffect(str(plan.get("effect_class") or ""))
        except ValueError:
            return Gate.BLOCKED, "unknown_effect_class", None
        generation = plan.get("navigation_generation")
        if not isinstance(generation, int) or isinstance(generation, bool):
            return Gate.BLOCKED, "navigation_generation_missing", None
        if effect is NavigationEffect.DESTRUCTIVE:
            return Gate.BLOCKED, "destructive_effect", None
        if effect is NavigationEffect.SECURE_OR_DENIED:
            return Gate.BLOCKED, "secure_or_denied_effect", None
        if effect is NavigationEffect.UNKNOWN:
            return Gate.BLOCKED, "unknown_effect", None
        if effect is NavigationEffect.CONSEQUENTIAL:
            return Gate.CONFIRM, None, str(plan["preview"])
        if generation != navigation.generation:
            return Gate.BLOCKED, "navigation_lease_stale", None
        if not navigation.allows(effect, generation):
            reason = (
                "navigation_suspended"
                if navigation.public_snapshot()["suspended"]
                else "navigation_grant_required"
            )
            return Gate.BLOCKED, reason, None
        if cfg.risk_overrides.get(name) == "blocked":
            return Gate.BLOCKED, "blocked_by_config_override", None
        if cfg.risk_overrides.get(name) == "confirm":
            return Gate.CONFIRM, None, str(plan["preview"])
        return Gate.AUTO, None, str(plan["preview"])

    if name == "computer_hotkey":
        gate, reason, _preview = _gate_hotkey(args, cfg)
        return gate, reason, str(plan["preview"])

    if name == "computer_click":
        bundle_id = str(plan.get("bundle_id") or "")
        role = str(plan.get("target_role") or "")
        gate = Gate.AUTO if role in _trusted_roles(cfg, bundle_id) else Gate.CONFIRM
    elif name == "computer_type_text":
        gate = Gate.CONFIRM
    elif name == "app_menu":
        bundle_id = str(plan.get("bundle_id") or "")
        gate = Gate.AUTO if "AXMenuItem" in _trusted_roles(cfg, bundle_id) else Gate.CONFIRM
    else:
        gate = _LEVEL_TO_GATE[level]

    native_risk = str(plan.get("risk") or "").lower()
    if native_risk in {"external_side_effect", "destructive"}:
        gate = Gate.CONFIRM

    override = cfg.risk_overrides.get(name)
    if override == "blocked":
        return Gate.BLOCKED, "blocked_by_config_override", None
    if override == "confirm":
        gate = Gate.CONFIRM
    elif override == "auto" and gate is Gate.AUTO:
        gate = Gate.AUTO

    return gate, None, str(plan["preview"])
