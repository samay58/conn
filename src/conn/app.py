"""Composition root. One asyncio loop owns everything: machine transitions,
adapter I/O, tool execution, approvals, traces, cost, and console fan-out.

The machine decides; this file executes. The budget gate lives here because
response.create is the only spend trigger and every one flows through _exec.
"""

from __future__ import annotations

import asyncio
import shutil
import time
from typing import Callable

from .approval import ApprovalManager
from .ax_bridge import AxBridge
from .config import Config
from .cost import CostMeter
from .events import (
    ApprovalDecision, BudgetOverride, BudgetTripped, CancelResponse,
    ClearInput, CloseMic, Command, CommitInput, CreateResponse, EndSession,
    ExecTool, FlushPlayback, MachineInput, ModelSpeaking, OpenMic,
    PlaybackDrained, PttDown, PttUp, QueueApproval, ResetTick, ResponseDone,
    RejectInput, ResponseCancelled, SendText, SendToolResult, TextCommand,
    ToolFinished, ToolProposed, UserStop, WatchdogTick, WsFailed,
    WsReconnected, mono_ms, new_id,
)
from .realtime.base import (
    RealtimeAdapter, RtAudioDelta, RtClosed, RtError, RtInputTranscript,
    RtResponseCancelled, RtResponseDone, RtSessionReady, RtTextDelta,
    RtToolCall, RtTranscriptDelta,
)
from .state import Phase, SessionStateMachine
from .tools.harness import ToolHarness
from .trace import TraceWriter, write_receipt

WATCHDOG_INTERVAL_S = 60


