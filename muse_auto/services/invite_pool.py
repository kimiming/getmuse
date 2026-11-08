"""Invite-code pool backed by ``inviteCode.txt``.

Each line is a code. A line may carry a usage suffix written by this module::

    4X2K8I---用了1次

A code is used at most ``uses_per_code`` times (default 30); once exhausted,
the next line is selected. All operations are serialized in-process so
concurrent instance workers never reuse the same slot by accident.
"""

from __future__ import annotations

import os
import threading
from dataclasses import dataclass
from pathlib import Path

_LOCK = threading.RLock()
_USAGE_SEP = "---用了"


class InvitePoolExhausted(RuntimeError):
    pass


@dataclass(frozen=True)
class InviteEntry:
    code: str
    used: int = 0


@dataclass(frozen=True)
class InviteLease:
    code: str
    used: int
    limit: int

    @property
    def remaining(self) -> int:
        return max(0, self.limit - self.used)


class InviteCodePool:
    def __init__(self, path: str | Path, uses_per_code: int = 30) -> None:
        self.path = Path(path)
        self.uses_per_code = max(1, int(uses_per_code))

    # ------------------------------------------------------------------
    # Public
    # ------------------------------------------------------------------

    def acquire(self) -> InviteLease:
        with _LOCK:
            entries = self._read()
            if not entries:
                raise InvitePoolExhausted(f"邀请码文件为空：{self.path}")
            for index, entry in enumerate(entries):
                if entry.used < self.uses_per_code:
                    used = entry.used + 1
                    entries[index] = InviteEntry(entry.code, used)
                    self._write(entries)
                    return InviteLease(entry.code, used, self.uses_per_code)
            raise InvitePoolExhausted(
                f"邀请码都用完了（每个 {self.uses_per_code} 次）：{self.path}"
            )

    def rollback(self, code: str) -> None:
        """Undo a reservation if redemption failed before consuming the code."""
        with _LOCK:
            entries = self._read()
            for index, entry in enumerate(entries):
                if entry.code == code and entry.used > 0:
                    entries[index] = InviteEntry(entry.code, entry.used - 1)
                    self._write(entries)
                    return

    def status(self) -> list[InviteEntry]:
        with _LOCK:
            return self._read()

    # ------------------------------------------------------------------
    # File
    # ------------------------------------------------------------------

    def _read(self) -> list[InviteEntry]:
        if not self.path.exists():
            return []
        entries: list[InviteEntry] = []
        for line in self.path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if _USAGE_SEP in line:
                code, tail = line.split(_USAGE_SEP, 1)
                code = code.strip()
                count_text = tail.strip().rstrip("次").strip()
                try:
                    used = int(count_text)
                except ValueError:
                    used = 0
            else:
                code, used = line, 0
            if code:
                entries.append(InviteEntry(code, max(0, used)))
        return entries

    def _write(self, entries: list[InviteEntry]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp = self.path.with_suffix(self.path.suffix + ".tmp")
        with temp.open("w", encoding="utf-8", newline="\n") as handle:
            for entry in entries:
                if entry.used:
                    handle.write(f"{entry.code}{_USAGE_SEP}{entry.used}次\n")
                else:
                    handle.write(f"{entry.code}\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp, self.path)
