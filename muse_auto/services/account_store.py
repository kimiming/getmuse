"""Append Muse accounts to ``muse账号.xls``.

Columns:

    账号 | 创建时间 | 账号-api | 邀请码 | 本号邀请码

``账号-api`` is ``<account>----<yich8 API URL with username=account>``.
``邀请码`` is the invite code used by that account (blank if step3 was skipped).
``本号邀请码`` is the account's own invite code (blank if step4 was skipped).

Existing rows are read with xlrd and rewritten with xlwt using an atomic temp
file. Excel keeps an exclusive lock while open; in that case a timestamped
snapshot + ``.pending.jsonl`` journal are written and merged on the next append
(or ``ledger --xls-merge``).
"""

from __future__ import annotations

import json
import os
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from muse_auto.services.yich8_mail import api_with_username

HEADERS = ("账号", "创建时间", "账号-api", "邀请码", "本号邀请码")


@dataclass(frozen=True)
class AccountRow:
    account: str
    created_at: str
    account_api: str = ""
    invite_code: str = ""
    own_invite_code: str = ""


class MuseAccountStore:
    def __init__(self, path: str | Path, api_template: str = "") -> None:
        self.path = Path(path)
        self.api_template = str(api_template or "").strip()
        self.pending_path = self.path.with_name(self.path.name + ".pending.jsonl")
        self._lock = threading.RLock()

    def read_all(self) -> list[AccountRow]:
        with self._lock:
            rows: list[AccountRow] = []
            if self.path.exists():
                try:
                    import xlrd
                except ImportError as exc:  # pragma: no cover - installed here
                    raise RuntimeError("需要 xlrd 才能读取 muse账号.xls") from exc
                book = xlrd.open_workbook(str(self.path))
                sheet = book.sheet_by_index(0)
                for index in range(sheet.nrows):
                    values = [
                        str(sheet.cell_value(index, col)).strip()
                        for col in range(min(len(HEADERS), sheet.ncols))
                    ]
                    if not any(values):
                        continue
                    if values and values[0] == HEADERS[0]:
                        # Header row (2/3/4-column old workbooks included).
                        continue
                    account = values[0] if values else ""
                    if not account:
                        continue
                    created_at = values[1] if len(values) > 1 else ""
                    account_api = values[2] if len(values) > 2 else ""
                    invite_code = values[3] if len(values) > 3 else ""
                    own_invite_code = values[4] if len(values) > 4 else ""
                    rows.append(
                        AccountRow(
                            account,
                            created_at,
                            account_api,
                            invite_code,
                            own_invite_code,
                        )
                    )
            rows.extend(self._read_pending())
            return self._dedupe(rows)

    def append(
        self,
        account: str,
        created_at: str | None = None,
        invite_code: str = "",
        own_invite_code: str = "",
    ) -> Path:
        account = str(account or "").strip()
        if not account:
            raise ValueError("账号不能为空")
        created_at = created_at or time.strftime("%Y-%m-%d %H:%M:%S")
        with self._lock:
            rows = self.read_all()
            rows.append(
                AccountRow(
                    account,
                    created_at,
                    self.api_for(account),
                    invite_code,
                    own_invite_code,
                )
            )
            return self._write(rows)

    def flush(self) -> Path:
        """Merge the journal / backfill missing 账号-api columns."""
        with self._lock:
            rows = self.read_all()
            needs_backfill = bool(self.api_template) and any(
                not row.account_api for row in rows
            )
            if not self.pending_path.exists() and not needs_backfill:
                if self.path.exists():
                    # Still rewrite once so old 2/3-column workbooks get the
                    # new ``邀请码`` header/column.
                    return self._write(rows)
                return self.path
            return self._write(rows)

    def api_for(self, account: str) -> str:
        url = api_with_username(self.api_template, account)
        return f"{account}----{url}" if url else ""

    # ------------------------------------------------------------------
    # Write / fallback
    # ------------------------------------------------------------------

    def _write(self, rows: list[AccountRow]) -> Path:
        try:
            import xlwt
        except ImportError as exc:  # pragma: no cover - installed here
            raise RuntimeError("需要 xlwt 才能写入 muse账号.xls") from exc

        rows = [
            AccountRow(
                row.account,
                row.created_at,
                row.account_api or self.api_for(row.account),
                row.invite_code,
                row.own_invite_code,
            )
            for row in rows
        ]
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp = self.path.with_suffix(self.path.suffix + ".tmp")
        self._save_workbook(rows, temp, xlwt)
        try:
            os.replace(temp, self.path)
        except PermissionError:
            # The workbook is usually open in Excel/WPS on Windows. Preserve the
            # data in a snapshot + journal instead of losing the changed email.
            fallback = self.path.with_name(
                f"{self.path.stem}_{time.strftime('%Y%m%d_%H%M%S')}{self.path.suffix}"
            )
            try:
                os.replace(temp, fallback)
            except OSError as exc:
                raise PermissionError(
                    f"{self.path} 被占用，且无法写备用文件：{exc}"
                ) from exc
            self._write_pending(rows)
            return fallback
        self._clear_pending()
        return self.path

    @staticmethod
    def _save_workbook(rows: Iterable[AccountRow], path: Path, xlwt) -> None:
        book = xlwt.Workbook(encoding="utf-8")
        sheet = book.add_sheet("muse账号")
        header_style = xlwt.easyxf("font: bold on; pattern: pattern solid, fore_colour gray25;")
        for col, title in enumerate(HEADERS):
            sheet.write(0, col, title, header_style)
        for row_index, row in enumerate(rows, start=1):
            sheet.write(row_index, 0, row.account)
            sheet.write(row_index, 1, row.created_at)
            sheet.write(row_index, 2, row.account_api)
            sheet.write(row_index, 3, row.invite_code)
            sheet.write(row_index, 4, row.own_invite_code)
        sheet.col(0).width = 40 * 256
        sheet.col(1).width = 22 * 256
        sheet.col(2).width = 120 * 256
        sheet.col(3).width = 20 * 256
        sheet.col(4).width = 20 * 256
        book.save(str(path))

    def _read_pending(self) -> list[AccountRow]:
        if not self.pending_path.exists():
            return []
        rows: list[AccountRow] = []
        for line in self.pending_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                item = json.loads(line)
            except ValueError:
                continue
            account = str(item.get("account") or "").strip()
            created_at = str(item.get("created_at") or "").strip()
            account_api = str(item.get("account_api") or "").strip()
            invite_code = str(item.get("invite_code") or "").strip()
            own_invite_code = str(item.get("own_invite_code") or "").strip()
            if account:
                rows.append(
                    AccountRow(
                        account,
                        created_at,
                        account_api,
                        invite_code,
                        own_invite_code,
                    )
                )
        return rows

    def _write_pending(self, rows: Iterable[AccountRow]) -> None:
        temp = self.pending_path.with_suffix(self.pending_path.suffix + ".tmp")
        with temp.open("w", encoding="utf-8", newline="\n") as handle:
            for row in rows:
                handle.write(
                    json.dumps(
                        {
                            "account": row.account,
                            "created_at": row.created_at,
                            "account_api": row.account_api,
                            "invite_code": row.invite_code,
                            "own_invite_code": row.own_invite_code,
                        },
                        ensure_ascii=False,
                    )
                    + "\n"
                )
        os.replace(temp, self.pending_path)

    def _clear_pending(self) -> None:
        try:
            self.pending_path.unlink()
        except FileNotFoundError:
            pass

    @staticmethod
    def _dedupe(rows: list[AccountRow]) -> list[AccountRow]:
        merged: dict[tuple[str, str], AccountRow] = {}
        order: list[tuple[str, str]] = []
        for row in rows:
            key = (row.account, row.created_at)
            if key not in merged:
                order.append(key)
                merged[key] = row
            else:
                existing = merged[key]
                merged[key] = AccountRow(
                    existing.account,
                    existing.created_at,
                    existing.account_api or row.account_api,
                    existing.invite_code or row.invite_code,
                    existing.own_invite_code or row.own_invite_code,
                )
        return [merged[key] for key in order]
