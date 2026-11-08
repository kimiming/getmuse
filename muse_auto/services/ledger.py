"""Append-only account ledger with atomic updates.

One JSON object per line. Rows are appended as soon as a mailbox is bought, so
an interrupted run never strands an account. ``update`` rewrites the file via a
temp file + ``os.replace`` and is guarded by a process-local lock.
"""

from __future__ import annotations

import csv
import json
import os
import threading
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


STATUS_MAILBOX = "mailbox_bought"
STATUS_EMAIL = "email_submitted"
STATUS_OTP = "otp_verified"
STATUS_REGISTERED = "registered"
STATUS_INVITED = "invite_redeemed"
STATUS_FAILED = "failed"
STATUS_MANUAL = "manual_required"


@dataclass
class AccountRecord:
    email: str
    order_id: str = ""
    status: str = STATUS_MAILBOX
    instance: str = ""
    host: str = ""
    db_id: str = ""
    created_at: str = field(default_factory=_now)
    updated_at: str = field(default_factory=_now)
    invite_redeemed: bool = False
    note: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "AccountRecord":
        known = {field.name for field in cls.__dataclass_fields__.values()}  # type: ignore[attr-defined]
        return cls(**{key: value for key, value in data.items() if key in known})


class Ledger:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()

    # -- read --------------------------------------------------------------

    def all(self) -> list[AccountRecord]:
        with self._lock:
            if not self.path.exists():
                return []
            records: list[AccountRecord] = []
            with self.path.open("r", encoding="utf-8") as handle:
                for line in handle:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        data = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if isinstance(data, dict) and data.get("email"):
                        records.append(AccountRecord.from_dict(data))
            return records

    def find(self, email_or_order: str) -> AccountRecord | None:
        needle = str(email_or_order or "").strip().casefold()
        for record in self.all():
            if record.email.casefold() == needle or record.order_id == needle:
                return record
        return None

    def __iter__(self) -> Iterator[AccountRecord]:
        return iter(self.all())

    # -- write -------------------------------------------------------------

    def upsert(self, record: AccountRecord) -> AccountRecord:
        with self._lock:
            existing = self.find(record.email)
            if existing is None:
                record.created_at = record.created_at or _now()
                record.updated_at = _now()
                with self.path.open("a", encoding="utf-8") as handle:
                    handle.write(json.dumps(record.to_dict(), ensure_ascii=False) + "\n")
                    handle.flush()
                    os.fsync(handle.fileno())
                return record

            merged = existing.to_dict()
            for key, value in record.to_dict().items():
                if key in {"created_at"}:
                    continue
                if value not in ("", None, False) or key in {"invite_redeemed", "status"}:
                    merged[key] = value
            merged["updated_at"] = _now()
            self._rewrite(merged)
            return AccountRecord.from_dict(merged)

    def update(self, email: str, **fields: Any) -> AccountRecord:
        with self._lock:
            existing = self.find(email)
            if existing is None:
                raise KeyError(f"账本中不存在：{email}")
            data = existing.to_dict()
            data.update(fields)
            data["updated_at"] = _now()
            self._rewrite(data)
            return AccountRecord.from_dict(data)

    def mark(self, email: str, status: str, *, note: str = "", **fields: Any) -> AccountRecord:
        return self.update(email, status=status, note=note, **fields)

    def _rewrite(self, changed: dict[str, Any]) -> None:
        records = [record.to_dict() for record in self.all()]
        target = str(changed.get("email") or "").casefold()
        replaced = False
        for index, record in enumerate(records):
            if str(record.get("email") or "").casefold() == target:
                records[index] = changed
                replaced = True
                break
        if not replaced:
            records.append(changed)

        temp = self.path.with_suffix(self.path.suffix + ".tmp")
        with temp.open("w", encoding="utf-8", newline="\n") as handle:
            for record in records:
                handle.write(json.dumps(record, ensure_ascii=False) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp, self.path)

    # -- export ------------------------------------------------------------

    def export_csv(self, path: str | Path) -> Path:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        records = self.all()
        columns = list(AccountRecord.__dataclass_fields__.keys())  # type: ignore[attr-defined]
        with target.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=columns)
            writer.writeheader()
            for record in records:
                writer.writerow(record.to_dict())
        return target

    def counts(self) -> dict[str, int]:
        result: dict[str, int] = {}
        for record in self.all():
            result[record.status] = result.get(record.status, 0) + 1
        return result
