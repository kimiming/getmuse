"""Muse (Meta) Android application definition.

Only package/activity facts live here. Page text, buttons, and business steps
live in ``pages.py`` and ``flows/``.
"""

from __future__ import annotations

import logging
import time

from muse_auto.core.errors import DeviceError
from muse_auto.core.stop import StopToken
from muse_auto.vmos.device import DeviceApi

LOGGER = logging.getLogger("muse_auto.apps.muse.app")


class MuseApp:
    # Google Play: "Muse from Meta", package com.facebook.aura
    PACKAGE = "com.facebook.aura"
    NAME = "Muse (Meta)"
    # These system surfaces can legitimately be on top right after launch.
    STARTUP_OVERLAYS = (
        "com.android.credentialmanager",
        "com.google.android.gms",
        "com.android.permissioncontroller",
        "com.google.android.permissioncontroller",
    )

    def __init__(
        self,
        device: DeviceApi,
        *,
        package: str = PACKAGE,
        launch_wait: float = 8.0,
        stop: StopToken | None = None,
    ) -> None:
        self.device = device
        self.package = package
        self.launch_wait = max(1.0, launch_wait)
        self._stop = stop

    # -- package -----------------------------------------------------------

    def installed(self) -> bool:
        return self.device.is_installed(self.package)

    def version(self) -> str:
        return self.device.app_version(self.package)

    # -- foreground --------------------------------------------------------

    def top(self) -> dict[str, str]:
        return self.device.top_activity()

    def in_foreground(self) -> bool:
        return self.top().get("package_name") == self.package

    def launch(self, *, force_stop: bool = True) -> None:
        if force_stop:
            try:
                self.device.force_stop(self.package)
            except DeviceError:
                pass
        self.device.start_app(self.package)
        if not self.wait_started(self.launch_wait + 12.0):
            top = self.top()
            raise DeviceError(
                f"Muse 未进入前台（当前 {top.get('package_name') or '未知'}/"
                f"{top.get('class_name') or '未知'}）"
            )
        # Let the first screen settle; RN apps often show a splash then a form.
        if self._stop is not None:
            self._stop.sleep(1.5)
        else:
            time.sleep(1.5)

    def wait_foreground(self, timeout: float = 20.0, interval: float = 0.8) -> bool:
        deadline = time.monotonic() + max(0.0, timeout)
        while True:
            if self._stop is not None:
                self._stop.check()
            try:
                if self.in_foreground():
                    return True
            except Exception:  # noqa: BLE001 - transient device errors while booting
                pass
            if time.monotonic() >= deadline:
                return False
            if self._stop is not None:
                self._stop.sleep(interval)
            else:
                time.sleep(interval)

    def wait_started(self, timeout: float = 20.0, interval: float = 0.8) -> bool:
        """Wait until Muse or one of its immediate system overlays is on top."""
        deadline = time.monotonic() + max(0.0, timeout)
        while True:
            if self._stop is not None:
                self._stop.check()
            try:
                top = self.top().get("package_name", "")
            except Exception:  # noqa: BLE001
                top = ""
            if top == self.package:
                return True
            if top in self.STARTUP_OVERLAYS:
                LOGGER.info("启动后被系统弹层覆盖：%s", top)
                return True
            if time.monotonic() >= deadline:
                return False
            if self._stop is not None:
                self._stop.sleep(interval)
            else:
                time.sleep(interval)

    def force_stop(self) -> None:
        try:
            self.device.force_stop(self.package)
        except DeviceError:
            LOGGER.debug("force-stop 失败", exc_info=True)

    def clear_data(self) -> bool:
        return self.device.clear_data(self.package)
