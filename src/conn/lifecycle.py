"""Daemon ownership lease.

An app-launched daemon is owned by the app process that spawned it:
`DaemonLauncher` passes its pid as CONN_PARENT_PID next to the bridge token.
Ownership means two duties the July 12 session lacked: exit gracefully when
the owner asks (authenticated `shutdown` frame on normal app quit), and exit
on a bounded grace period after the owner dies, so a quit app never strands
a port-squatting daemon. A hand-run daemon has no lease and never
orphan-exits. Nothing here ever kills or adopts another process; a foreign
port owner is the launcher's problem to refuse, not ours to reap.
"""

from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass

DEFAULT_GRACE_S = 20.0
DEFAULT_POLL_S = 2.0


@dataclass
class OwnershipLease:
    parent_pid: int | None
    grace_s: float = DEFAULT_GRACE_S
    poll_s: float = DEFAULT_POLL_S

    @classmethod
    def from_environment(cls, env) -> "OwnershipLease":
        raw = env.pop("CONN_PARENT_PID", None)
        try:
            parent_pid = int(raw) if raw is not None else None
        except ValueError:
            parent_pid = None
        if parent_pid is not None and parent_pid <= 0:
            parent_pid = None
        try:
            grace_s = float(env.pop("CONN_ORPHAN_GRACE_S", DEFAULT_GRACE_S))
        except ValueError:
            grace_s = DEFAULT_GRACE_S
        return cls(parent_pid=parent_pid, grace_s=grace_s)

    @property
    def bound(self) -> bool:
        return self.parent_pid is not None

    def _parent_alive(self) -> bool:
        # The daemon is a direct child of the launcher, so a dead parent
        # reparents us (getppid changes). This needs no signal permission
        # and cannot race pid reuse.
        return os.getppid() == self.parent_pid

    async def watch(self, on_orphaned, *, parent_alive=None, sleep=None,
                    max_polls: int | None = None) -> None:
        """Fire on_orphaned once after the parent has been continuously gone
        for grace_s. A reappearing parent (same pid observed again) resets
        the grace window."""
        if not self.bound:
            return
        alive = parent_alive or self._parent_alive
        do_sleep = sleep or asyncio.sleep
        gone_for = 0.0
        polls = 0
        while max_polls is None or polls < max_polls:
            polls += 1
            if alive():
                gone_for = 0.0
            else:
                gone_for += self.poll_s
                if gone_for > self.grace_s:
                    on_orphaned()
                    return
            await do_sleep(self.poll_s)