class ConnApp:
    def __init__(self, cfg: Config, adapter: RealtimeAdapter, harness: ToolHarness,
                 audio=None):
        self.cfg = cfg
        self.adapter = adapter
        self.harness = harness
        self.audio = audio  # None in demo/text mode
        self.session_id = new_id("session")
        self.machine = SessionStateMachine(
            tap_threshold_ms=cfg.session.tap_threshold_ms,
            watchdog_timeout_s=cfg.session.watchdog_timeout_s)
        self.trace = TraceWriter(cfg.data_dir, self.session_id)
        self.trace.subscribe(lambda e: self.publish({"type": "trace", "event": e}))
        self.cost = CostMeter(pricing=cfg.pricing, budget=cfg.budget)
        self.approvals = ApprovalManager(on_timeout=self.dispatch_soon)
        self.ax_bridge = AxBridge()
        self.harness.ctx.ax_reader = self.ax_bridge
        self.publisher: Callable[[dict], None] | None = None
        self._pump_task: asyncio.Task | None = None
        self._spoke_this_response = False
        self._warned_budget = False
        self._closing = False
        self._idle_timer: asyncio.TimerHandle | None = None
        self._watchdog_timer: asyncio.TimerHandle | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._turn_count = 0
        self._phase_since = time.monotonic()
        self._current_response_id: str | None = None

    # ---------- lifecycle ----------

    async def start(self) -> None:
        self._loop = asyncio.get_running_loop()
        self.ax_bridge.bind(self._loop, self.publish)
        self.trace.log("session_start", session_id=self.session_id,
                       model=self.cfg.realtime.model, demo=not self.adapter_is_live())
        await self.adapter.connect()
        self._pump_task = asyncio.ensure_future(self._pump())
        self._arm_idle_timer()
        self._arm_watchdog_timer()
        self.publish_state()
        await self.publish_ax_grants()

    async def publish_ax_grants(self) -> None:
        """T2 grant preflight: both lanes' Accessibility state, traced and
        pushed to the surfaces at session start and on app attach, so a dead
        grant is visible before the first command instead of mid-command."""
        from .identity import grant_target, python_ax_trusted

        trusted = python_ax_trusted()
        python_ax = "unknown" if trusted is None else ("granted" if trusted else "not_granted")
        app_ax = "unattached"
        if self.ax_bridge.app_present:
            payload = await self.ax_bridge.request()
            if isinstance(payload, dict):
                app_ax = "granted" if payload.get("accessibility") == "granted" else "not_granted"
        grants = {"python_ax": python_ax, "app_ax": app_ax,
                  "python_grant_target": grant_target()}
        self.trace.log("ax_grants", **grants)
        self.publish({"type": "ax_grants", **grants})

    async def stop(self) -> None:
        self._closing = True
        self.approvals.clear()
        if self._pump_task:
            self._pump_task.cancel()
        if self._watchdog_timer:
            self._watchdog_timer.cancel()
        if self.adapter.connected:
            await self.adapter.close()
        receipt = self.cost.receipt()
        receipt["final"] = True
        path = self.cost.write_receipt_snapshot(self.cfg.data_dir, self.session_id, final=True,
                                                trace_path=self.trace.path)
        self.trace.log("session_end", receipt=receipt, receipt_path=str(path))
        if not self.cfg.screenshots.keep:
            shutil.rmtree(self.harness.ctx.screenshot_dir, ignore_errors=True)
        self.publish({"type": "receipt", "receipt": receipt})

    def adapter_is_live(self) -> bool:
        return type(self.adapter).__name__ == "OpenAIRealtimeAdapter"

    async def new_session(self) -> None:
        """Fresh session: receipt written, upstream context dropped, meters reset."""
        await self.stop()
        self._closing = False
        self.session_id = new_id("session")
        self.machine = SessionStateMachine(
            tap_threshold_ms=self.cfg.session.tap_threshold_ms,
            watchdog_timeout_s=self.cfg.session.watchdog_timeout_s)
        self.trace = TraceWriter(self.cfg.data_dir, self.session_id)
        self.trace.subscribe(lambda e: self.publish({"type": "trace", "event": e}))
        self.cost = CostMeter(pricing=self.cfg.pricing, budget=self.cfg.budget)
        self._warned_budget = False
        self._spoke_this_response = False
        self._turn_count = 0
        self._phase_since = time.monotonic()
        self._current_response_id = None
        await self.start()

    # ---------- console / hotkey entry points ----------

    def dispatch_soon(self, ev: MachineInput) -> None:
        """Thread-safe entry for hotkey callbacks and timers."""
        loop = self._loop
        if loop is None:
            return
        loop.call_soon_threadsafe(lambda: asyncio.ensure_future(self.dispatch(ev)))

    async def on_ptt_down(self, client_ts_ms: int | None = None, source: str = "hotkey") -> None:
        self.trace.log("ptt_down", client_ts_ms=client_ts_ms, source=source)
        await self._ensure_connected()
        await self.dispatch(PttDown(client_ts_ms=client_ts_ms))

    async def on_ptt_up(self, client_ts_ms: int | None = None, source: str = "hotkey") -> None:
        self.trace.log("ptt_up", client_ts_ms=client_ts_ms, source=source)
        await self.dispatch(PttUp(client_ts_ms=client_ts_ms))

    async def on_text(self, text: str) -> None:
        text = text.strip()
        if not text:
            return
        await self._ensure_connected()
        self.trace.log("input", mode="text", text=text)
        self.publish({"type": "user_transcript", "text": text})
        await self.dispatch(TextCommand(text=text))

    async def on_approval(self, call_id: str, approved: bool,
                          client_ts_ms: int | None = None) -> None:
        latency = self.approvals.decide(call_id)
        self.trace.log("approval_decision", call_id=call_id, approved=approved,
                       latency_s=round(latency, 2) if latency is not None else None,
                       client_ts_ms=client_ts_ms)
        await self.dispatch(ApprovalDecision(call_id=call_id, approved=approved))

    async def on_stop(self, client_ts_ms: int | None = None) -> None:
        self.trace.log("kill_switch", client_ts_ms=client_ts_ms)
        await self.dispatch(UserStop())

    async def on_budget_override(self) -> None:
        self.cost.overridden = True
        self.trace.log("budget_override")
        await self.dispatch(BudgetOverride())

    async def on_ui_ack(self, moment: str, client_ts_ms: int | None) -> None:
        """Client reports the render pass that first showed a state. Trace
        only, no machine input: the daemon does not act on UI paint timing."""
        self.trace.log("ui_ack", moment=moment, client_ts_ms=client_ts_ms)

    # ---------- machine loop ----------

    async def dispatch(self, ev: MachineInput) -> None:
        if isinstance(ev, PlaybackDrained):
            self.trace.log("audio_silent", after="drain")
        old_phase = self.machine.phase
        cmds = self.machine.handle(ev)
        if self.machine.phase != old_phase:
            self._on_phase_changed(old_phase, self.machine.phase)
        for cmd in cmds:
            if not await self._exec(cmd):
                break
        self._arm_idle_timer()
        self.publish_state()

    def _on_phase_changed(self, old: Phase, new: Phase) -> None:
        is_turn_start = (new is Phase.LISTENING
                        or (new is Phase.THINKING and old in (Phase.IDLE, Phase.DONE)))
        if is_turn_start:
            self._turn_count += 1
        self.trace.log("phase_change", from_phase=old.value, to_phase=new.value,
                       turn=self._turn_count)
        self._phase_since = time.monotonic()

    async def _exec(self, cmd: Command) -> bool:
        """Executes one machine command. Returns False when an adapter send
        failed and the disconnect path already ran, so dispatch() can stop
        feeding the rest of a now-stale command batch to a dead or reset
        adapter."""
        ok = True
        match cmd:
            case ClearInput():
                if self.adapter.connected:
                    await self.adapter.clear_input()
            case OpenMic():
                if self.audio:
                    self.audio.gate_open()
            case CloseMic():
                if self.audio:
                    self.audio.gate_close()
            case CommitInput():
                ok = await self._send_or_disconnect(self.adapter.commit_input())
            case CreateResponse():
                ok = await self._create_response_gated()
            case CancelResponse():
                if self.adapter.connected:
                    await self.adapter.cancel_response()
            case FlushPlayback():
                if self.audio:
                    self.audio.flush()
                self.trace.log("audio_silent", after="flush")
            case SendText(text=text):
                ok = await self._send_or_disconnect(self.adapter.send_text(text))
            case ExecTool(call=call):
                self.trace.log("tool_exec", call_id=call.call_id, name=call.name)
                asyncio.ensure_future(self._run_tool(call))
            case QueueApproval(call=call):
                self.approvals.ask(call)
                self.trace.log("approval_asked", call_id=call.call_id,
                               name=call.name, preview=call.preview)
            case SendToolResult(call_id=call_id, ok=tool_ok, output=output):
                self.trace.log("tool_result_sent", call_id=call_id, ok=tool_ok)
                ok = await self._send_or_disconnect(
                    self.adapter.send_tool_result(call_id, output))
            case EndSession(reason=reason):
                self.trace.log("upstream_session_end", reason=reason)
                if self.adapter.connected:
                    await self.adapter.close()
            case RejectInput(reason=reason):
                self.publish({"type": "reject_input", "reason": reason})
        return ok

    async def _send_or_disconnect(self, coro) -> bool:
        """Wraps an adapter send. A failure here means the socket is dead;
        raising it into the caller would leave the machine wedged in whatever
        phase it was mid-transition to (Defect 3), so route it through the
        same disconnect/reconnect path a fatal upstream event would take."""
        try:
            await coro
            return True
        except Exception as e:
            self.trace.log("adapter_send_failed", error=str(e))
            await self._handle_disconnect(str(e))
            return False

    async def _create_response_gated(self) -> bool:
        if self.cfg.budget.hard_stop and self.cost.would_exceed():
            self.trace.log("budget_hold", spent_usd=round(self.cost.spent_usd, 4),
                           cap_usd=self.cfg.budget.session_cap_usd)
            self.publish({"type": "toast", "level": "warn",
                          "text": f"Budget hold: ${self.cost.spent_usd:.2f} of "
                                  f"${self.cfg.budget.session_cap_usd:.2f} cap"})
            await self.dispatch(BudgetTripped())
            return True
        self._spoke_this_response = False
        self._current_response_id = new_id("response")
        return await self._send_or_disconnect(self.adapter.create_response())

    async def _run_tool(self, call) -> None:
        result = await self.harness.run(call)
        self.cost.tool_calls += 1
        if call.name == "computer_screenshot" and result.ok:
            self.cost.screenshots += 1
        self.trace.log("tool_result", call_id=call.call_id, name=call.name,
                       ok=result.ok, output=result.output[:500])
        await self.dispatch(result)

    # ---------- adapter event pump ----------

    async def _pump(self) -> None:
        try:
            async for ev in self.adapter.events():
                await self._on_rt_event(ev)
        except asyncio.CancelledError:
            pass

    async def _on_rt_event(self, ev) -> None:
        match ev:
            case RtSessionReady(session_id=sid):
                self.trace.log("upstream_ready", upstream_id=sid)
            case RtAudioDelta(pcm=pcm):
                if self.audio:
                    self.audio.play(pcm)
                await self._mark_speaking("audio")
            case RtTranscriptDelta(text=text):
                self.publish({"type": "transcript_delta", "text": text})
                await self._mark_speaking("audio")
            case RtTextDelta(text=text):
                self.publish({"type": "transcript_delta", "text": text})
                await self._mark_speaking("text")
            case RtInputTranscript(text=text):
                self.trace.log("input", mode="voice", text=text)
                self.publish({"type": "user_transcript", "text": text})
            case RtToolCall(call_id=call_id, name=name, arguments_json=argv):
                call = self.harness.gate(call_id, name, argv)
                self.trace.log("tool_proposed", call_id=call_id, name=name,
                               gate=call.gate.value, preview=call.preview,
                               arguments=call.arguments,
                               block_reason=call.block_reason)
                await self.dispatch(ToolProposed(call=call))
            case RtResponseDone(usage=usage, had_tool_calls=had_calls):
                if usage:
                    turn = self.cost.ingest(usage)
                    self.trace.log("response_done", usage=usage,
                                   turn_usd=round(turn.usd, 5),
                                   spent_usd=round(self.cost.spent_usd, 4))
                    self.publish({"type": "cost", "receipt": self.cost.receipt()})
                    self._maybe_warn_budget()
                self.cost.write_receipt_snapshot(self.cfg.data_dir, self.session_id, final=False,
                                                 trace_path=self.trace.path)
                await self.dispatch(ResponseDone(had_tool_calls=had_calls))
                await self._maybe_drain()
            case RtResponseCancelled():
                await self.dispatch(ResponseCancelled())
            case RtError(message=msg, fatal=fatal):
                self.trace.log("upstream_error", message=msg, fatal=fatal)
                if fatal:
                    await self._handle_disconnect(msg)
            case RtClosed(reason=reason):
                if not self._closing:
                    await self._handle_disconnect(reason)

    async def _mark_speaking(self, modality: str) -> None:
        if not self._spoke_this_response:
            self._spoke_this_response = True
            self.trace.log("model_delta", response_id=self._current_response_id,
                           modality=modality)
            await self.dispatch(ModelSpeaking())

    async def _maybe_drain(self) -> None:
        """In demo/text mode there is no playback, so drain immediately. With
        live audio the playback module reports drain itself."""
        if self.audio is None and self.machine.phase is Phase.SPEAKING:
            await self.dispatch(PlaybackDrained())
        if self.machine.phase is Phase.DONE and self._loop:
            self._loop.call_later(self.cfg.session.done_flash_ms / 1000,
                                  lambda: self.dispatch_soon(ResetTick()))

    def _maybe_warn_budget(self) -> None:
        if not self._warned_budget and self.cost.should_warn():
            self._warned_budget = True
            self.publish({"type": "toast", "level": "warn",
                          "text": f"Session at ${self.cost.spent_usd:.2f} "
                                  f"(warn threshold ${self.cfg.budget.warn_at_usd:.2f})"})

    async def _handle_disconnect(self, reason: str) -> None:
        await self.dispatch(WsFailed(reason=reason))
        self.publish({"type": "toast", "level": "error",
                      "text": "Connection lost. Reconnecting with a fresh session; "
                              "conversation context was reset."})
        if self.adapter.connected:
            try:
                await self.adapter.close()
            except Exception as e:
                self.trace.log("adapter_close_failed", error=str(e))
        for delay in (0.5, 1.0, 2.0, 4.0):
            try:
                await self.adapter.connect()
                self._pump_task = asyncio.ensure_future(self._pump())
                await self.dispatch(WsReconnected())
                self.trace.log("upstream_reconnected")
                return
            except Exception as e:
                self.trace.log("reconnect_failed", error=str(e))
                await asyncio.sleep(delay)
        self.publish({"type": "toast", "level": "error",
                      "text": "Could not reconnect. Press stop and restart."})

    async def _ensure_connected(self) -> None:
        if not self.adapter.connected:
            await self.adapter.connect()
            self._pump_task = asyncio.ensure_future(self._pump())
            self.trace.log("upstream_reconnected", lazy=True)

    # ---------- idle timeout ----------

    def _arm_idle_timer(self) -> None:
        if self._loop is None:
            return
        if self._idle_timer:
            self._idle_timer.cancel()
        self._idle_timer = self._loop.call_later(
            self.cfg.session.idle_timeout_s, self._idle_fire)

    def _idle_fire(self) -> None:
        if self.machine.phase is Phase.IDLE and self.adapter.connected:
            self.trace.log("idle_timeout")
            if self._loop:
                asyncio.ensure_future(self.adapter.close())

    # ---------- stuck-phase watchdog ----------

    def _arm_watchdog_timer(self) -> None:
        if self._loop is None:
            return
        self._watchdog_timer = self._loop.call_later(
            WATCHDOG_INTERVAL_S, self._watchdog_fire)

    def _watchdog_fire(self) -> None:
        self.dispatch_soon(WatchdogTick(ts_ms=mono_ms()))
        self._arm_watchdog_timer()

    # ---------- health ----------

    def phase_age_s(self) -> float:
        """Seconds since the machine entered its current phase, monotonic so
        it never jumps on wall-clock adjustments."""
        return time.monotonic() - self._phase_since

    # ---------- console fan-out ----------

    def publish(self, msg: dict) -> None:
        if self.publisher:
            self.publisher(msg)

    def publish_state(self) -> None:
        snap = self.machine.snapshot()
        snap["type"] = "state"
        snap["session_id"] = self.session_id
        snap["connected"] = self.adapter.connected
        snap["spent_usd"] = round(self.cost.spent_usd, 4)
        self.publish(snap)
