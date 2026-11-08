"""Yich8 IMAP read API client for replacement email verification codes.

The endpoint is an HTTP GET whose ``username`` query parameter is the mailbox
address; the API key/IMAP settings are fixed in ``changeEmailapi.txt``.
"""

from __future__ import annotations

import logging
import re
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from muse_auto.core.errors import MailError
from muse_auto.core.stop import StopToken
from muse_auto.services.mail import extract_code

LOGGER = logging.getLogger("muse_auto.services.yich8")
_MBOX_RE = re.compile(r"mbox_id\s*[:：]\s*(\d+)", re.IGNORECASE)


def read_api_template(path: str | Path) -> str:
    file_path = Path(path)
    if not file_path.exists():
        raise MailError(f"邮箱 API 文件不存在：{file_path}")
    for line in file_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line.startswith("http"):
            return line
    raise MailError(f"邮箱 API 文件中没有 http 地址：{file_path}")


def api_with_username(template: str, email: str) -> str:
    """Return the API URL with ``username`` replaced, keeping the email raw.

    The account ledger is read by humans/other tools, so the stored URL keeps
    ``username=xxx@yich8.com`` instead of percent-encoding the ``@``.
    """
    template = str(template or "").strip()
    email = str(email or "").strip()
    if not template:
        return ""
    if re.search(r"([?&])username=", template):
        return re.sub(
            r"([?&]username=)[^&]*",
            lambda match: match.group(1) + email,
            template,
            count=1,
        )
    joiner = "&" if "?" in template else "?"
    return f"{template}{joiner}username={email}"


@dataclass(frozen=True)
class Yich8Message:
    code: str
    mbox_id: int
    content: str = ""


class Yich8MailClient:
    def __init__(
        self,
        api_url: str,
        *,
        timeout: float = 25.0,
        stop: StopToken | None = None,
    ) -> None:
        template = str(api_url or "").strip()
        if not template.startswith("http"):
            raise MailError("邮箱 API 地址必须以 http 开头")
        self.api_url = template
        self.timeout = timeout
        self.stop = stop

    @classmethod
    def from_file(cls, path: str | Path, **kwargs) -> "Yich8MailClient":
        return cls(read_api_template(path), **kwargs)

    def url_for(self, email: str) -> str:
        parts = urllib.parse.urlsplit(self.api_url)
        query = dict(urllib.parse.parse_qsl(parts.query, keep_blank_values=True))
        query["username"] = str(email).strip()
        return urllib.parse.urlunsplit(
            (parts.scheme, parts.netloc, parts.path, urllib.parse.urlencode(query), parts.fragment)
        )

    def fetch(self, email: str) -> str:
        request = urllib.request.Request(
            self.url_for(email), headers={"User-Agent": "muse-auto/0.1"}
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                return response.read().decode("utf-8", "replace")
        except Exception as exc:  # noqa: BLE001
            raise MailError(f"读取邮箱失败：{exc}") from exc

    def max_mbox_id(self, email: str) -> int:
        text = self.fetch(email)
        ids = [int(value) for value in _MBOX_RE.findall(text)]
        return max(ids) if ids else 0

    def latest_code(self, email: str, baseline: int = 0) -> Yich8Message | None:
        text = self.fetch(email)
        if "无邮件" in text:
            return None
        matches = list(_MBOX_RE.finditer(text))
        if not matches:
            return None
        latest = max(matches, key=lambda item: int(item.group(1)))
        mbox_id = int(latest.group(1))
        if mbox_id <= baseline:
            return None
        end = len(text)
        for other in matches:
            if other.start() > latest.start():
                end = min(end, other.start())
        block = text[latest.start():end]
        code = extract_code(block)
        if not code:
            return None
        return Yich8Message(code=code, mbox_id=mbox_id, content=block)

    def wait_for_code(
        self,
        email: str,
        *,
        baseline: int = 0,
        timeout: float = 180.0,
        interval: float = 4.0,
    ) -> str:
        deadline = time.monotonic() + max(1.0, timeout)
        while True:
            if self.stop is not None:
                self.stop.check()
            message = self.latest_code(email, baseline)
            if message is not None:
                LOGGER.info("收到 %s 的验证码：%s", email, message.code)
                return message.code
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise MailError(f"等待 {email} 的验证码超时（{timeout:g}s）")
            pause = min(interval, remaining)
            if self.stop is not None:
                self.stop.sleep(pause)
            else:
                time.sleep(pause)
