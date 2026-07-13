from __future__ import annotations

from urllib.parse import quote_plus, quote

from .registry import ToolSpec


def compile_action_request(spec: ToolSpec, args: dict, cfg) -> dict:
    name = spec.name
    operation = spec.semantic_operation
    if not spec.computer_mutation or not operation:
        raise ValueError(f"tool {name!r} is not a semantic computer mutation")
    target: dict | str | None = None
    payload: object | None = None

    if name in {"app_open", "app_switch"}:
        app_name = args["app"]
        bundle_id = str(cfg.apps.bundle_ids.get(app_name) or "").strip()
        if not bundle_id:
            raise ValueError(f"app_bundle_id_missing: {app_name!r}")
        payload = {"app_name": app_name, "bundle_id": bundle_id}
        team_id = str(cfg.apps.team_ids.get(app_name) or "").strip()
        if not bundle_id.startswith("com.apple.") and not team_id:
            raise ValueError(f"app_signer_not_configured: {app_name!r}")
        if team_id:
            payload["team_id"] = team_id
    elif name == "browser_search":
        payload = {
            "url": cfg.browser.search_url.format(q=quote_plus(args["query"]))
        }
    elif name == "phoenix_open_note":
        vault = quote(cfg.phoenix.obsidian_vault, safe="")
        path = quote(str(args["path"]).lstrip("/"), safe="/")
        payload = {"url": f"obsidian://open?vault={vault}&file={path}"}
    elif name == "clipboard_set":
        payload = args["text"]
    elif name in {"computer_click", "computer_scroll"}:
        target = {"snapshot_id": args["snapshot_id"], "ref": args["ref"]}
        if name == "computer_scroll" and "direction" in args and "amount" in args:
            payload = {"direction": args["direction"], "amount": args["amount"]}
    elif name == "computer_type_text":
        target = {"snapshot_id": args["snapshot_id"], "ref": args["ref"]}
        payload = {"text": args["text"], "submit": bool(args.get("submit", False))}
    elif name == "computer_hotkey":
        combo = str(args["combo"]).lower().replace("meta", "cmd").replace(
            "super", "cmd"
        )
        payload = {"keys": combo.split("+")}
    elif name == "app_focus_tab":
        app_name = str(args.get("app") or "").strip()
        target = {"title": args["title"], "app": app_name or None}
        if app_name:
            bundle_id = str(cfg.apps.bundle_ids.get(app_name) or "").strip()
            if not bundle_id:
                raise ValueError(f"app_bundle_id_missing: {app_name!r}")
            payload = {"bundle_id": bundle_id}
            team_id = str(cfg.apps.team_ids.get(app_name) or "").strip()
            if not bundle_id.startswith("com.apple.") and not team_id:
                raise ValueError(f"app_signer_not_configured: {app_name!r}")
            if team_id:
                payload["team_id"] = team_id
    elif name == "app_menu":
        payload = {"menu_path": args["path"]}
        app_name = str(args.get("app") or "").strip()
        if app_name:
            bundle_id = str(cfg.apps.bundle_ids.get(app_name) or "").strip()
            if not bundle_id:
                raise ValueError(f"app_bundle_id_missing: {app_name!r}")
            payload["bundle_id"] = bundle_id
            team_id = str(cfg.apps.team_ids.get(app_name) or "").strip()
            if not bundle_id.startswith("com.apple.") and not team_id:
                raise ValueError(f"app_signer_not_configured: {app_name!r}")
            if team_id:
                payload["team_id"] = team_id

    timeout_ms = (
        cfg.actions.launch_verify_ms
        if name in {"app_open", "app_switch"}
        else cfg.actions.semantic_verify_ms
    )
    strategy_ceiling = (
        "semantic_plus_events"
        if name in {"computer_type_text", "computer_hotkey"}
        else "semantic_only"
    )
    return {
        "operation": operation,
        "target": target,
        "payload": payload,
        "desired_effect": args.get("desired_effect"),
        "risk": spec.risk.value,
        "strategy_ceiling": strategy_ceiling,
        "timeout_ms": timeout_ms,
        "denied_bundles": list(cfg.ax.deny_bundles),
    }


def validate_plan(plan: object) -> str | None:
    if not isinstance(plan, dict):
        return "native_plan_invalid: expected object"
    fingerprint = plan.get("plan_fingerprint")
    if not isinstance(fingerprint, str) or not fingerprint:
        return "native_plan_invalid: missing plan fingerprint"
    if not isinstance(plan.get("preview"), str) or not plan["preview"].strip():
        return "native_plan_invalid: missing safe preview"
    if not isinstance(plan.get("target"), str) or not plan["target"].strip():
        return "native_plan_invalid: missing safe target"
    if not isinstance(plan.get("effect"), str) or not plan["effect"].strip():
        return "native_plan_invalid: missing effect summary"
    strategies = plan.get("authorized_strategies")
    if (
        not isinstance(strategies, list)
        or not strategies
        or len(strategies) > 8
        or any(not isinstance(item, str) or not item for item in strategies)
    ):
        return "native_plan_invalid: invalid authorized strategies"
    semantic_strategies = {
        "launch_services",
        "pasteboard",
        "ax_press",
        "ax_set_value",
        "ax_set_selected",
        "ax_scroll_to_visible",
        "ax_menu_action",
        "live_menu_shortcut",
        "unicode_text",
        "key_chord",
    }
    if any(item not in semantic_strategies for item in strategies):
        return "native_plan_invalid: unauthorized strategy"
    return None


_SAFE_PLAN_FIELDS = frozenset({
    "plan_fingerprint",
    "preview",
    "target",
    "effect",
    "authorized_strategies",
    "risk",
    "target_role",
    "secure",
    "denied",
    "bundle_id",
    "window_id",
    "snapshot_id",
    "observation_id",
    "predicates",
    "payload_hash",
    "before_digest",
    "target_fingerprint",
})


def safe_plan(plan: dict) -> dict:
    return {key: value for key, value in plan.items() if key in _SAFE_PLAN_FIELDS}
