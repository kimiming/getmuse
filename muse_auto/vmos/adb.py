"""ADB discovery helper.

ADB is only used to discover host IPs (``adb devices``). All device actions go
through the VMOS HTTP API so behaviour is identical on hosts without ADB.
"""

from __future__ import annotations

import logging
import os
import re
import shutil
import subprocess
from pathlib import Path

LOGGER = logging.getLogger("muse_auto.vmos.adb")


def find_adb() -> str:
    candidates: list[Path] = []
    env = os.environ.get("ADB")
    if env:
        candidates.append(Path(env))
    candidates.extend(
        [
            Path.cwd() / "platform-tools" / ("adb.exe" if os.name == "nt" else "adb"),
            Path(__file__).resolve().parents[2] / "platform-tools" / ("adb.exe" if os.name == "nt" else "adb"),
        ]
    )
    for candidate in candidates:
        if candidate.is_file():
            return str(candidate)
    return shutil.which("adb") or ""


def list_devices(timeout: float = 8.0) -> list[tuple[str, str]]:
    """Return ``[(serial, state), ...]`` from ``adb devices``."""
    adb = find_adb()
    if not adb:
        return []
    try:
        proc = subprocess.run(
            [adb, "devices"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        LOGGER.debug("adb devices 失败：%s", exc)
        return []

    devices: list[tuple[str, str]] = []
    for raw in (proc.stdout or "").splitlines():
        line = raw.strip()
        if not line or line.startswith("List of devices"):
            continue
        parts = line.split()
        if len(parts) >= 2:
            devices.append((parts[0], parts[1]))
    return devices


def hosts_from_adb() -> list[str]:
    """Extract LAN IPs from ``IP:port`` ADB serials (skip localhost)."""
    hosts: list[str] = []
    for serial, state in list_devices():
        if state != "device" or ":" not in serial:
            continue
        ip = serial.rsplit(":", 1)[0].strip()
        if not re.fullmatch(r"\d{1,3}(?:\.\d{1,3}){3}", ip):
            continue
        if ip in {"127.0.0.1", "0.0.0.0"} or ip.startswith("127."):
            continue
        if ip not in hosts:
            hosts.append(ip)
    return hosts
