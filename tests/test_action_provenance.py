import asyncio
import dataclasses
import json
import threading

import pytest

from conn.actions import (
    ActionOutcome,
    simulated_verified_receipt,
)
from conn.events import (
    ApprovalDecision,
    ExecTool,
    Gate,
    SendToolResult,
    TextCommand,
    ToolCall,
    ToolFinished,
    ToolProposed,
    UserStop,
)
from conn.realtime.base import RtResponseCreated, RtTextDelta, RtToolCall
from conn.state import CallStatus, Phase, SessionStateMachine
from conn.tools.registry import build_registry, computer_mutation_names


MUTATIONS = computer_mutation_names(build_registry())


def call(call_id: str, name: str) -> ToolCall:
    return ToolCall(call_id, name, {}, Gate.AUTO, name)


def test_every_registered_state_changing_tool_is_serialized() -> None:
    from conn.tools.registry import build_registry
    from conn.tools.risk import RiskLevel

    registry = build_registry()
    state_changing = {name for name, spec in registry.items()
                      if spec.risk is not RiskLevel.READ}
    computer_mutations = {name for name, spec in registry.items()
                          if spec.computer_mutation}

    assert state_changing <= computer_mutations
    assert all(registry[name].semantic_operation for name in computer_mutations)


def test_tool_metadata_rejects_half_declared_semantic_mutation() -> None:
    from conn.tools.registry import build_registry

    with pytest.raises(ValueError, match="semantic operation"):
        dataclasses.replace(
            build_registry()["wait_for_user"], semantic_operation="press"
        )


def test_only_first_mutation_in_response_can_dispatch() -> None:
    machine = SessionStateMachine(computer_mutations=MUTATIONS)
    machine.phase = Phase.THINKING

    first = machine.handle(ToolProposed(call("c1", "app_switch")))
    second = machine.handle(ToolProposed(call("c2", "app_menu")))

    assert any(isinstance(command, ExecTool) for command in first)
    assert not any(isinstance(command, ExecTool) for command in second)
    assert any(isinstance(command, SendToolResult) for command in second)
    assert machine.ledger["c2"].status is CallStatus.BLOCKED
    assert "sequential_action_required" in (machine.ledger["c2"].output or "")


def test_serialization_uses_registry_mutation_metadata(cfg, ctx) -> None:
    from conn.tools.harness import ToolHarness
    from conn.tools.registry import build_registry

    registry = build_registry()
    registry["wait_for_user"] = dataclasses.replace(
        registry["wait_for_user"],
        computer_mutation=True,
        semantic_operation="test_mutation",
    )
    harness = ToolHarness(registry, cfg, ctx, executors={})
    machine = SessionStateMachine(computer_mutations=harness.computer_mutations)
    machine.phase = Phase.THINKING

    first = machine.handle(ToolProposed(call("c1", "wait_for_user")))
    second = machine.handle(ToolProposed(call("c2", "wait_for_user")))

    assert any(isinstance(command, ExecTool) for command in first)
    assert not any(isinstance(command, ExecTool) for command in second)
    assert "sequential_action_required" in (machine.ledger["c2"].output or "")


def test_duplicate_tool_call_id_never_dispatches_twice() -> None:
    machine = SessionStateMachine(computer_mutations=MUTATIONS)
    machine.phase = Phase.THINKING

    first = machine.handle(ToolProposed(call("same", "app_switch")))
    repeated = machine.handle(ToolProposed(call("same", "app_switch")))

    assert any(isinstance(command, ExecTool) for command in first)
    assert repeated == []


def test_read_only_calls_can_dispatch_while_mutation_is_running() -> None:
    machine = SessionStateMachine(computer_mutations=MUTATIONS)
    machine.phase = Phase.THINKING

    mutation = machine.handle(ToolProposed(call("c1", "app_switch")))
    read = machine.handle(ToolProposed(call("c2", "computer_get_context")))

    assert any(isinstance(command, ExecTool) for command in mutation)
    assert any(isinstance(command, ExecTool) for command in read)


