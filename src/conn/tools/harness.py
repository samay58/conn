"""Gate and execute tool calls. The pipeline is:

model proposal -> parse args -> schema check -> risk gate -> ToolCall(gate)
then, for approved/auto calls: executor on a thread, with timeout, wrapped in
a result envelope the model can rely on: {"ok": bool, "data"|"error", "duration_ms"}.
"""

from __future__ import annotations

import asyncio
import json
import time

from ..config import Config
from ..events import Gate, ToolCall, ToolFinished
from .base import ExecutionContext, ToolError
from .registry import ToolSpec
from .risk import gate_for

PREVIEW_BUDGET = 32


def clamp_preview(text: str, budget: int = PREVIEW_BUDGET) -> str:
    """Chip previews are composed to fit the island; this is the safety net.
    Over-budget text truncates at a word boundary with a trailing ellipsis,
    never mid-word (a single unbroken token longer than the budget has no
    boundary and cuts hard, the only option left)."""
    text = text.strip()
    if len(text) <= budget:
        return text
    head = text[: budget - 1]
    if " " in head:
        head = head.rsplit(" ", 1)[0].rstrip()
    return head + "…"


_TYPE_MAP = {
    "string": str,
    "integer": int,
    "number": (int, float),
    "boolean": bool,
    "object": dict,
    "array": list,
}


def validate_args(schema: dict, args: dict) -> str | None:
    props = schema.get("properties", {})
    for key in schema.get("required", []):
        if key not in args:
            return f"missing required argument {key!r}"
    for key, value in args.items():
        prop = props.get(key)
        if prop is None:
            continue
        expected = _TYPE_MAP.get(prop.get("type", ""))
        if expected and not isinstance(value, expected):
            return f"argument {key!r} should be {prop['type']}"
        if prop.get("type") == "array":
            min_items = prop.get("minItems")
            if min_items is not None and len(value) < int(min_items):
                return f"argument {key!r} should have at least {min_items} item"
            item_schema = prop.get("items", {})
            item_expected = _TYPE_MAP.get(item_schema.get("type", ""))
            if item_expected and any(not isinstance(item, item_expected) for item in value):
                return f"argument {key!r} items should be {item_schema['type']}"
    return None


class ToolHarness:
    def __init__(self, registry: dict[str, ToolSpec], cfg: Config, ctx: ExecutionContext, executors: dict[str, object] | None = None):
        self.registry = registry
        self.cfg = cfg
        self.ctx = ctx
        self._executors = executors

    def _safe_preview(self, spec: ToolSpec, args: dict) -> str:
        try:
            return clamp_preview(spec.preview(args))
        except Exception:
            try:
                return clamp_preview(spec.preview({}))
            except Exception:
                return f"Use tool: {spec.name}"

    def gate(self, call_id: str, name: str, arguments_json: str) -> ToolCall:
        spec = self.registry.get(name)
        if spec is None:
            return ToolCall(call_id=call_id, name=name, arguments={}, gate=Gate.BLOCKED, preview=f"Unknown tool: {name}", block_reason=f"unknown_tool: {name!r}")
        try:
            args = json.loads(arguments_json) if arguments_json.strip() else {}
            if not isinstance(args, dict):
                raise ValueError("arguments must be a JSON object")
        except ValueError as e:
            return ToolCall(
                call_id=call_id,
                name=name,
                arguments={},
                gate=Gate.BLOCKED,
                preview=f"{self._safe_preview(spec, {})} (invalid arguments)",
                block_reason=f"invalid_arguments: {e}",
            )
        problem = validate_args(spec.parameters, args)
        if problem:
            if name == "computer_click" and "selector" in args and "snapshot_id" not in args and "ref" not in args:
                return ToolCall(
                    call_id=call_id,
                    name=name,
                    arguments=args,
                    gate=Gate.BLOCKED,
                    preview=f"{self._safe_preview(spec, args)} (snapshot required)",
                    block_reason="tool_disabled_in_v0: ungrounded selectors are disabled; take a snapshot first",
                )
            return ToolCall(
                call_id=call_id,
                name=name,
                arguments=args,
                gate=Gate.BLOCKED,
                preview=f"{self._safe_preview(spec, args)} (invalid arguments)",
                block_reason=f"invalid_arguments: {problem}",
            )
        try:
            gate, reason, preview_override = gate_for(name, spec.risk, args, self.cfg, self.ctx)
        except Exception as e:
            gate = Gate.BLOCKED
            reason = str(e) if getattr(e, "args", None) else f"gating_failed: {type(e).__name__}"
            if not reason:
                reason = f"gating_failed: {type(e).__name__}"
            elif reason == str(e) and type(e).__name__ not in {"StaleRef", "ToolError"} and ":" not in reason:
                reason = f"gating_failed: {type(e).__name__}: {reason}"
            preview_override = None
        # The clamp covers both preview sources: the registry lambdas and the
        # grounded-resolution overrides from risk.py, whose element titles are
        # unbounded.
        return ToolCall(call_id=call_id, name=name, arguments=args, gate=gate, preview=clamp_preview(preview_override or self._safe_preview(spec, args)), block_reason=reason)

    def block_reason(self, call: ToolCall) -> str:
        return call.block_reason or "blocked_by_policy"

    async def run(self, call: ToolCall) -> ToolFinished:
        started = time.monotonic()
        if call.gate is Gate.BLOCKED:
            envelope = {"ok": False, "error": self.block_reason(call), "duration_ms": int((time.monotonic() - started) * 1000)}
            return ToolFinished(call_id=call.call_id, ok=False, output=json.dumps(envelope))
        spec = self.registry[call.name]
        problem = validate_args(spec.parameters, call.arguments)
        if problem:
            envelope = {"ok": False, "error": f"invalid_arguments: {problem}", "duration_ms": int((time.monotonic() - started) * 1000)}
            return ToolFinished(call_id=call.call_id, ok=False, output=json.dumps(envelope))
        try:
            gate, reason, _preview = gate_for(call.name, spec.risk, call.arguments, self.cfg, self.ctx)
        except Exception as e:
            reason = str(e) or f"gating_failed: {type(e).__name__}"
            envelope = {"ok": False, "error": reason, "duration_ms": int((time.monotonic() - started) * 1000)}
            return ToolFinished(call_id=call.call_id, ok=False, output=json.dumps(envelope))
        if gate is Gate.BLOCKED:
            envelope = {"ok": False, "error": reason or "blocked_by_policy", "duration_ms": int((time.monotonic() - started) * 1000)}
            return ToolFinished(call_id=call.call_id, ok=False, output=json.dumps(envelope))
        executor = (self._executors or {}).get(call.name, spec.executor)
        try:
            data = await asyncio.wait_for(asyncio.to_thread(executor, call.arguments, self.ctx), timeout=spec.timeout_s)
            envelope = {"ok": True, "data": data, "duration_ms": int((time.monotonic() - started) * 1000)}
            return ToolFinished(call_id=call.call_id, ok=True, output=json.dumps(envelope))
        except TimeoutError:
            envelope = {"ok": False, "error": f"timeout after {spec.timeout_s}s", "duration_ms": int((time.monotonic() - started) * 1000)}
        except ToolError as e:
            envelope = {"ok": False, "error": str(e), "duration_ms": int((time.monotonic() - started) * 1000)}
        except Exception as e:
            envelope = {"ok": False, "error": f"internal: {type(e).__name__}: {e}", "duration_ms": int((time.monotonic() - started) * 1000)}
        return ToolFinished(call_id=call.call_id, ok=False, output=json.dumps(envelope))
