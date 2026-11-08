"""Application logging setup.

One console handler and one run-scoped file handler. Per-instance context is
added by the caller through :func:`instance_logger` instead of global mutable
state.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

_FORMAT = "%(asctime)s %(levelname)-7s %(message)s"
_DATE_FORMAT = "%H:%M:%S"


class _Formatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        prefix = getattr(record, "instance", "")
        message = super().format(record)
        if prefix:
            return f"{message} [{prefix}]"
        return message


def setup_logging(level: str = "INFO", log_file: Path | None = None) -> logging.Logger:
    root = logging.getLogger("muse_auto")
    root.setLevel(getattr(logging, str(level).upper(), logging.INFO))
    root.handlers.clear()
    root.propagate = False

    formatter = _Formatter(_FORMAT, datefmt=_DATE_FORMAT)

    console = logging.StreamHandler(sys.stderr)
    console.setFormatter(formatter)
    root.addHandler(console)

    if log_file is not None:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(log_file, encoding="utf-8")
        file_handler.setFormatter(formatter)
        root.addHandler(file_handler)

    return root


def get_logger(name: str = "muse_auto") -> logging.Logger:
    return logging.getLogger(name)


class InstanceLogger:
    """Logger adapter that appends ``[instance]`` to every record."""

    def __init__(self, logger: logging.Logger, instance: str) -> None:
        self._logger = logger
        self._instance = instance

    def _log(self, level: int, message: str, *args: object, **kwargs: object) -> None:
        self._logger.log(level, message, *args, extra={"instance": self._instance}, **kwargs)

    def debug(self, message: str, *args: object, **kwargs: object) -> None:
        self._log(logging.DEBUG, message, *args, **kwargs)

    def info(self, message: str, *args: object, **kwargs: object) -> None:
        self._log(logging.INFO, message, *args, **kwargs)

    def warning(self, message: str, *args: object, **kwargs: object) -> None:
        self._log(logging.WARNING, message, *args, **kwargs)

    def error(self, message: str, *args: object, **kwargs: object) -> None:
        self._log(logging.ERROR, message, *args, **kwargs)

    def exception(self, message: str, *args: object, **kwargs: object) -> None:
        self._log(logging.ERROR, message, *args, exc_info=True, **kwargs)


def instance_logger(instance: str, name: str = "muse_auto") -> InstanceLogger:
    return InstanceLogger(get_logger(name), instance)
