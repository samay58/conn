"""Gate and execute tool calls. The pipeline is:

model proposal -> parse args -> schema check -> risk gate -> ToolCall(gate)
then, for approved/auto calls: executor on a thread, with timeout, wrapped in
a result envelope the model can rely on: {"ok": bool, "data"|"error", "duration_ms"}.
"""

from __future__ import annotations

import asyncio
import dataclasses
import hashlib
import json
import time

from ..config import Config
from ..actions import (
    ActionReceipt,
    ambiguous_receipt,
    blocked_receipt,
    dispatch_only_receipt,
    not_dispatched_failure_receipt,
    preparation_failure_receipt,
    uncertain_failure_receipt,
)
from ..events import Gate, ToolCall, ToolFinished
from .base import ExecutionContext, ToolError
from .native_actions import compile_action_request, safe_plan, validate_plan
from .registry import ToolSpec, computer_mutation_names
from .risk import argument_guard, gate_for, gate_for_prepared

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
        if expected and (
            not isinstance(value, expected)
            or prop.get("type") in {"integer", "number"} and isinstance(value, bool)
        ):
            return f"argument {key!r} should be {prop['type']}"
        if "enum" in prop and value not in prop["enum"]:
            return f"argument {key!r} should be one of {prop['enum']}"
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            if "exclusiveMinimum" in prop and value <= prop["exclusiveMinimum"]:
                return f"argument {key!r} should be greater than {prop['exclusiveMinimum']}"
            if "minimum" in prop and value < prop["minimum"]:
                return f"argument {key!r} should be at least {prop['minimum']}"
            if "maximum" in prop and value > prop["maximum"]:
                return f"argument {key!r} should be at most {prop['maximum']}"
            if "exclusiveMaximum" in prop and value >= prop["exclusiveMaximum"]:
                return f"argument {key!r} should be less than {prop['exclusiveMaximum']}"
        if isinstance(value, str):
            if "minLength" in prop and len(value) < prop["minLength"]:
                return f"argument {key!r} is too short"
            if "maxLength" in prop and len(value) > prop["maxLength"]:
                return f"argument {key!r} is too long"
        if prop.get("type") == "array":
            min_items = prop.get("minItems")
            if min_items is not None and len(value) < int(min_items):
                return f"argument {key!r} should have at least {min_items} item"
            item_schema = prop.get("items", {})
            item_expected = _TYPE_MAP.get(item_schema.get("type", ""))
            if item_expected and any(not isinstance(item, item_expected) for item in value):
                return f"argument {key!r} items should be {item_schema['type']}"
    effect = args.get("desired_effect")
    if effect is not None:
        if not isinstance(effect, dict):
            return "argument 'desired_effect' should be object"
        if set(effect) - {"mode", "predicates"}:
            return "desired_effect does not allow nested or free-form fields"
        if effect.get("mode", "all") not in {"all", "any"}:
            return "desired_effect mode should be 'all' or 'any'"
        predicates = effect.get("predicates")
        if not isinstance(predicates, list) or not 1 <= len(predicates) <= 3:
            return "desired_effect should contain 1 to 3 predicates"
        allowed = {
            "frontmost_bundle_equals",
            "window_count_delta",
            "window_title_equals",
            "window_title_changes",
            "element_exists",
            "element_disappears",
            "element_attribute_equals",
            "element_attribute_changes",
            "focused_element_equals",
            "text_contains",
            "text_hash_equals",
            "clipboard_hash_equals",
            "notification",
        }
        for predicate in predicates:
            if not isinstance(predicate, dict) or predicate.get("kind") not in allowed:
                return "desired_effect contains an unsupported predicate"
            if set(predicate) - {
                "kind", "ref", "attribute", "expected", "delta", "notification"
            }:
                return "desired_effect predicate contains a free-form field"
            expected_value = predicate.get("expected")
            if expected_value is not None and not isinstance(
                expected_value, (str, int, float, bool)
            ):
                return "desired_effect expected value must be scalar"
    return None