def test_read_only_executors_run_in_parallel(cfg, ctx) -> None:
    async def run() -> int:
        from conn.app import ConnApp
        from conn.realtime.fake import FakeRealtimeAdapter
        from conn.tools.harness import ToolHarness
        from conn.tools.registry import build_registry

        barrier = threading.Barrier(3)
        completed = 0
        lock = threading.Lock()

        def delayed_read(args, execution_ctx):
            nonlocal completed
            barrier.wait(timeout=2)
            with lock:
                completed += 1
            return {"app": "Safari"}

        adapter = FakeRealtimeAdapter(pace_s=0)
        harness = ToolHarness(
            build_registry(), cfg, ctx,
            executors={"computer_get_context": delayed_read},
        )
        app = ConnApp(cfg, adapter, harness)
        await adapter.connect()
        app._loop = asyncio.get_running_loop()
        app._start_turn_context()
        context = app._turn_context
        assert context is not None
        app.machine.phase = Phase.THINKING

        commands = []
        for call_id in ("read-1", "read-2"):
            proposed = dataclasses.replace(
                call(call_id, "computer_get_context"),
                turn_id=context.turn_id,
                response_epoch=context.response_epoch,
                observation_epoch=context.observation_epoch,
            )
            commands.extend(app.machine.handle(ToolProposed(proposed)))
        for command in commands:
            await app._exec(command)

        await asyncio.wait_for(asyncio.to_thread(barrier.wait), timeout=2)
        await app._quiesce_tool_tasks()
        await app.stop()
        return completed

    assert asyncio.run(run()) == 2


def test_tool_completion_resolves_only_the_exact_execution_generation() -> None:
    machine = SessionStateMachine(computer_mutations=MUTATIONS)
    machine.phase = Phase.THINKING
    proposed = ToolCall(
        "same",
        "app_switch",
        {},
        Gate.AUTO,
        "Switch app",
        turn_id="turn_1",
        response_epoch=2,
        observation_epoch=3,
    )

    [command] = machine.handle(ToolProposed(proposed))
    running = command.call
    verified_output = json.dumps(simulated_verified_receipt(
        target="Safari",
        effect="frontmost app is Safari",
        data={"frontmost_bundle": "com.apple.Safari"},
    ))

    stale = ToolFinished(
        call_id="same",
        ok=True,
        output=verified_output,
        action_outcome=ActionOutcome.VERIFIED,
        turn_id="turn_1",
        response_epoch=2,
        observation_epoch=3,
        execution_id=running.execution_id + 1,
    )
    assert machine.handle(stale) == []
    assert machine.ledger["same"].status is CallStatus.RUNNING

    exact = ToolFinished(
        call_id="same",
        ok=True,
        output=verified_output,
        action_outcome=ActionOutcome.VERIFIED,
        turn_id="turn_1",
        response_epoch=2,
        observation_epoch=3,
        execution_id=running.execution_id,
    )
    commands = machine.handle(exact)

    assert any(isinstance(item, SendToolResult) for item in commands)
    assert machine.ledger["same"].status is CallStatus.VERIFIED


def test_nonverified_mutation_closes_chain_until_fresh_user_turn() -> None:
    machine = SessionStateMachine(computer_mutations=MUTATIONS)
    machine.phase = Phase.THINKING
    [first_exec] = machine.handle(ToolProposed(call("first", "app_switch")))
    first = first_exec.call

    machine.handle(ToolFinished(
        call_id=first.call_id,
        ok=False,
        output='{"ok":false,"outcome":"dispatch_only"}',
        action_outcome=ActionOutcome.DISPATCH_ONLY,
        turn_id=first.turn_id,
        response_epoch=first.response_epoch,
        observation_epoch=first.observation_epoch,
        execution_id=first.execution_id,
    ))

    blocked = machine.handle(ToolProposed(call("second", "app_switch")))

    assert not any(isinstance(command, ExecTool) for command in blocked)
    assert machine.ledger["second"].status is CallStatus.BLOCKED
    assert "mutation_chain_closed" in (machine.ledger["second"].output or "")

    machine.handle(UserStop())
    machine.handle(TextCommand("fresh user turn"))
    allowed = machine.handle(ToolProposed(call("third", "app_switch")))

    assert any(isinstance(command, ExecTool) for command in allowed)


def test_old_response_tool_call_is_ignored_after_new_response(cfg, ctx) -> None:
    async def run() -> tuple[list[dict], object]:
        from conn.app import ConnApp
        from conn.realtime.fake import FakeRealtimeAdapter
        from conn.tools.harness import ToolHarness
        from conn.tools.registry import build_registry

        cfg.data_dir = ctx.screenshot_dir.parent / "data"
        app = ConnApp(cfg, FakeRealtimeAdapter(pace_s=0), ToolHarness(build_registry(), cfg, ctx))
        await app.start()
        await app.on_text("hello")
        await app._on_rt_event(RtResponseCreated(response_id="r_new"))
        await app._on_rt_event(RtTextDelta(text="new", response_id="r_new"))
        await app._on_rt_event(RtToolCall(
            call_id="old_call",
            name="computer_get_context",
            arguments_json="{}",
            response_id="r_old",
        ))
        await app.stop()
        return app.trace.read(), app

    trace, app = asyncio.run(run())
    assert "old_call" not in app.machine.ledger
    assert any(event["kind"] == "stale_realtime_event" for event in trace)


