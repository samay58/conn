"""Global push-to-talk hotkey via pynput (listen-only tap: needs Input
Monitoring, not Accessibility). Degrades gracefully: if the listener cannot
start, the console's hold-Space PTT still carries the product.
"""

from __future__ import annotations

import asyncio
from typing import Callable


class HotkeyListener:
    def __init__(self, key_name: str, on_down: Callable[[], None],
                 on_up: Callable[[], None]):
        self.key_name = key_name
        self.on_down = on_down
        self.on_up = on_up
        self._listener = None
        self._held = False

    def start(self) -> bool:
        if self.key_name in ("", "none"):
            return False
        try:
            from pynput import keyboard

            target = getattr(keyboard.Key, self.key_name, None)
            if target is None:
                target = keyboard.KeyCode.from_char(self.key_name)

            def press(key):
                if key == target and not self._held:
                    self._held = True
                    self.on_down()

            def release(key):
                if key == target and self._held:
                    self._held = False
                    self.on_up()

            self._listener = keyboard.Listener(on_press=press, on_release=release)
            self._listener.start()
            return True
        except Exception:
            return False

    def stop(self) -> None:
        if self._listener:
            self._listener.stop()
            self._listener = None


def wire_hotkey(cfg_key: str, app, loop: asyncio.AbstractEventLoop) -> HotkeyListener | None:
    def down():
        loop.call_soon_threadsafe(lambda: asyncio.ensure_future(app.on_ptt_down()))

    def up():
        loop.call_soon_threadsafe(lambda: asyncio.ensure_future(app.on_ptt_up()))

    listener = HotkeyListener(cfg_key, down, up)
    return listener if listener.start() else None
