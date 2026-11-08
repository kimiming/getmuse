"""Cooperative cancellation shared by CLI, runner, and UI waits."""

from __future__ import annotations

import threading
import time

from muse_auto.core.errors import Stopped


class StopToken:
    """A thin wrapper around ``threading.Event`` with sleep/check helpers."""

    def __init__(self, event: threading.Event | None = None) -> None:
        self._event = event or threading.Event()

    @property
    def event(self) -> threading.Event:
        return self._event

    @property
    def stopped(self) -> bool:
        return self._event.is_set()

    def stop(self) -> None:
        self._event.set()

    def reset(self) -> None:
        self._event.clear()

    def check(self) -> None:
        if self._event.is_set():
            raise Stopped("任务已停止")

    def sleep(self, seconds: float) -> None:
        """Sleep, but wake up immediately when a stop is requested."""
        if seconds <= 0:
            self.check()
            return
        if self._event.wait(seconds):
            raise Stopped("任务已停止")

    def wait(self, seconds: float) -> bool:
        """Sleep and return ``True`` if a stop was requested."""
        return self._event.wait(max(0.0, seconds))

    def poll(self, predicate, timeout: float, interval: float = 0.5):
        """Call ``predicate`` until truthy or timeout; returns last value."""
        deadline = time.monotonic() + max(0.0, timeout)
        while True:
            self.check()
            value = predicate()
            if value:
                return value
            if time.monotonic() >= deadline:
                return value
            self.sleep(min(interval, max(0.0, deadline - time.monotonic())))
