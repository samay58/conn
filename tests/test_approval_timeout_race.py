"""A late approval timeout must never overwrite a decided call, and a click
for a chip that is no longer pending must never be dispatched."""

from __future__ import annotations

import asyncio

import pytest

from conn.events import (
    ApprovalDecision, ApprovalTimeout, Gate, PttDown, PttUp, ResponseDone,
    ToolCall,
)
from conn.state import CallStatus, SessionStateMachine
from conn.tools.registry import build_registry, computer_mutation_names

from tests.test_app_reliability import build_app

MUTATIONS = computer_mutation_names(build_registry())


def call(call_id="c1", gate=Gate.AUTO, name="app_open"):
    return ToolCall(call_id=call_id, name=name, arguments={"app": "Obsidian"},
                    gate=gate, preview="Open app: Obsidian")


@pytest.fixture
def m():
    return SessionStateMachine(computer_mutations=MUTATIONS)


def start_turn(m, t0=1000, t1=2000):
    m.handle(PttDown(ts_ms=t0))
    return m.handle(PttUp(ts_ms=t1))


def ToolProposedFactory(call_id="c1", gate=Gate.AUTO, name="app_open"):
    from conn.events import ToolProposed
    return ToolProposed(call=call(call_id=call_id, gate=gate, name=name))


def _proposed_confirm(m):
    start_turn(m)
    m.handle(ToolProposedFactory(gate=Gate.CONFIRM))
    m.handle(ResponseDone(had_tool_calls=True))


def test_timeout_after_approval_leaves_running_call_alone(m):
    _proposed_confirm(m)
    m.handle(ApprovalDecision(call_id="c1", approved=True))
    assert m.ledger["c1"].status is CallStatus.RUNNING
    cmds = m.handle(ApprovalTimeout(call_id="c1"))
    assert cmds == []
    assert m.ledger["c1"].status is CallStatus.RUNNING


def test_timeout_after_denial_is_a_noop(m):
    _proposed_confirm(m)
    m.handle(ApprovalDecision(call_id="c1", approved=False))
    assert m.ledger["c1"].status is CallStatus.DENIED
    cmds = m.handle(ApprovalTimeout(call_id="c1"))
    assert cmds == []
    assert m.ledger["c1"].status is CallStatus.DENIED


def test_timeout_while_proposed_still_times_out(m):
    _proposed_confirm(m)
    cmds = m.handle(ApprovalTimeout(call_id="c1"))
    assert m.ledger["c1"].status is CallStatus.TIMEOUT
    assert "approval_timeout" in cmds[0].output


def test_click_after_chip_expired_is_ignored(cfg, ctx):
    async def run():
        app, _messages = build_app(cfg, ctx)
        dispatched = []

        async def record(ev):
            dispatched.append(ev)

        app.dispatch = record
        await app.on_approval("c_expired", approved=True)
        kinds = [e["kind"] for e in app.trace.read()]
        return dispatched, kinds

    dispatched, kinds = asyncio.run(run())
    assert dispatched == []
    assert "approval_decision_ignored" in kinds
