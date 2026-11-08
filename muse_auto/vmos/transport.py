"""HTTP transport for VMOS Edge.

This is the only module that opens sockets directly. It bypasses system HTTP
proxies (the API is on a trusted LAN), retries idempotent transient failures,
and normalises the VMOS envelope ``{"code": 200, "data": ...}``.

It also supports binary responses for screenshots.
"""

from __future__ import annotations

import json
import logging
import socket
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from muse_auto.core.errors import (
    Stopped,
    VmosApiError,
    VmosConnectionError,
    VmosError,
)
from muse_auto.core.stop import StopToken

LOGGER = logging.getLogger("muse_auto.vmos.transport")

# No system proxy: these endpoints are local-LAN only.
_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


class HttpTransport:
    def __init__(
        self,
        *,
        timeout: float = 20.0,
        retries: int = 2,
        stop: StopToken | None = None,
    ) -> None:
        self.timeout = timeout
        self.retries = max(0, retries)
        self.stop = stop

    # -- low level ---------------------------------------------------------

    def request(
        self,
        url: str,
        *,
        method: str = "GET",
        params: dict[str, Any] | None = None,
        body: dict[str, Any] | None = None,
        timeout: float | None = None,
        binary: bool = False,
        retries: int | None = None,
    ) -> Any:
        if params:
            query = urllib.parse.urlencode(
                {key: value for key, value in params.items() if value is not None},
                doseq=True,
            )
            url = f"{url}{'&' if '?' in url else '?'}{query}"

        data: bytes | None = None
        headers = {
            "Accept": "application/json, image/*",
            "User-Agent": "muse-auto/0.1",
        }
        if body is not None:
            data = json.dumps(body, ensure_ascii=False).encode("utf-8")
            headers["Content-Type"] = "application/json; charset=utf-8"

        attempts = self.retries + 1 if retries is None else max(1, retries)
        last_error: BaseException | None = None

        for attempt in range(1, attempts + 1):
            if self.stop is not None:
                self.stop.check()
            request = urllib.request.Request(url, data=data, method=method, headers=headers)
            try:
                with _OPENER.open(request, timeout=timeout or self.timeout) as response:
                    raw = response.read()
                    content_type = response.headers.get("Content-Type", "")
                if binary:
                    return raw
                return self._decode(raw, url, content_type)
            except urllib.error.HTTPError as exc:
                raw = exc.read()
                detail = raw[:300].decode("utf-8", "replace")
                error = VmosApiError(
                    f"HTTP {exc.code}：{detail}", code=exc.code, url=url
                )
                # 404/400 are configuration or compatibility problems: do not retry.
                if exc.code < 500:
                    raise error from exc
                last_error = error
            except (urllib.error.URLError, TimeoutError, socket.timeout) as exc:
                last_error = VmosConnectionError(f"连接失败：{exc}", url=url)
            except Stopped:
                raise
            except VmosError:
                raise

            if attempt < attempts:
                pause = 0.35 * attempt
                if self.stop is not None:
                    self.stop.sleep(pause)
                else:
                    time.sleep(pause)

        assert last_error is not None
        raise last_error

    @staticmethod
    def _decode(raw: bytes, url: str, content_type: str) -> Any:
        if "json" not in content_type.lower():
            # Some endpoints omit a content type; only parse if it looks like JSON.
            text = raw[:1].decode("utf-8", "replace")
            if text not in {"{", "["}:
                raise VmosApiError(
                    f"响应不是 JSON（Content-Type={content_type!r}）", url=url
                )
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise VmosApiError(f"JSON 解析失败：{exc}", url=url) from exc

        if isinstance(payload, dict) and "code" in payload:
            code = payload.get("code")
            try:
                numeric = int(code)
            except (TypeError, ValueError):
                numeric = None
            if numeric not in (0, 200, None):
                raise VmosApiError(
                    f"VMOS 业务错误 code={code} msg={payload.get('msg') or payload.get('message') or ''}",
                    code=numeric,
                    url=url,
                )
            if "data" in payload:
                return payload["data"]
        return payload

    def close(self) -> None:
        # urllib has no persistent session to close; kept for symmetry.
        return None
