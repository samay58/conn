"""Authenticated native observation and action RPC for Conn.app."""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import os
import secrets
from dataclasses import dataclass
from typing import Callable

from .observations import ObservationQuery

from .events import new_id

APP_HEALTH_PURPOSE = "conn-app-health-v1"
APP_WEBSOCKET_PURPOSE = "conn-app-websocket-v1"
DAEMON_WEBSOCKET_PURPOSE = "conn-daemon-websocket-v1"
CONSOLE_WEBSOCKET_PURPOSE = "conn-console-websocket-v1"


@dataclass(frozen=True, slots=True)
class NativeRpcResult:
    data: object | None
    request_sent: bool
    error: str | None = None


@dataclass(frozen=True, slots=True)
class _PendingRequest:
    future: asyncio.Future
    sequence: int
    turn_id: str
    observation_epoch: int


_DISCONNECTED = object()


def hmac_proof(secret: str, purpose: str, challenge: str) -> str:
    payload = f"{purpose}:{challenge}".encode()
    return hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()


def verify_hmac_proof(secret: str, purpose: str, challenge: str,
                      proof: str | None) -> bool:
    if not proof:
        return False
    expected = hmac_proof(secret, purpose, challenge)
    return secrets.compare_digest(proof, expected)


def valid_challenge(challenge: object) -> bool:
    if not isinstance(challenge, str) or not 16 <= len(challenge) <= 256:
        return False
    return all(
        character.isascii() and (character.isalnum() or character in "-_")
        for character in challenge
    )


