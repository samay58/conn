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
        payload = _application_goal(str(args["app"]), cfg)
    elif name == "browser_search":
        payload = {
            "url": cfg.browser.search_url.format(q=quote_plus(args["query"]))
        }
    elif name == "browser_navigate":
        scope = str(args.get("browser_scope") or "").strip()
        payload = {"url": args["url"]}
        if scope:
            payload["browser_scope"] = scope
            hints = _application_hints(scope, cfg)
            payload.update(hints)
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
    elif name == "computer_activate":
        has_semantic = bool(args.get("snapshot_id") and args.get("ref"))
        has_visual = isinstance(args.get("grounding"), dict)
        if has_semantic == has_visual:
            raise ValueError("activation_requires_one_grounding_lane")
        payload = {"goal": args["goal"]}
        if has_semantic:
            target = {"snapshot_id": args["snapshot_id"], "ref": args["ref"]}
        else:
            payload["visual_grounding"] = _visual_grounding(args["grounding"])
    elif name == "computer_key":
        payload = {"keys": [args["key"]]}
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
    elif name == "computer_create":
        payload = {"family": "create", "kind": args["kind"]}
        payload.update(_intent_scope(args, cfg))
    elif name == "computer_select_relative":
        payload = {"family": "select_relative", "relation": args["relation"]}
        if args.get("kind"):
            payload["kind"] = args["kind"]
        payload.update(_intent_scope(args, cfg))
    elif name == "computer_select":
        payload = {"family": "select_named", "target_name": args["name"]}
        if args.get("kind"):
            payload["kind"] = args["kind"]
        payload.update(_intent_scope(args, cfg))

    timeout_ms = (
        cfg.actions.launch_verify_ms
        if name in {"app_open", "app_switch"}
        else cfg.actions.create_verify_ms
        if name == "computer_create"
        else cfg.actions.visual_verify_ms
        if name == "computer_activate" and isinstance(args.get("grounding"), dict)
        else cfg.actions.semantic_verify_ms
    )
    strategy_ceiling = (
        "semantic_plus_events"
        if name in {"computer_type_text", "computer_hotkey"}
        else "semantic_only"
    )
    # Model-authored effect predicates are gone from the contract: the
    # native side derives every witness or declares a truthful ceiling. A
    # predicate the model hallucinates is dropped here, never forwarded.
    request = {
        "operation": operation,
        "target": target,
        "payload": payload,
        "risk": spec.risk.value,
        "strategy_ceiling": strategy_ceiling,
        "timeout_ms": timeout_ms,
        "denied_bundles": list(cfg.ax.deny_bundles),
    }
    if name == "computer_activate":
        request["visual_enabled"] = bool(cfg.actions.visual_enabled)
    return request


def _visual_grounding(value: dict) -> dict:
    if set(value) != {"capture_id", "region", "label", "confidence"}:
        raise ValueError("visual_grounding_invalid")
    capture_id = value.get("capture_id")
    label = value.get("label")
    confidence = value.get("confidence")
    region = value.get("region")
    if not isinstance(capture_id, str) or not capture_id or len(capture_id) > 128:
        raise ValueError("visual_capture_id_invalid")
    if not isinstance(label, str) or not label.strip() or len(label) > 160:
        raise ValueError("visual_label_invalid")
    if not isinstance(confidence, (int, float)) or isinstance(confidence, bool) or not 0 <= confidence <= 1:
        raise ValueError("visual_confidence_invalid")
    if not isinstance(region, dict) or set(region) != {"x", "y", "width", "height"}:
        raise ValueError("visual_region_invalid")
    numbers = {key: region[key] for key in ("x", "y", "width", "height")}
    if any(not isinstance(item, (int, float)) or isinstance(item, bool) for item in numbers.values()):
        raise ValueError("visual_region_invalid")
    if numbers["width"] <= 0 or numbers["height"] <= 0 or any(item < 0 or item > 1 for item in numbers.values()):
        raise ValueError("visual_region_invalid")
    if numbers["x"] + numbers["width"] > 1 or numbers["y"] + numbers["height"] > 1:
        raise ValueError("visual_region_invalid")
    return {
        "capture_id": capture_id,
        "region": numbers,
        "label": label.strip(),
        "confidence": float(confidence),
    }


def _intent_scope(args: dict, cfg) -> dict:
    app_name = str(args.get("app") or "").strip()
    if not app_name:
        return {}
    return _application_goal(app_name, cfg)


def _application_goal(app_name: str, cfg) -> dict:
    goal = {"app_name": app_name}
    goal.update(_application_hints(app_name, cfg))
    return goal


def _application_hints(app_name: str, cfg) -> dict:
    hints: dict = {}
    bundle_id = str(cfg.apps.bundle_ids.get(app_name) or "").strip()
    if bundle_id:
        hints["bundle_id_hint"] = bundle_id
    return hints


def validate_plan(
    plan: object, *, require_navigation: bool = False, allow_visual: bool = False
) -> str | None:
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
        "ax_set_selected_rows",
        "semantic_row_key_select",
        "ax_scroll_to_visible",
        "ax_menu_action",
        "live_menu_shortcut",
        "unicode_text",
        "key_chord",
    }
    if allow_visual:
        semantic_strategies.add("visual_coordinate_press")
    if any(item not in semantic_strategies for item in strategies):
        return "native_plan_invalid: unauthorized strategy"
    if require_navigation:
        if plan.get("effect_class") not in {
            "reversible_navigation",
            "consequential",
            "destructive",
            "secure_or_denied",
            "unknown",
        }:
            return "native_plan_invalid: missing effect class"
        generation = plan.get("navigation_generation")
        if not isinstance(generation, int) or isinstance(generation, bool):
            return "native_plan_invalid: missing navigation generation"
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
    "candidates",
    "read_set",
    "timeout_ms",
    "effect_class",
    "navigation_generation",
})


def safe_plan(plan: dict) -> dict:
    return {key: value for key, value in plan.items() if key in _SAFE_PLAN_FIELDS}


def safe_failure_data(value: object) -> dict:
    if not isinstance(value, dict) or not isinstance(value.get("candidates"), list):
        return {}
    candidates = []
    for raw in value["candidates"][:20]:
        if not isinstance(raw, dict):
            continue
        candidate = {}
        for key in ("display", "app_name", "bundle_id"):
            item = raw.get(key)
            if isinstance(item, str) and item.strip():
                candidate[key] = item.strip()[:160]
        if candidate.get("display"):
            candidates.append(candidate)
    return {"candidates": candidates} if candidates else {}