class ToolHarness:
    def __init__(self, registry: dict[str, ToolSpec], cfg: Config, ctx: ExecutionContext, executors: dict[str, object] | None = None):
        self.registry = registry
        self.cfg = cfg
        self.ctx = ctx
        self._executors = executors
        self.computer_mutations = computer_mutation_names(registry)

    def is_computer_mutation(self, name: str) -> bool:
        return name in self.computer_mutations

    def _safe_preview(self, spec: ToolSpec, args: dict) -> str:
        try:
            return clamp_preview(spec.preview(args))
        except Exception:
            try:
                return clamp_preview(spec.preview({}))
            except Exception:
                return f"Use tool: {spec.name}"

    async def prepare_call(
        self,
        call_id: str,
        name: str,
        arguments_json: str,
        provenance,
    ) -> ToolCall:
        if (
            not self.is_computer_mutation(name)
            or self._executors is not None
        ):
            return dataclasses.replace(
                self.gate(call_id, name, arguments_json),
                turn_id=provenance.turn_id,
                response_epoch=provenance.response_epoch,
                observation_epoch=provenance.observation_epoch,
            )

        spec = self.registry.get(name)
        if spec is None:
            return dataclasses.replace(
                self.gate(call_id, name, arguments_json),
                turn_id=provenance.turn_id,
                response_epoch=provenance.response_epoch,
                observation_epoch=provenance.observation_epoch,
            )
        try:
            args = json.loads(arguments_json) if arguments_json.strip() else {}
            if not isinstance(args, dict):
                raise ValueError("arguments must be a JSON object")
        except ValueError as exc:
            return ToolCall(
                call_id=call_id,
                name=name,
                arguments={},
                gate=Gate.BLOCKED,
                preview=f"{self._safe_preview(spec, {})} (invalid arguments)",
                block_reason=f"invalid_arguments: {exc}",
                turn_id=provenance.turn_id,
                response_epoch=provenance.response_epoch,
                observation_epoch=provenance.observation_epoch,
            )
        problem = validate_args(spec.parameters, args)
        if problem:
            return ToolCall(
                call_id=call_id,
                name=name,
                arguments=args,
                gate=Gate.BLOCKED,
                preview=f"{self._safe_preview(spec, args)} (invalid arguments)",
                block_reason=f"invalid_arguments: {problem}",
                turn_id=provenance.turn_id,
                response_epoch=provenance.response_epoch,
                observation_epoch=provenance.observation_epoch,
            )

        reason = argument_guard(name, args, self.cfg)
        if reason:
            return ToolCall(
                call_id=call_id,
                name=name,
                arguments=args,
                gate=Gate.BLOCKED,
                preview=self._safe_preview(spec, args),
                block_reason=reason,
                turn_id=provenance.turn_id,
                response_epoch=provenance.response_epoch,
                observation_epoch=provenance.observation_epoch,
                prepared_failure=preparation_failure_receipt(
                    outcome="blocked",
                    target=self._safe_preview(spec, args),
                    summary=reason,
                ).as_dict(),
            )

        bridge = self.ctx.ax_reader
        if bridge is None or not getattr(bridge, "app_present", False):
            reason = "native_app_unavailable: Conn.app is required for computer actions"
            return ToolCall(
                call_id=call_id,
                name=name,
                arguments=args,
                gate=Gate.BLOCKED,
                preview=self._safe_preview(spec, args),
                block_reason=reason,
                turn_id=provenance.turn_id,
                response_epoch=provenance.response_epoch,
                observation_epoch=provenance.observation_epoch,
                prepared_failure=preparation_failure_receipt(
                    outcome="failed",
                    target=self._safe_preview(spec, args),
                    summary=reason,
                ).as_dict(),
            )

        try:
            request = compile_action_request(spec, args, self.cfg)
        except (KeyError, TypeError, ValueError) as exc:
            reason = str(exc) or f"action_request_invalid: {type(exc).__name__}"
            return ToolCall(
                call_id=call_id,
                name=name,
                arguments=args,
                gate=Gate.BLOCKED,
                preview=self._safe_preview(spec, args),
                block_reason=reason,
                turn_id=provenance.turn_id,
                response_epoch=provenance.response_epoch,
                observation_epoch=provenance.observation_epoch,
                prepared_failure=preparation_failure_receipt(
                    outcome="blocked",
                    target=self._safe_preview(spec, args),
                    summary=reason,
                ).as_dict(),
            )
        response = await bridge.prepare_action(
            request,
            turn_id=provenance.turn_id,
            response_epoch=provenance.response_epoch,
            observation_epoch=provenance.observation_epoch,
        )
        problem = validate_plan(response.data)
        if problem:
            raw_failure = response.data if isinstance(response.data, dict) else {}
            reason = response.error or str(raw_failure.get("error") or problem)
            prepared_failure = preparation_failure_receipt(
                outcome="failed",
                target=self._safe_preview(spec, args),
                summary=reason,
            ).as_dict()
            outcome = raw_failure.get("outcome")
            if outcome in {"ambiguous", "blocked", "failed"}:
                prepared_failure = preparation_failure_receipt(
                    outcome=outcome,
                    target=self._safe_preview(spec, args),
                    summary=reason,
                ).as_dict()
            return ToolCall(
                call_id=call_id,
                name=name,
                arguments=args,
                gate=Gate.BLOCKED,
                preview=self._safe_preview(spec, args),
                block_reason=reason,
                turn_id=provenance.turn_id,
                response_epoch=provenance.response_epoch,
                observation_epoch=provenance.observation_epoch,
                prepared_failure=prepared_failure,
            )

        plan = safe_plan(response.data)
        try:
            gate, reason, preview = gate_for_prepared(
                name, spec.risk, args, plan, self.cfg
            )
        except Exception as exc:
            gate = Gate.BLOCKED
            reason = f"gating_failed: {type(exc).__name__}: {exc}"
            preview = None
        return ToolCall(
            call_id=call_id,
            name=name,
            arguments=args,
            gate=gate,
            preview=clamp_preview(preview or self._safe_preview(spec, args)),
            block_reason=reason,
            turn_id=provenance.turn_id,
            response_epoch=provenance.response_epoch,
            observation_epoch=provenance.observation_epoch,
            prepared_plan=plan,
        )

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

    @staticmethod
    def trace_arguments(name: str, args: dict) -> dict:
        safe = dict(args)
        if "text" in safe:
            text = str(safe.pop("text"))
            safe["text_length"] = len(text)
            safe["text_sha256"] = hashlib.sha256(text.encode()).hexdigest()
        return safe

    @staticmethod
    def _action_result(
        call: ToolCall,
        receipt: ActionReceipt,
        action_trace: dict | None = None,
    ) -> ToolFinished:
        return ToolFinished(
            call_id=call.call_id,
            ok=receipt.ok,
            output=json.dumps(receipt.as_dict()),
            action_outcome=receipt.outcome,
            turn_id=call.turn_id,
            response_epoch=call.response_epoch,
            observation_epoch=call.observation_epoch,
            execution_id=call.execution_id,
            action_trace=action_trace,
        )

    @staticmethod
    def _result(call: ToolCall, *, ok: bool, output: str) -> ToolFinished:
        return ToolFinished(
            call_id=call.call_id,
            ok=ok,
            output=output,
            turn_id=call.turn_id,
            response_epoch=call.response_epoch,
            observation_epoch=call.observation_epoch,
            execution_id=call.execution_id,
        )

    async def run(self, call: ToolCall) -> ToolFinished:
        started = time.monotonic()
        if call.gate is Gate.BLOCKED:
            if self.is_computer_mutation(call.name):
                return self._action_result(call, blocked_receipt(
                    target=call.preview,
                    summary=self.block_reason(call),
                    duration_ms=int((time.monotonic() - started) * 1000),
                ))
            envelope = {"ok": False, "error": self.block_reason(call), "duration_ms": int((time.monotonic() - started) * 1000)}
            return self._result(call, ok=False, output=json.dumps(envelope))
        spec = self.registry[call.name]
        problem = validate_args(spec.parameters, call.arguments)
        if problem:
            envelope = {"ok": False, "error": f"invalid_arguments: {problem}", "duration_ms": int((time.monotonic() - started) * 1000)}
            return self._result(call, ok=False, output=json.dumps(envelope))
        if (
            self._executors is None
            and call.name in {"computer_get_context", "computer_ax_snapshot"}
            and hasattr(self.ctx.ax_reader, "observe")
        ):
            return await self._run_native_observation(call, started)
        if self.is_computer_mutation(call.name) and call.prepared_plan is not None:
            return await self._run_prepared_action(call, spec, started)
        if (
            self.is_computer_mutation(call.name)
            and self._executors is None
            and self.ctx.ax is None
        ):
            return self._action_result(call, not_dispatched_failure_receipt(
                target=call.preview,
                strategy="native_bridge",
                duration_ms=int((time.monotonic() - started) * 1000),
                summary="native_plan_required",
            ))
        try:
            gate, reason, _preview = gate_for(call.name, spec.risk, call.arguments, self.cfg, self.ctx)
        except Exception as e:
            reason = str(e) or f"gating_failed: {type(e).__name__}"
            envelope = {"ok": False, "error": reason, "duration_ms": int((time.monotonic() - started) * 1000)}
            return self._result(call, ok=False, output=json.dumps(envelope))
        if gate is Gate.BLOCKED:
            if self.is_computer_mutation(call.name):
                return self._action_result(call, blocked_receipt(
                    target=call.preview,
                    summary=reason or "blocked_by_policy",
                    duration_ms=int((time.monotonic() - started) * 1000),
                ))
            envelope = {"ok": False, "error": reason or "blocked_by_policy", "duration_ms": int((time.monotonic() - started) * 1000)}
            return self._result(call, ok=False, output=json.dumps(envelope))
        executor = (self._executors or {}).get(call.name, spec.executor)
        mutating = self.is_computer_mutation(call.name)
        worker = asyncio.create_task(asyncio.to_thread(executor, call.arguments, self.ctx))
        try:
            if mutating:
                try:
                    data = await asyncio.wait_for(asyncio.shield(worker), timeout=spec.timeout_s)
                except TimeoutError:
                    # A Python thread cannot be revoked safely. Retain ownership
                    # and wait for its terminal result so Conn never reports a
                    # settled state while a hidden desktop effect can still run.
                    data = await worker
            else:
                data = await asyncio.wait_for(worker, timeout=spec.timeout_s)
            duration_ms = int((time.monotonic() - started) * 1000)
            if mutating:
                if isinstance(data, dict) and "outcome" in data:
                    receipt = ActionReceipt.from_dict(data)
                elif isinstance(data, dict) and "candidates" in data:
                    receipt = ambiguous_receipt(
                        target=call.preview,
                        data=data,
                        duration_ms=duration_ms,
                    )
                else:
                    strategy = "legacy_executor"
                    if isinstance(data, dict):
                        strategy = str(data.get("strategy") or data.get("lane") or strategy)
                    receipt = dispatch_only_receipt(
                        target=call.preview,
                        strategy=strategy,
                        duration_ms=duration_ms,
                    )
                return self._action_result(call, receipt)
            envelope = {"ok": True, "data": data, "duration_ms": int((time.monotonic() - started) * 1000)}
            return self._result(call, ok=True, output=json.dumps(envelope))
        except TimeoutError:
            envelope = {"ok": False, "error": f"timeout after {spec.timeout_s}s", "duration_ms": int((time.monotonic() - started) * 1000)}
        except ToolError as e:
            if mutating:
                return self._action_result(call, uncertain_failure_receipt(
                    target=call.preview,
                    strategy="legacy_executor",
                    duration_ms=int((time.monotonic() - started) * 1000),
                    summary=str(e),
                ))
            envelope = {"ok": False, "error": str(e), "duration_ms": int((time.monotonic() - started) * 1000)}
        except Exception as e:
            if mutating:
                return self._action_result(call, uncertain_failure_receipt(
                    target=call.preview,
                    strategy="legacy_executor",
                    duration_ms=int((time.monotonic() - started) * 1000),
                    summary=f"{type(e).__name__}: {e}",
                ))
            envelope = {"ok": False, "error": f"internal: {type(e).__name__}: {e}", "duration_ms": int((time.monotonic() - started) * 1000)}
        return self._result(call, ok=False, output=json.dumps(envelope))

    async def _run_prepared_action(
        self, call: ToolCall, spec: ToolSpec, started: float
    ) -> ToolFinished:
        plan = call.prepared_plan or {}
        try:
            gate, reason, _preview = gate_for_prepared(
                call.name, spec.risk, call.arguments, plan, self.cfg
            )
        except Exception as exc:
            gate = Gate.BLOCKED
            reason = f"gating_failed: {type(exc).__name__}: {exc}"
        if gate is Gate.BLOCKED:
            return self._action_result(call, blocked_receipt(
                target=str(plan.get("target") or call.preview),
                summary=reason or "blocked_by_policy",
                duration_ms=int((time.monotonic() - started) * 1000),
            ))

        fingerprint = plan.get("plan_fingerprint")
        bridge = self.ctx.ax_reader
        if not isinstance(fingerprint, str) or not fingerprint or bridge is None:
            return self._action_result(call, not_dispatched_failure_receipt(
                target=str(plan.get("target") or call.preview),
                strategy="native_bridge",
                duration_ms=int((time.monotonic() - started) * 1000),
                summary="native_plan_invalid",
            ))

        response = await bridge.execute_action(
            fingerprint,
            turn_id=call.turn_id or "",
            response_epoch=int(call.response_epoch or 0),
            observation_epoch=int(call.observation_epoch or 0),
        )
        duration_ms = int((time.monotonic() - started) * 1000)
        if isinstance(response.data, dict):
            if response.data.get("plan_fingerprint") != fingerprint:
                receipt = uncertain_failure_receipt(
                    target=str(plan.get("target") or call.preview),
                    strategy="native_bridge",
                    duration_ms=duration_ms,
                    summary="invalid_native_receipt: plan_fingerprint_mismatch",
                )
                return self._action_result(
                    call,
                    receipt,
                    self._native_action_trace(call, plan, response.data, receipt),
                )
            try:
                receipt = ActionReceipt.from_dict(response.data)
            except (KeyError, TypeError, ValueError) as exc:
                receipt = uncertain_failure_receipt(
                    target=str(plan.get("target") or call.preview),
                    strategy="native_bridge",
                    duration_ms=duration_ms,
                    summary=f"invalid_native_receipt: {type(exc).__name__}",
                )
            return self._action_result(
                call,
                receipt,
                self._native_action_trace(call, plan, response.data, receipt),
            )

        summary = response.error or "native_bridge_no_result"
        if response.request_sent:
            receipt = uncertain_failure_receipt(
                target=str(plan.get("target") or call.preview),
                strategy="native_bridge",
                duration_ms=duration_ms,
                summary=summary,
            )
        else:
            receipt = not_dispatched_failure_receipt(
                target=str(plan.get("target") or call.preview),
                strategy="native_bridge",
                duration_ms=duration_ms,
                summary=summary,
            )
        return self._action_result(call, receipt)

    @staticmethod
    def _native_action_trace(
        call: ToolCall, plan: dict, raw: dict, receipt: ActionReceipt
    ) -> dict:
        return {
            "turn_id": call.turn_id,
            "response_epoch": call.response_epoch,
            "observation_epoch": call.observation_epoch,
            "plan_fingerprint": raw.get("plan_fingerprint")
            or plan.get("plan_fingerprint"),
            "approval_fingerprint": (
                plan.get("plan_fingerprint") if call.gate is Gate.CONFIRM else None
            ),
            "before_digest": raw.get("before_digest")
            or plan.get("before_digest"),
            "target_fingerprint": raw.get("target_fingerprint")
            or plan.get("target_fingerprint"),
            "authorized_strategies": list(
                plan.get("authorized_strategies") or []
            ),
            "selected_strategy": receipt.strategy,
            "dispatch_state": receipt.dispatch_state.value,
            "native_error": raw.get("native_error"),
            "notifications": list(raw.get("notifications") or [])[:16],
            "predicates": list(plan.get("predicates") or [])[:3],
            "evidence": [item.as_dict() for item in receipt.evidence],
            "after_digest": raw.get("after_digest"),
            "outcome": receipt.outcome.value,
            "retry_safe": receipt.retry_safe,
            "duration_ms": receipt.duration_ms,
            "latency_spans": raw.get("latency_spans")
            if isinstance(raw.get("latency_spans"), dict)
            else {},
        }

    async def _run_native_observation(
        self, call: ToolCall, started: float
    ) -> ToolFinished:
        response = await self.ctx.ax_reader.observe(
            turn_id=call.turn_id or "system",
            observation_epoch=int(call.observation_epoch or 0),
            query=call.arguments.get("query"),
            denied_bundles=list(self.cfg.ax.deny_bundles),
        )
        duration_ms = int((time.monotonic() - started) * 1000)
        if not isinstance(response.data, dict):
            envelope = {
                "ok": False,
                "error": response.error or "native_observation_unavailable",
                "duration_ms": duration_ms,
            }
            return self._result(call, ok=False, output=json.dumps(envelope))
        data = dict(response.data)
        if bool(data.get("denied")):
            envelope = {
                "ok": False,
                "error": "denied_bundle: semantic observation excluded",
                "duration_ms": duration_ms,
            }
            return self._result(call, ok=False, output=json.dumps(envelope))
        data.pop("selected_text", None)
        if call.name == "computer_get_context":
            data = {
                key: data.get(key)
                for key in (
                    "app",
                    "app_name",
                    "bundle_id",
                    "window_id",
                    "window_title",
                    "snapshot_id",
                    "observation_id",
                    "accessibility",
                )
                if key in data
            }
            data["source"] = "app"
        envelope = {"ok": True, "data": data, "duration_ms": duration_ms}
        return self._result(call, ok=True, output=json.dumps(envelope))
