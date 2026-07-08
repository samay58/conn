"""The per-call fresh frontmost source (bug 1 of the 2026-07-07 live drive).

NSWorkspace.frontmostApplication() is KVO-cached and never updates in a
process whose main thread does not pump a runloop, which is exactly the
daemon (asyncio owns main, executors run on harness threads). Measured
2026-07-08: it serves the app that was frontmost at process start, forever.
The fix derives frontmost from the window server (front layer-0 on-screen
window), filtered to regular-activation-policy apps so accessory overlays
(Kaku, WindowManager) never win.

These tests patch the module's seams; the live behavior was verified with
the discriminating probe in the session notes.
"""

from unittest.mock import patch

import pytest

from conn.tools import frontmost
from conn.tools.base import ToolError


class FakeApp:
    def __init__(self, name, bundle, pid, policy=frontmost.POLICY_REGULAR):
        self._name = name
        self._bundle = bundle
        self._pid = pid
        self._policy = policy

    def localizedName(self):
        return self._name

    def bundleIdentifier(self):
        return self._bundle

    def processIdentifier(self):
        return self._pid

    def activationPolicy(self):
        return self._policy


CHROME = FakeApp("Google Chrome", "com.google.Chrome", 100)
TERMINAL = FakeApp("Terminal", "com.apple.Terminal", 200)
KAKU = FakeApp("Kaku", "fun.tw93.kaku", 300, policy=frontmost.POLICY_ACCESSORY)
WINDOW_MANAGER = FakeApp("WindowManager", "com.apple.WindowManager", 400, policy=frontmost.POLICY_ACCESSORY)


def apps(*items):
    by_pid = {app.processIdentifier(): app for app in items}
    return lambda pid: by_pid.get(pid)


class TestFrontmostApplication:
    def test_front_regular_window_owner_wins(self):
        with patch.object(frontmost, "_front_window_owner_pids", return_value=[100, 200]), \
             patch.object(frontmost, "_running_app", side_effect=apps(CHROME, TERMINAL)):
            app = frontmost.frontmost_application()
        assert app.bundleIdentifier() == "com.google.Chrome"

    def test_accessory_owner_is_skipped(self):
        # Measured live: WindowManager (accessory) transiently owns the front
        # layer-0 window during a Stage Manager transition.
        with patch.object(frontmost, "_front_window_owner_pids", return_value=[400, 200]), \
             patch.object(frontmost, "_running_app", side_effect=apps(WINDOW_MANAGER, TERMINAL)):
            app = frontmost.frontmost_application()
        assert app.bundleIdentifier() == "com.apple.Terminal"

    def test_kaku_never_wins_while_a_regular_app_has_a_window(self):
        with patch.object(frontmost, "_front_window_owner_pids", return_value=[300, 100]), \
             patch.object(frontmost, "_running_app", side_effect=apps(KAKU, CHROME)):
            app = frontmost.frontmost_application()
        assert app.bundleIdentifier() == "com.google.Chrome"

    def test_falls_back_to_workspace_when_no_regular_window_owner(self):
        with patch.object(frontmost, "_front_window_owner_pids", return_value=[300]), \
             patch.object(frontmost, "_running_app", side_effect=apps(KAKU)), \
             patch.object(frontmost, "_workspace_frontmost", return_value=TERMINAL):
            app = frontmost.frontmost_application()
        assert app.bundleIdentifier() == "com.apple.Terminal"

    def test_workspace_fallback_rejects_accessory_apps(self):
        with patch.object(frontmost, "_front_window_owner_pids", return_value=[]), \
             patch.object(frontmost, "_running_app", return_value=None), \
             patch.object(frontmost, "_workspace_frontmost", return_value=KAKU):
            assert frontmost.frontmost_application() is None

    def test_returns_none_when_nothing_resolves(self):
        with patch.object(frontmost, "_front_window_owner_pids", return_value=[]), \
             patch.object(frontmost, "_running_app", return_value=None), \
             patch.object(frontmost, "_workspace_frontmost", return_value=None):
            assert frontmost.frontmost_application() is None

    def test_unknown_pid_is_skipped(self):
        with patch.object(frontmost, "_front_window_owner_pids", return_value=[999, 200]), \
             patch.object(frontmost, "_running_app", side_effect=apps(TERMINAL)):
            app = frontmost.frontmost_application()
        assert app.bundleIdentifier() == "com.apple.Terminal"


class TestCallSites:
    def test_get_context_reads_the_fresh_source(self, ctx):
        from conn.tools import mac

        with patch.object(frontmost, "frontmost_application", return_value=CHROME):
            data = mac.get_context({}, ctx)
        assert data["app"] == "Google Chrome"
        assert data["bundle_id"] == "com.google.Chrome"

    def test_get_context_handles_no_frontmost(self, ctx):
        from conn.tools import mac

        with patch.object(frontmost, "frontmost_application", return_value=None):
            data = mac.get_context({}, ctx)
        assert data["app"] is None
        assert data["bundle_id"] is None

    def test_mac_ax_backend_reads_the_fresh_source(self):
        from conn.tools.ax import MacAxBackend

        with patch.object(frontmost, "frontmost_application", return_value=CHROME):
            bundle_id, pid = MacAxBackend().frontmost()
        assert (bundle_id, pid) == ("com.google.Chrome", 100)

    def test_mac_ax_backend_raises_when_unavailable(self):
        from conn.tools.ax import MacAxBackend

        with patch.object(frontmost, "frontmost_application", return_value=None):
            with pytest.raises(ToolError, match="frontmost_unavailable"):
                MacAxBackend().frontmost()
