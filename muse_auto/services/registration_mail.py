"""Registration mailboxes supplied by ``registerEmail.txt.txt``.

Each line is ``email----verification_api_url``. One line is consumed per
registration. The API is polled until it returns a verification code (plain
text, HTML or JSON are all accepted).
"""

from __future__ import annotations

import json
import logging
import re
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from muse_auto.core.errors import MailError
from muse_auto.core.stop import StopToken
from muse_auto.services.mail import Mailbox, MailCode, extract_code

LOGGER = logging.getLogger("muse_auto.services.registration_mail")
_LOCK = threading.RLock()
_CODE_KEYS = (
    "code",
    "verificationcode",
    "verification_code",
    "otp",
    "otpcode",
    "pin",
    "captcha",
)
_CODE_DIGITS = re.compile(r"(?<!\d)(\d{6})(?!\d)")


class CustomMailProvider:
    """Same interface subset as ``MailClient`` used by RegisterFlow."""

    provider_name = "自选邮箱API"

    def __init__(
        self,
        path: str | Path,
        *,
        timeout: float = 25.0,
        stop: StopToken | None = None,
    ) -> None:
        self.path = Path(path)
        self.timeout = timeout
        self.stop = stop
        self._last_text = ""
        self._last_logged = ""

    # -- mailboxes ---------------------------------------------------------

    def buy_mailbox(self, *, service: str | None = None, email_type_id: int | None = None) -> Mailbox:
        with _LOCK:
            lines = self._read_lines()
            if not lines:
                raise MailError(f"自选邮箱文件为空：{self.path}")
            line = lines.pop(0)
            self._write_lines(lines)
        email, _, api_url = line.partition("----")
        email = email.strip()
        api_url = api_url.strip()
        if not email or not api_url.startswith("http"):
            raise MailError(f"自选邮箱行格式错误：{line!r}")
        LOGGER.info("已取用自选邮箱 %s", email)
        return Mailbox(email=email, order_id=api_url)

    def balance(self) -> float:
        return float(self.remaining())

    def remaining(self) -> int:
        with _LOCK:
            return len(self._read_lines())

    # -- code --------------------------------------------------------------

    def latest_code(self, order_id: str) -> MailCode | None:
        text = self._fetch(order_id)
        if not text.strip():
            return None
        self._last_text = text
        code = self._extract(text)
        if code:
            return MailCode(code=code, content=text)
        if text != self._last_logged:
            self._last_logged = text
            LOGGER.info("自选邮箱 API 暂无 6 位验证码，响应片段：%r", text[:300])
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
            try:
                message = self.latest_code(order_id)
            except MailError:
                raise
            if message is not None and message.code:
                if baseline is None or message.code != baseline:
                    LOGGER.info("收到自选邮箱验证码：%s", message.code)
                    return message.code
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                suffix = (
                    f"；最后响应：{self._last_text[:120]!r}"
                    if self._last_text
                    else ""
                )
                raise MailError(f"等待自选邮箱验证码超时（{timeout:g}s）{suffix}")
            pause = min(interval, remaining)
            if self.stop is not None:
                self.stop.sleep(pause)
            else:
                time.sleep(pause)

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
            import os

            os.fsync(handle.fileno())
        import os

        os.replace(temp, self.path)

    # -- API parse ---------------------------------------------------------

    def _fetch(self, url: str) -> str:
        request = urllib.request.Request(
            url,
            headers={
                "User-Agent": "muse-auto/0.1",
                "Accept": "application/json, text/plain, text/html",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                if response.status in (204, 404):
                    return ""
                return response.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as exc:
            if exc.code in (204, 404):
                return ""
            raise MailError(f"自选邮箱 API HTTP {exc.code}") from exc
        except Exception as exc:  # noqa: BLE001
            raise MailError(f"自选邮箱 API 请求失败：{exc}") from exc

    @classmethod
    def _extract(cls, text: str) -> str | None:
        stripped = text.strip()
        try:
            data = json.loads(stripped)
        except ValueError:
            data = None
        if data is not None:
            for candidate in cls._json_code_candidates(data):
                code = extract_code(candidate) or cls._six_digits(candidate)
                if code:
                    return code
        return extract_code(stripped) or cls._six_digits(stripped)

    @classmethod
    def _json_code_candidates(cls, value: Any):
        if isinstance(value, dict):
            for key, item in value.items():
                key_norm = str(key).casefold().replace(" ", "")
                if key_norm in _CODE_KEYS:
                    yield str(item)
            for item in value.values():
                yield from cls._json_code_candidates(item)
        elif isinstance(value, list):
            for item in value:
                yield from cls._json_code_candidates(item)
        elif isinstance(value, (str, int)):
            yield str(value)

    @staticmethod
    def _six_digits(value: str) -> str | None:
        match = _CODE_DIGITS.search(str(value))
        return match.group(1) if match else None
