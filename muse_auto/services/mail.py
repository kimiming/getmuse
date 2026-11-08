"""Disposable mailbox provider client.

Provider: https://api.online-disposablemail.com

Endpoints used:
    GET /api/balance
    GET /api/services
    GET /api/mailbox          (buy; costs account balance)
    GET /api/latest/code      (poll one order)

The API uses a JSON envelope with a business ``code``; 42001 means "waiting for
the code" and is treated as pending rather than an error.
"""

from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass
from typing import Any

from muse_auto.core.errors import MailError, Stopped
from muse_auto.core.stop import StopToken
from muse_auto.vmos.transport import HttpTransport

LOGGER = logging.getLogger("muse_auto.services.mail")

_PENDING_CODES = {401, 42001}
_FATAL_CODES = {42002, 42003, 42004, 42005, 42006}
_PENDING_PHRASES = (
    "waiting to receive verification code",
    "等待接取验证码",
    "waiting for code",
)


@dataclass(frozen=True)
class Mailbox:
    email: str
    order_id: str


@dataclass(frozen=True)
class MailCode:
    code: str | None
    content: str | None = None

    @property
    def found(self) -> bool:
        return bool(self.code)


class MailClient:
    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        timeout: float = 20.0,
        stop: StopToken | None = None,
    ) -> None:
        if not api_key:
            raise MailError("mail.api_key 未配置（可设置 MUSE_MAIL_API_KEY）")
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.stop = stop
        self.transport = HttpTransport(timeout=timeout, retries=1, stop=stop)
        self._service_cache: dict[str, str] | None = None

    # -- transport ---------------------------------------------------------

    def _url(self, path: str) -> str:
        return f"{self.base_url}/api/{path.lstrip('/')}"

    def _get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        query = {"apiKey": self.api_key}
        if params:
            query.update(params)
        url = self._url(path)
        try:
            return self.transport.request(url, params=query, timeout=25.0)
        except Stopped:
            raise
        except Exception as exc:  # noqa: BLE001 - normalise transport failures
            if isinstance(exc, MailError):
                raise
            raise MailError(f"邮箱接口请求失败：{exc}") from exc

    # -- account -----------------------------------------------------------

    def balance(self) -> float:
        data = self._get("balance")
        try:
            return float(data)
        except (TypeError, ValueError) as exc:
            raise MailError(f"余额返回格式异常：{data!r}") from exc

    def services(self) -> list[dict[str, Any]]:
        # /services does not require apiKey, but sending it is harmless.
        data = self._get("services")
        if not isinstance(data, list):
            raise MailError("services 返回格式异常")
        return [item for item in data if isinstance(item, dict)]

    def types(self) -> list[dict[str, Any]]:
        data = self._get("types")
        if not isinstance(data, list):
            raise MailError("types 返回格式异常")
        return [item for item in data if isinstance(item, dict)]

    def resolve_service(self, name: str) -> str:
        wanted = str(name or "").strip()
        if wanted.isdigit():
            return wanted
        if not wanted:
            raise MailError("mail.service 为空")

        if self._service_cache is None:
            cache: dict[str, str] = {}
            for service in self.services():
                service_id = str(service.get("serviceId") or "").strip()
                service_name = str(service.get("serviceName") or "").strip()
                if service_id and service_name:
                    cache[service_name.casefold()] = service_id
            self._service_cache = cache

        exact = self._service_cache.get(wanted.casefold())
        if exact:
            return exact
        for service_name, service_id in self._service_cache.items():
            if wanted.casefold() in service_name:
                return service_id
        raise MailError(f"邮箱服务商列表中没有找到 {wanted!r}")

    # -- mailboxes ---------------------------------------------------------

    def buy_mailbox(
        self,
        *,
        service: str | None = None,
        email_type_id: int | None = None,
        quantity: int = 1,
    ) -> Mailbox:
        service_id = self.resolve_service(service or "")
        if service_id == "302" and email_type_id is not None and int(email_type_id) != 26:
            raise MailError(
                "Meta Ai 只支持 emailTypeId=26（Gmail_1）；"
                f"{email_type_id}（如 25=Gmail_test）会返回 41001 Invalid parameter"
            )
        params: dict[str, Any] = {
            "serviceId": service_id,
            "quantity": max(1, int(quantity)),
        }
        if email_type_id:
            params["emailTypeId"] = int(email_type_id)

        data = self._get("mailbox", params)
        orders = data.get("orders") if isinstance(data, dict) else None
        if not isinstance(orders, list) or not orders:
            raise MailError(f"购买邮箱返回格式异常：{data!r}")
        order = orders[0]
        email = str(order.get("email") or "").strip()
        order_id = str(order.get("orderId") or "").strip()
        if not email or not order_id:
            raise MailError(f"购买邮箱缺少 email/orderId：{order!r}")
        LOGGER.info("已购买邮箱 %s（orderId=%s）", email, order_id)
        return Mailbox(email=email, order_id=order_id)

    # -- codes -------------------------------------------------------------

    def latest_code(self, order_id: str) -> MailCode | None:
        """Return the newest code, or ``None`` when the provider is still waiting."""
        try:
            data = self._get("latest/code", {"orderId": order_id})
        except MailError as exc:
            # The transport converts non-200 business codes into MailError only
            # at this layer; detect the common pending/fatal codes in the text.
            message = str(exc)
            lowered = message.casefold()
            if any(str(code) in message for code in _PENDING_CODES) or any(
                phrase.casefold() in lowered for phrase in _PENDING_PHRASES
            ):
                return None
            if any(str(code) in message for code in _FATAL_CODES):
                raise
            raise

        if not isinstance(data, dict):
            return None
        raw_code = data.get("code")
        content = data.get("content")
        code = str(raw_code).strip() if raw_code is not None else None
        if not code and content:
            code = extract_code(str(content))
        if not code:
            return MailCode(None, str(content) if content else None)
        return MailCode(code=code, content=str(content) if content else None)

    def wait_for_code(
        self,
        order_id: str,
        *,
        timeout: float,
        interval: float = 5.0,
        baseline: str | None = None,
    ) -> str:
        deadline = time.monotonic() + max(0.0, timeout)
        last_content: str | None = None
        while True:
            if self.stop is not None:
                self.stop.check()
            try:
                message = self.latest_code(order_id)
            except MailError:
                raise
            if message is not None and message.code:
                if baseline is None or message.code != baseline:
                    LOGGER.info("收到验证码：%s", message.code)
                    return message.code
            if message is not None and message.content:
                last_content = message.content

            remaining = deadline - time.monotonic()
            if remaining <= 0:
                suffix = f"（最后邮件片段：{last_content[:80]!r}）" if last_content else ""
                raise MailError(f"等待验证码超时（{timeout:g}s）{suffix}")
            sleep_for = min(interval, remaining)
            if self.stop is not None:
                self.stop.sleep(sleep_for)
            else:
                time.sleep(sleep_for)


_CODE_LABEL_RE = re.compile(
    r"(?:code|验证码|驗證碼|verification|otp)[^0-9]{0,24}(\d{6,8})(?!\d)",
    re.IGNORECASE,
)
_CODE_TAG_RE = re.compile(r">\s*(\d{6,8})\s*<")
_CODE_SPLIT_RE = re.compile(r"(?<!\d)(\d{3})[\s\-]+(\d{3})(?!\d)")
_CODE_RE = re.compile(r"(?<!\d)(\d{6,8})(?!\d)")


def extract_code(text: str) -> str | None:
    """Extract an OTP from either a plain string or a full HTML email."""
    if not text:
        return None
    for pattern in (_CODE_LABEL_RE, _CODE_TAG_RE):
        for match in pattern.finditer(text):
            value = match.group(1)
            if not _looks_like_year(value):
                return value
    split = _CODE_SPLIT_RE.search(text)
    if split:
        return split.group(1) + split.group(2)
    for match in _CODE_RE.finditer(text):
        value = match.group(1)
        if not _looks_like_year(value):
            return value
    return None


def _looks_like_year(value: str) -> bool:
    return len(value) == 4 or (value.startswith(("19", "20")) and len(value) <= 4)