class AxBridge:
    def __init__(self, timeout_s: float = 2.0, expected_token: str | None = None):
        self.timeout_s = timeout_s
        environment_token = os.environ.pop("CONN_BRIDGE_TOKEN", None)
        self.expected_token = expected_token if expected_token is not None else environment_token
        self._loop: asyncio.AbstractEventLoop | None = None
        self._publish: Callable[[dict], None] | None = None
        self._pending: dict[str, _PendingRequest] = {}
        self._active_client_id: str | None = None
        self._sequence = 0
        self.rejected_replies = 0

    def bind(self, loop: asyncio.AbstractEventLoop, publish: Callable[[dict], None]) -> None:
        self._loop = loop
        self._publish = publish

    def authenticate_app_proof(self, challenge: str, proof: str | None,
                               client_id: str) -> bool:
        if not self.expected_token or not valid_challenge(challenge):
            return False
        if not verify_hmac_proof(
            self.expected_token, APP_WEBSOCKET_PURPOSE, challenge, proof
        ):
            return False
        if self._active_client_id not in (None, client_id):
            return False
        self._active_client_id = client_id
        return True

    def app_detached(self, client_id: str | None = None) -> None:
        if client_id is not None and client_id != self._active_client_id:
            return
        self._active_client_id = None
        for pending in self._pending.values():
            if not pending.future.done():
                pending.future.set_result(_DISCONNECTED)
        self._pending.clear()

    @property
    def app_present(self) -> bool:
        return self._active_client_id is not None

    def request_context_sync(self) -> dict | None:
        data = self._round_trip(self.request())
        return data if isinstance(data, dict) else None

    def request_action_sync(self, op: str, params: dict) -> object | None:
        return self._round_trip(self.request_action(op, params))

    def _round_trip(self, coro) -> object | None:
        loop = self._loop
        if loop is None or self._publish is None or not self.app_present:
            coro.close()
            return None
        future = asyncio.run_coroutine_threadsafe(coro, loop)
        try:
            return future.result(self.timeout_s + 0.5)
        except Exception:
            future.cancel()
            return None

    async def request(self) -> dict | None:
        data = await self._ask({"type": "ax_read"}, "axread")
        return data if isinstance(data, dict) else None

    async def request_action(self, op: str, params: dict) -> object | None:
        return await self._ask(
            {"type": "ax_action", "op": op, "params": params}, "axact")

    async def observe(
        self,
        *,
        turn_id: str,
        observation_epoch: int,
        query: ObservationQuery | str | None = None,
        denied_bundles: list[str] | None = None,
    ) -> NativeRpcResult:
        if isinstance(query, ObservationQuery):
            wire_query = query.as_wire()
        else:
            wire_query = ObservationQuery.from_tool_arguments({"query": query}).as_wire()
        wire_query["denied_bundles"] = list(denied_bundles or [])
        return await self._ask_detailed(
            {
                "type": "ax_action",
                "op": "observe",
                "params": {
                    "query": wire_query,
                    "include_selected_text": False,
                    "turn_id": turn_id,
                    "observation_epoch": observation_epoch,
                },
                "turn_id": turn_id,
                "observation_epoch": observation_epoch,
            },
            "axobs",
        )

    async def observe_visual(
        self,
        *,
        turn_id: str,
        observation_epoch: int,
        enabled: bool,
        denied_bundles: list[str] | None = None,
    ) -> NativeRpcResult:
        return await self._ask_detailed(
            {
                "type": "ax_action",
                "op": "observe_visual",
                "params": {
                    "enabled": enabled,
                    "denied_bundles": list(denied_bundles or []),
                    "turn_id": turn_id,
                    "observation_epoch": observation_epoch,
                },
                "turn_id": turn_id,
                "observation_epoch": observation_epoch,
            },
            "axvisual",
        )

    async def capability_report(
        self,
        *,
        turn_id: str,
        observation_epoch: int,
        denied_bundles: list[str] | None = None,
    ) -> NativeRpcResult:
        """Descriptive intent capabilities for the current app, epoch-bound.
        Reports carry no plan fingerprints and cannot authorize anything."""
        return await self._ask_detailed(
            {
                "type": "ax_action",
                "op": "capability_report",
                "params": {
                    "turn_id": turn_id,
                    "observation_epoch": observation_epoch,
                    "denied_bundles": list(denied_bundles or []),
                },
                "turn_id": turn_id,
                "observation_epoch": observation_epoch,
            },
            "axcap",
        )

    async def prepare_action(
        self,
        request: dict,
        *,
        turn_id: str,
        response_epoch: int,
        observation_epoch: int,
        navigation_generation: int | None = None,
    ) -> NativeRpcResult:
        params = {
            "request": request,
            "turn_id": turn_id,
            "response_epoch": response_epoch,
            "observation_epoch": observation_epoch,
        }
        if navigation_generation is not None:
            params["navigation_generation"] = navigation_generation
        return await self._ask_detailed(
            {
                "type": "ax_action",
                "op": "prepare_action",
                "params": params,
                "turn_id": turn_id,
                "observation_epoch": observation_epoch,
            },
            "axplan",
        )

    TRANSPORT_MARGIN_S = 1.6

    def effective_timeout_s(self, timeout_ms: int | None) -> float:
        """The Python deadline for an execute is the authorized native
        budget plus bounded transport margin, never shorter: a slow valid
        action must not become a premature bridge timeout that strands a
        finished native receipt."""
        if not isinstance(timeout_ms, int) or timeout_ms <= 0:
            return self.timeout_s
        return max(self.timeout_s, timeout_ms / 1000 + self.TRANSPORT_MARGIN_S)

    async def execute_action(
        self,
        plan_fingerprint: str,
        *,
        turn_id: str,
        response_epoch: int,
        observation_epoch: int,
        timeout_ms: int | None = None,
        navigation_generation: int | None = None,
    ) -> NativeRpcResult:
        params = {
            "plan_fingerprint": plan_fingerprint,
            "turn_id": turn_id,
            "response_epoch": response_epoch,
            "observation_epoch": observation_epoch,
        }
        if navigation_generation is not None:
            params["navigation_generation"] = navigation_generation
        return await self._ask_detailed(
            {
                "type": "ax_action",
                "op": "execute_action",
                "params": params,
                "turn_id": turn_id,
                "observation_epoch": observation_epoch,
            },
            "axexec",
            timeout_s=self.effective_timeout_s(timeout_ms),
        )

    async def _ask(self, message: dict, id_prefix: str) -> object | None:
        return (await self._ask_detailed(message, id_prefix)).data

    async def _ask_detailed(
        self, message: dict, id_prefix: str, timeout_s: float | None = None
    ) -> NativeRpcResult:
        if self._loop is None or self._publish is None or not self.app_present:
            return NativeRpcResult(None, False, "native_app_unavailable")
        request_id = new_id(id_prefix)
        self._sequence += 1
        sequence = self._sequence
        turn_id = str(message.get("turn_id", "system"))
        observation_epoch = int(message.get("observation_epoch", 0))
        future: asyncio.Future = self._loop.create_future()
        self._pending[request_id] = _PendingRequest(
            future=future,
            sequence=sequence,
            turn_id=turn_id,
            observation_epoch=observation_epoch,
        )
        request_sent = False
        try:
            self._publish({
                **message,
                "request_id": request_id,
                "turn_id": turn_id,
                "observation_epoch": observation_epoch,
                "sequence": sequence,
            })
            request_sent = True
            data = await asyncio.wait_for(future, timeout_s or self.timeout_s)
            if data is _DISCONNECTED:
                return NativeRpcResult(None, True, "native_app_disconnected")
            return NativeRpcResult(data, True)
        except asyncio.TimeoutError:
            return NativeRpcResult(None, request_sent, "native_bridge_timeout")
        except Exception as exc:
            return NativeRpcResult(
                None,
                request_sent,
                f"native_bridge_error: {type(exc).__name__}",
            )
        finally:
            self._pending.pop(request_id, None)

    def resolve(self, request_id: str, data: object, *, client_id: str | None = None,
                sequence: int | None = None, turn_id: str | None = None,
                observation_epoch: int | None = None) -> None:
        """Called on the loop when the app answers. Unknown ids (a late answer
        after timeout) are dropped. Payload validation is the requester's
        job: reads need a dict, actions may carry bools or trees."""
        if self._active_client_id is None or client_id != self._active_client_id:
            self.rejected_replies += 1
            return
        pending = self._pending.get(request_id)
        if pending is None:
            return
        if (
            sequence != pending.sequence
            or turn_id != pending.turn_id
            or observation_epoch != pending.observation_epoch
        ):
            self.rejected_replies += 1
            return
        if not pending.future.done():
            pending.future.set_result(data)