def test_late_old_response_is_ignored_after_barge_in(cfg, ctx) -> None:
    async def run() -> tuple[list[dict], object]:
        from conn.app import ConnApp
        from conn.realtime.fake import FakeRealtimeAdapter
        from conn.tools.harness import ToolHarness
        from conn.tools.registry import build_registry

        cfg.session.tap_threshold_ms = 0
        cfg.data_dir = ctx.screenshot_dir.parent / "data"
        adapter = FakeRealtimeAdapter(pace_s=0)
        app = ConnApp(cfg, adapter, ToolHarness(build_registry(), cfg, ctx))
        await adapter.connect()

        await app.on_text("first turn")
        old_response = adapter._active_response_id
        assert old_response is not None
        await app._on_rt_event(RtResponseCreated(response_id=old_response))
        await app._on_rt_event(RtTextDelta(text="old answer", response_id=old_response))
        assert app.machine.phase is Phase.SPEAKING

        await app.on_ptt_down()
        await app.on_ptt_up()
        new_response = adapter._active_response_id
        assert new_response is not None and new_response != old_response
        await app._on_rt_event(RtResponseCreated(response_id=new_response))

        await app._on_rt_event(RtToolCall(
            call_id="late-old-call",
            name="app_switch",
            arguments_json='{"app":"Safari"}',
            response_id=old_response,
        ))
        trace = app.trace.read()
        await app.stop()
        return trace, app

    trace, app = asyncio.run(run())
    assert "late-old-call" not in app.machine.ledger
    assert any(
        event["kind"] == "stale_realtime_event"
        and event.get("response_id") is not None
        for event in trace
    )


def test_stop_cancels_queued_undispatched_approval() -> None:
    machine = SessionStateMachine(computer_mutations=MUTATIONS)
    machine.phase = Phase.THINKING
    queued = machine.handle(ToolProposed(ToolCall(
        "queued",
        "app_menu",
        {"path": ["File", "Close"]},
        Gate.CONFIRM,
        "Close window",
    )))
    assert not any(isinstance(command, ExecTool) for command in queued)

    machine.handle(UserStop())
    after_stop = machine.handle(ApprovalDecision(call_id="queued", approved=True))

    assert after_stop == []
    assert machine.phase is Phase.IDLE
    assert "queued" not in machine.ledger


def test_stop_does_not_report_idle_before_started_mutation_finishes(cfg, ctx) -> None:
    async def run() -> tuple[list[str], Phase, bool]:
        from conn.app import ConnApp
        from conn.realtime.fake import FakeRealtimeAdapter
        from conn.tools.harness import ToolHarness
        from conn.tools.registry import build_registry

        entered = threading.Event()
        release = threading.Event()
        effects: list[str] = []

        def delayed(args, execution_ctx):
            entered.set()
            release.wait(timeout=2)
            effects.append("dispatched")
            return {"activated": True}

        cfg.data_dir = ctx.screenshot_dir.parent / "data"
        harness = ToolHarness(
            build_registry(), cfg, ctx, executors={"app_switch": delayed}
        )
        app = ConnApp(cfg, FakeRealtimeAdapter(pace_s=0), harness)
        await app.start()
        app._start_turn_context()
        context = app._turn_context
        assert context is not None
        call = ToolCall(
            "late",
            "app_switch",
            {"app": "Safari"},
            Gate.AUTO,
            "Switch to Safari",
            turn_id=context.turn_id,
            response_epoch=context.response_epoch,
            observation_epoch=context.observation_epoch,
        )
        app.machine.phase = Phase.THINKING
        commands = app.machine.handle(ToolProposed(call))

        async def execute_commands() -> None:
            for command in commands:
                await app._exec(command)

        execution_task = asyncio.create_task(execute_commands())
        while not entered.is_set():
            await asyncio.sleep(0)

        stop_task = asyncio.create_task(app.on_stop())
        await asyncio.sleep(0.02)
        returned_early = stop_task.done()
        release.set()
        await asyncio.gather(execution_task, stop_task)
        phase = app.machine.phase
        await app.stop()
        return effects, phase, returned_early

    effects, phase, returned_early = asyncio.run(run())
    assert returned_early is False
    assert effects == ["dispatched"]
    assert phase is Phase.IDLE
