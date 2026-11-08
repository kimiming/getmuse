"""Outlook registration mailboxes via Microsoft Graph + OAuth2 refresh tokens.

File format (one account per line):

    email----password----client_id----refresh_token

The refresh token is exchanged at the Microsoft common token endpoint, then
``/me/messages`` is read. One account is consumed per registration.
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from muse_auto.core.errors import MailError
from muse_auto.core.stop import StopToken
from muse_auto.services.mail import Mailbox, MailCode, extract_code

LOGGER = logging.getLogger("muse_auto.services.outlook_mail")
_LOCK = threading.RLock()
_TOKEN_URL = "https://login.microsoftonline.com/common/oauth2/v2.0/token"
_GRAPH_SCOPE = "https://graph.microsoft.com/.default offline_access"
_GRAPH_MESSAGES = "https://graph.microsoft.com/v1.0/me/messages"


@dataclass
class OutlookAccount:
    email: str
    password: str
    client_id: str
    refresh_token: str
    access_token: str = ""
    expires_at: float = 0.0


class OutlookMailProvider:
    """Same subset as ``MailClient`` used by RegisterFlow."""

    provider_name = "Outlook邮箱"

    def __init__(
        self,
        path: str | Path,
        *,
        timeout: float = 30.0,
        stop: StopToken | None = None,
    ) -> None:
        self.path = Path(path)
        self.timeout = timeout
        self.stop = stop
        self._accounts: dict[str, OutlookAccount] = {}

    # -- mailboxes ---------------------------------------------------------

    def buy_mailbox(self, *, service: str | None = None, email_type_id: int | None = None) -> Mailbox:
        with _LOCK:
            lines = self._read_lines()
            if not lines:
                raise MailError(f"Outlook 邮箱文件为空：{self.path}")
            line = lines.pop(0)
            self._write_lines(lines)
        parts = line.split("----", 3)
        if len(parts) != 4:
            raise MailError(f"Outlook 邮箱行格式错误（需要 4 段）：{line[:80]!r}")
        email, password, client_id, refresh_token = [part.strip() for part in parts]
        if not email or not client_id or not refresh_token:
            raise MailError("Outlook 邮箱缺少 email/client_id/refresh_token")
        with _LOCK:
            self._accounts[email] = OutlookAccount(
                email=email,
                password=password,
                client_id=client_id,
                refresh_token=refresh_token,
            )
        LOGGER.info("已取用 Outlook 邮箱 %s", email)
        return Mailbox(email=email, order_id=email)

    def balance(self) -> float:
        return float(self.remaining())

    def remaining(self) -> int:
        with _LOCK:
            return len(self._read_lines())

    # -- code --------------------------------------------------------------

    def latest_code(self, order_id: str) -> MailCode | None:
        account = self._account(order_id)
        token = self._access_token(account)
        data = self._graph_messages(token)
        for message in data.get("value", []) if isinstance(data, dict) else []:
            text = self._message_text(message)
            code = extract_code(text)
            if code:
                return MailCode(code=code, content=text[:2000])
        return None

    def wait_for_code(
        self,
        order_id: str,
        *,
        timeout: float,
        interval: float = 5.0,
        baseline: str | None = None,
    ) -> str:
        deadline = time.monotonic() + max(0.0, timeout)
        while True:
            if self.stop is not None:
                self.stop.check()
            message = self.latest_code(order_id)
            if message is not None and message.code:
                if baseline is None or message.code != baseline:
                    LOGGER.info("收到 Outlook 验证码：%s", message.code)
                    return message.code
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise MailError(f"等待 Outlook 验证码超时（{timeout:g}s）")
            pause = min(interval, remaining)
            if self.stop is not None:
                self.stop.sleep(pause)
            else:
                time.sleep(pause)

    # -- auth / graph ------------------------------------------------------

    def _account(self, order_id: str) -> OutlookAccount:
        with _LOCK:
            account = self._accounts.get(order_id)
            if account is None:
                account = next(
                    (item for item in self._accounts.values() if item.email == order_id),
                    None,
                )
        if account is None:
            raise MailError(f"Outlook 邮箱未取用：{order_id}")
        return account

    def _access_token(self, account: OutlookAccount) -> str:
        now = time.time()
        if account.access_token and account.expires_at > now + 60:
            return account.access_token
        data = urllib.parse.urlencode(
            {
                "client_id": account.client_id,
                "grant_type": "refresh_token",
                "refresh_token": account.refresh_token,
                "scope": _GRAPH_SCOPE,
            }
        ).encode()
        request = urllib.request.Request(
            _TOKEN_URL,
            data=data,
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "User-Agent": "muse-auto/0.1",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                payload = json.loads(response.read().decode("utf-8", "replace"))
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", "replace")
            raise MailError(
                f"Outlook OAuth2 刷新失败 HTTP {exc.code}：{_safe_error(body)}"
            ) from exc
        except Exception as exc:  # noqa: BLE001
            raise MailError(f"Outlook OAuth2 请求失败：{exc}") from exc
        token = str(payload.get("access_token") or "")
        if not token:
            raise MailError(f"Outlook OAuth2 返回缺少 access_token：{_safe_error(payload)}")
        account.access_token = token
        account.expires_at = time.time() + max(60, int(payload.get("expires_in") or 3600))
        new_refresh = str(payload.get("refresh_token") or "")
        if new_refresh:
            account.refresh_token = new_refresh
        return token

    def _graph_messages(self, access_token: str) -> dict:
        query = urllib.parse.urlencode(
            {
                "$top": "10",
                "$select": "subject,receivedDateTime,bodyPreview,body",
                "$orderby": "receivedDateTime desc",
            }
        )
        request = urllib.request.Request(
            f"{_GRAPH_MESSAGES}?{query}",
            headers={
                "Authorization": f"Bearer {access_token}",
                "Accept": "application/json",
                "User-Agent": "muse-auto/0.1",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                return json.loads(response.read().decode("utf-8", "replace"))
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", "replace")
            raise MailError(
                f"Outlook Graph 读取失败 HTTP {exc.code}：{_safe_error(body)}"
            ) from exc
        except Exception as exc:  # noqa: BLE001
            raise MailError(f"Outlook Graph 请求失败：{exc}") from exc

    @staticmethod
    def _message_text(message: dict) -> str:
        parts = [str(message.get("subject") or ""), str(message.get("bodyPreview") or "")]
        body = message.get("body")
        if isinstance(body, dict):
            parts.append(str(body.get("content") or ""))
        return "\n".join(parts)

    # -- file --------------------------------------------------------------

    def _read_lines(self) -> list[str]:
        if not self.path.exists():
            return []
        return [
            line.strip()
            for line in self.path.read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.strip().startswith("#")
        ]

    def _write_lines(self, lines: list[str]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp = self.path.with_suffix(self.path.suffix + ".tmp")
        with temp.open("w", encoding="utf-8", newline="\n") as handle:
            for line in lines:
                handle.write(line + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp, self.path)


def _safe_error(payload) -> str:
    text = payload if isinstance(payload, str) else json.dumps(payload, ensure_ascii=False)
    return text[:300]
