"""Bridge Python logging into the Tk event queue."""

from __future__ import annotations

import logging
import queue
import time


class QueueLogHandler(logging.Handler):
    """Put formatted log records on a queue; Tk reads it on the main thread."""

    def __init__(self, target: "queue.Queue[tuple]") -> None:
        super().__init__()
        self.target = target

    def emit(self, record: logging.LogRecord) -> None:
        try:
            message = record.getMessage()
            if record.exc_info:
                message = f"{message}\n{self.formatException(record.exc_info)}"
            instance = getattr(record, "instance", "")
            prefix = f"[{instance}] " if instance else ""
            timestamp = time.strftime("%H:%M:%S", time.localtime(record.created))
            self.target.put(("log", record.levelno, f"{timestamp} {prefix}{message}"))
        except Exception:  # noqa: BLE001 - logging must never break the UI
            self.handleError(record)
