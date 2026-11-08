"""One-at-a-time replacement email pool.

The file is a plain list (one address per line). ``take`` removes the first
address immediately; ``restore`` puts it back if the change failed before it was
consumed. Writes are atomic so an interrupted run does not duplicate addresses.
"""

from __future__ import annotations

import os
import threading
from pathlib import Path


class EmailPool:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self._lock = threading.RLock()

    def _read(self) -> list[str]:
        if not self.path.exists():
            return []
        lines = self.path.read_text(encoding="utf-8").splitlines()
        return [line.strip() for line in lines if line.strip() and not line.strip().startswith("#")]

    def _write(self, lines: list[str]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp = self.path.with_suffix(self.path.suffix + ".tmp")
        with temp.open("w", encoding="utf-8", newline="\n") as handle:
            for line in lines:
                handle.write(line + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp, self.path)

    def take(self) -> str | None:
        with self._lock:
            lines = self._read()
            if not lines:
                return None
            email = lines.pop(0)
            self._write(lines)
            return email

    def restore(self, email: str) -> None:
        email = str(email or "").strip()
        if not email:
            return
        with self._lock:
            lines = self._read()
            if email not in lines:
                self._write([email, *lines])

    def remaining(self) -> int:
        with self._lock:
            return len(self._read())
