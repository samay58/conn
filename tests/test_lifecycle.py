"""R1 daemon lifecycle: app-owned daemons carry a parent lease, quit
gracefully on an authenticated shutdown message, and orphan-exit after
bounded parent loss. Hand-run daemons (no lease) never orphan-exit."""

from __future__ import annotations

import asyncio

from conn.lifecycle import OwnershipLease


class TestLeaseParsing:
    def test_from_environment_reads_and_removes_parent_pid(self):
        env = {"CONN_PARENT_PID": "4242"}
        lease = OwnershipLease.from_environment(env)
        assert lease.parent_pid == 4242
        assert lease.bound
        assert "CONN_PARENT_PID" not in env

    def test_missing_or_garbage_pid_leaves_lease_unbound(self):
        assert not OwnershipLease.from_environment({}).bound
        assert not OwnershipLease.from_environment(
            {"CONN_PARENT_PID": "not-a-pid"}).bound

    def test_grace_override_from_environment(self):
        env = {"CONN_PARENT_PID": "1", "CONN_ORPHAN_GRACE_S": "1.5"}
        lease = OwnershipLease.from_environment(env)
        assert lease.grace_s == 1.5


class TestOrphanWatch:
    def _run_watch(self, alive_sequence, *, grace_s=4.0, poll_s=2.0):
        """Drive watch() with a scripted parent_alive sequence and a fake
        sleep that advances instantly. Returns True if on_orphaned fired."""
        fired = []
        sequence = iter(alive_sequence)

        def parent_alive():
            try:
                return next(sequence)
            except StopIteration:
                return True

        async def fake_sleep(_s):
            return

        lease = OwnershipLease(parent_pid=999, grace_s=grace_s, poll_s=poll_s)

        async def run():
            await lease.watch(lambda: fired.append(True),
                              parent_alive=parent_alive, sleep=fake_sleep,
                              max_polls=len(alive_sequence))

        asyncio.run(run())
        return bool(fired)

    def test_continuous_parent_loss_past_grace_fires(self):
        # poll 2s, grace 4s: three consecutive dead polls exceed the grace.
        assert self._run_watch([False, False, False]) is True

    def test_parent_flap_resets_the_grace(self):
        assert self._run_watch([False, False, True, False, False]) is False

    def test_living_parent_never_fires(self):
        assert self._run_watch([True] * 10) is False

    def test_unbound_lease_never_fires(self):
        fired = []

        async def run():
            lease = OwnershipLease(parent_pid=None)
            await lease.watch(lambda: fired.append(True),
                              parent_alive=lambda: False,
                              sleep=lambda _s: asyncio.sleep(0),
                              max_polls=5)

        asyncio.run(run())
        assert fired == []


class TestShutdownMessage:
    def test_app_shutdown_message_triggers_daemon_shutdown(self, cfg, ctx):
        from conn.server.http import handle_client
        from tests.test_trace_truth import build_app

        async def run():
            app = build_app(cfg, ctx)
            app._loop = asyncio.get_running_loop()
            await app.adapter.connect()
            fired = []
            app.shutdown_signal = lambda: fired.append(True)
            await handle_client(app, {"type": "shutdown"},
                                authenticated_role="app", client_id="c1")
            events = [e for e in app.trace.read()
                      if e["kind"] == "shutdown_request"]
            await app.stop()
            return fired, events

        fired, events = asyncio.run(run())
        assert fired == [True]
        assert len(events) == 1

    def test_console_cannot_trigger_shutdown(self, cfg, ctx):
        from conn.server.http import handle_client
        from tests.test_trace_truth import build_app

        async def run():
            app = build_app(cfg, ctx)
            app._loop = asyncio.get_running_loop()
            await app.adapter.connect()
            fired = []
            app.shutdown_signal = lambda: fired.append(True)
            await handle_client(app, {"type": "shutdown"},
                                authenticated_role="console", client_id="c2")
            await app.stop()
            return fired

        assert asyncio.run(run()) == []
