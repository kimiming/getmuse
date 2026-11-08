"""Android Control API for one VMOS instance.

All methods try the modern ``android_api/v2`` endpoint first and fall back to a
root shell command for older images. The fallbacks are deliberately kept in
this module: callers never build shell strings.
"""

from __future__ import annotations

import logging
import re
import shlex
import time
import urllib.parse
from pathlib import Path
from typing import Any, Iterable

from muse_auto.core.errors import DeviceError, VmosError
from muse_auto.core.stop import StopToken
from muse_auto.vmos.models import VmosInstance
from muse_auto.vmos.transport import HttpTransport

LOGGER = logging.getLogger("muse_auto.vmos.device")

_KEY_BACK = 4
_KEY_HOME = 3
_KEY_ENTER = 66
_KEY_DELETE = 67
_KEY_MOVE_END = 123
_KEY_CTRL_LEFT = 113
_KEY_A = 29

_PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


class DeviceApi:
    def __init__(
        self,
        instance: VmosInstance,
        *,
        timeout: float = 20.0,
        stop: StopToken | None = None,
        transport: HttpTransport | None = None,
    ) -> None:
        self.instance = instance
        self.timeout = timeout
        self.stop = stop
        self.transport = transport or HttpTransport(timeout=timeout, retries=1, stop=stop)
        self._db_id = urllib.parse.quote(instance.db_id, safe="")

    # -- URLs --------------------------------------------------------------

    @property
    def _base(self) -> str:
        return f"{self.instance.host.base_url}/android_api/v2/{self._db_id}"

    def _url(self, path: str) -> str:
        return f"{self._base}/{path.lstrip('/')}"

    def _call(
        self,
        path: str,
        *,
        method: str = "GET",
        params: dict[str, Any] | None = None,
        body: dict[str, Any] | None = None,
        timeout: float | None = None,
        retries: int | None = None,
    ) -> Any:
        try:
            return self.transport.request(
                self._url(path),
                method=method,
                params=params,
                body=body,
                timeout=timeout or self.timeout,
                retries=retries,
            )
        except VmosError as exc:
            raise DeviceError(
                f"设备接口失败 [{self.instance.name}] {path}：{exc}", url=getattr(exc, "url", "")
            ) from exc

    # -- legacy shell ------------------------------------------------------

    def shell(self, cmd: str, timeout: float = 30.0) -> str:
        url = (
            f"{self.instance.host.base_url}/android_api/v1/shell/{self._db_id}"
        )
        try:
            data = self.transport.request(
                url,
                method="POST",
                body={"cmd": str(cmd)},
                timeout=timeout,
                retries=0,
            )
        except VmosError as exc:
            raise DeviceError(f"shell 失败 [{self.instance.name}]：{exc}") from exc
        if isinstance(data, dict):
            return str(data.get("message") or data.get("output") or "")
        return str(data or "")

    # -- info --------------------------------------------------------------

    def version_info(self) -> dict[str, Any]:
        data = self._call("base/version_info", retries=0)
        return data if isinstance(data, dict) else {}

    def display_info(self) -> tuple[int, int]:
        try:
            data = self._call("display/info", retries=0)
            if isinstance(data, dict):
                width = int(data.get("width") or 0)
                height = int(data.get("height") or 0)
                if width > 0 and height > 0:
                    return width, height
        except (DeviceError, ValueError, TypeError):
            pass

        output = self.shell("wm size", timeout=10)
        for match in re.finditer(r"(\d{3,5})x(\d{3,5})", output):
            width, height = int(match.group(1)), int(match.group(2))
            if width > 0 and height > 0:
                return width, height
        raise DeviceError(f"无法读取屏幕尺寸 [{self.instance.name}]")

    def top_activity(self) -> dict[str, str]:
        """Return ``{"package_name": ..., "class_name": ...}``."""
        try:
            data = self._call("activity/top_activity", retries=0)
            if isinstance(data, dict):
                package = str(data.get("package_name") or "").strip()
                klass = str(data.get("class_name") or "").strip()
                if package:
                    return {"package_name": package, "class_name": klass}
        except DeviceError:
            pass

        output = self.shell(
            "dumpsys activity activities | grep -E 'topResumedActivity|mResumedActivity'",
            timeout=15,
        )
        match = re.search(r"([A-Za-z0-9_.]+)/([A-Za-z0-9_.$]+)", output)
        if match:
            return {"package_name": match.group(1), "class_name": match.group(2)}
        focus = self.shell("dumpsys window | grep -E 'mCurrentFocus|mFocusedApp'", timeout=15)
        match = re.search(r"([A-Za-z0-9_.]+)/([A-Za-z0-9_.$]+)", focus)
        if match:
            return {"package_name": match.group(1), "class_name": match.group(2)}
        return {"package_name": "", "class_name": ""}

    def list_packages(self, package_type: str = "user") -> list[dict[str, Any]]:
        try:
            data = self._call(
                "package/list",
                params={"type": package_type, "launcher_only": "false"},
                retries=0,
            )
            if isinstance(data, list):
                result: list[dict[str, Any]] = []
                for item in data:
                    if isinstance(item, dict):
                        name = item.get("package_name") or item.get("packageName") or item.get("name")
                        if name:
                            result.append(dict(item) | {"package_name": str(name)})
                    elif isinstance(item, str):
                        result.append({"package_name": item})
                return result
        except DeviceError:
            pass

        output = self.shell(
            "pm list packages -3" if package_type == "user" else "pm list packages",
            timeout=20,
        )
        return [
            {"package_name": line.split(":", 1)[1].strip()}
            for line in output.splitlines()
            if line.startswith("package:") and ":" in line
        ]

    def is_installed(self, package: str) -> bool:
        return any(item.get("package_name") == package for item in self.list_packages("user")) or any(
            item.get("package_name") == package for item in self.list_packages("all")
        )

    def app_version(self, package: str) -> str:
        for item in self.list_packages("all"):
            if item.get("package_name") == package:
                return str(item.get("version_name") or item.get("versionName") or "")
        return ""

    # -- app lifecycle -----------------------------------------------------

    def start_app(self, package: str) -> None:
        try:
            self._call("activity/start", method="POST", body={"package_name": package}, timeout=20)
            return
        except DeviceError:
            pass
        self.shell(
            f"monkey -p {shlex.quote(package)} -c android.intent.category.LAUNCHER 1",
            timeout=25,
        )

    def force_stop(self, package: str) -> None:
        try:
            self._call(
                "activity/force_stop",
                method="POST",
                body={"package_name": package},
                timeout=15,
            )
            return
        except DeviceError:
            pass
        self.shell(f"am force-stop {shlex.quote(package)}", timeout=15)

    def clear_data(self, package: str) -> bool:
        output = self.shell(f"pm clear {shlex.quote(package)}", timeout=30)
        return "Success" in output or "成功" in output

    # -- UI tree -----------------------------------------------------------

    def dump(self, timeout: float = 20.0) -> str:
        try:
            data = self._call("accessibility/dump", timeout=timeout)
            xml = data.get("xml") if isinstance(data, dict) else data
            if isinstance(xml, str) and self._valid_xml(xml):
                return xml
            if isinstance(xml, str) and "<hierarchy" in xml:
                LOGGER.debug("[%s] v2 控件树不完整，尝试 uiautomator", self.instance.name)
        except DeviceError as exc:
            LOGGER.debug("[%s] v2 dump 失败，尝试 uiautomator：%s", self.instance.name, exc)
        return self.dump_uiautomator()

    def dump_uiautomator(self) -> str:
        """Force a shell uiautomator dump (needed for system permission dialogs)."""
        remote = f"/sdcard/_muse_{re.sub(r'[^A-Za-z0-9]', '', self.instance.db_id)}.xml"
        self.shell(f"uiautomator dump {remote} >/dev/null 2>&1", timeout=25)
        try:
            raw = self.transport.request(
                self._url("file/export"),
                params={"path": remote},
                binary=True,
                timeout=25,
                retries=0,
            )
            if isinstance(raw, bytes):
                xml = raw.decode("utf-8", "replace")
                if self._valid_xml(xml):
                    return xml
        except VmosError:
            pass

        # Last resort for images where file/export is unavailable.
        xml = self.shell(f"cat {remote}", timeout=25)
        if self._valid_xml(xml):
            return xml
        raise DeviceError(f"控件树读取失败或 XML 不完整 [{self.instance.name}]")

    @staticmethod
    def _valid_xml(xml: str) -> bool:
        if not isinstance(xml, str) or "<hierarchy" not in xml:
            return False
        xml = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", xml)
        try:
            import xml.etree.ElementTree as ET

            ET.fromstring(xml)
            return True
        except Exception:  # noqa: BLE001
            return False

    # -- input -------------------------------------------------------------

    def click(self, x: int, y: int) -> None:
        try:
            self._call(
                "input/click",
                method="POST",
                body={"x": int(x), "y": int(y)},
                timeout=15,
            )
            return
        except DeviceError:
            pass
        self.shell(f"input tap {int(x)} {int(y)}", timeout=15)

    def swipe(self, start_x: int, start_y: int, end_x: int, end_y: int, duration: int = 300) -> None:
        # Shell first: on some Compose screens the v2 swipe returns 200 but the
        # list does not move (same class of bug as v2 input/text).
        try:
            self.shell(
                f"input swipe {int(start_x)} {int(start_y)} {int(end_x)} {int(end_y)} {int(duration)}",
                timeout=20,
            )
            return
        except DeviceError:
            pass
        try:
            self._call(
                "input/swipe",
                method="POST",
                body={
                    "start_x": int(start_x),
                    "start_y": int(start_y),
                    "end_x": int(end_x),
                    "end_y": int(end_y),
                    "duration": int(duration),
                },
                timeout=20,
            )
        except DeviceError as exc:
            raise DeviceError(f"滑动失败 [{self.instance.name}]：{exc}") from exc

    def text(self, value: str, *, verify: bool = True) -> None:
        """Input text into the focused field.

        Some VMOS images return HTTP 200 for ``input/text`` without actually
        typing anything (seen on Compose screens), while their root shell
        ``input text`` works. For ASCII (email/code/date/invite) we use the
        shell path and verify the result. Non-ASCII goes through the v2
        endpoint, which is the only route that reliably handles it.

        ``verify=False`` is used for OTP fields: Muse auto-submits and removes
        the field on the last digit, so the post-input tree check must not turn
        a successful submission into a failure.
        """
        value = str(value)
        if not value:
            return

        if value.isascii():
            try:
                escaped = value.replace(" ", "%s")
                self.shell(f"input text {shlex.quote(escaped)}", timeout=25)
            except DeviceError as exc:
                raise DeviceError(
                    f"输入文本失败 [{self.instance.name}]：{exc}"
                ) from exc
            time.sleep(0.45)
            if not verify or len(value) < 3 or self._text_present(value):
                return
            raise DeviceError(
                f"输入文本失败 [{self.instance.name}]：shell 已发送但控件树中未出现该文本"
            )

        try:
            self._call("input/text", method="POST", body={"text": value}, timeout=25)
        except DeviceError as exc:
            raise DeviceError(
                f"输入文本失败 [{self.instance.name}]：{exc}"
            ) from exc
        time.sleep(0.45)
        if not verify or self._text_present(value):
            return
        raise DeviceError(
            f"输入文本失败 [{self.instance.name}]：v2 已发送但控件树中未出现该文本"
        )

    def clear_chars(self, count: int) -> None:
        """Send ``count`` BACKSPACE key events to the focused field."""
        count = max(0, int(count))
        if not count:
            return
        # Android's `input keyevent` accepts multiple codes; batching keeps this
        # to one HTTP call for normal field lengths.
        codes = " ".join([str(_KEY_DELETE)] * min(count, 120))
        self.shell(f"input keyevent {codes}", timeout=60)

    def _text_present(self, value: str) -> bool:
        """Best-effort check that the focused field really contains ``value``.

        Accessibility often lags a few hundred ms behind the input event, so
        retry the dump instead of declaring failure (and potentially typing the
        value twice).
        """
        variants = (value, value.replace(" ", "%s"))
        for attempt in range(3):
            try:
                xml = self.dump(timeout=10)
            except DeviceError:
                return True  # cannot verify; do not double-type
            if any(variant in xml for variant in variants):
                return True
            if attempt < 2:
                time.sleep(0.45)
        return False

    def key(self, key_code: int | Iterable[int]) -> None:
        if isinstance(key_code, int):
            body: dict[str, Any] = {"key_code": key_code}
        else:
            body = {"key_codes": [int(item) for item in key_code]}
        try:
            self._call("input/keyevent", method="POST", body=body, timeout=15)
            return
        except DeviceError:
            pass
        codes = [key_code] if isinstance(key_code, int) else list(key_code)
        for code in codes:
            self.shell(f"input keyevent {int(code)}", timeout=15)

    def back(self) -> None:
        self.key(_KEY_BACK)

    def enter(self) -> None:
        self.key(_KEY_ENTER)

    def select_all_and_delete(self) -> None:
        """Clear the focused text field."""
        try:
            self.key([_KEY_CTRL_LEFT, _KEY_A])
            time.sleep(0.15)
            self.key(_KEY_DELETE)
        except DeviceError:
            self.shell(f"input keyevent {_KEY_MOVE_END}", timeout=10)
            self.shell("input keyevent 67", timeout=10)

    # -- screen ------------------------------------------------------------

    def screenshot(self, path: Path, timeout: float = 30.0) -> Path:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            raw = self.transport.request(
                self._url("screenshot/format"),
                params={"format": "png", "quality": 100},
                timeout=timeout,
                binary=True,
                retries=0,
            )
            if isinstance(raw, bytes) and raw.startswith(_PNG_SIGNATURE):
                path.write_bytes(raw)
                return path
        except VmosError as exc:
            LOGGER.debug("[%s] v2 截图失败，尝试 screencap：%s", self.instance.name, exc)

        remote = f"/sdcard/_muse_{re.sub(r'[^A-Za-z0-9]', '', self.instance.db_id)}.png"
        try:
            self.shell(f"screencap -p {remote}", timeout=60)
            raw = self.transport.request(
                self._url("file/export"),
                params={"path": remote},
                timeout=timeout,
                binary=True,
                retries=0,
            )
            if isinstance(raw, bytes) and raw.startswith(_PNG_SIGNATURE):
                path.write_bytes(raw)
                return path
        except VmosError as exc:
            raise DeviceError(f"截图失败 [{self.instance.name}]：{exc}") from exc
        raise DeviceError(f"截图不是 PNG [{self.instance.name}]")
