from __future__ import annotations

from muse_auto.vmos.adb import find_adb, hosts_from_adb, list_devices
from muse_auto.vmos.container import ContainerApi
from muse_auto.vmos.device import DeviceApi
from muse_auto.vmos.discovery import (
    DiscoveryResult,
    discover_hosts,
    discover_instances,
    load_instances,
    local_prefixes,
    scan_lan_hosts,
    select_instances,
)
from muse_auto.vmos.models import CONTAINER_PORT, VmosHost, VmosInstance, normalize_state
from muse_auto.vmos.transport import HttpTransport

__all__ = [
    "CONTAINER_PORT",
    "ContainerApi",
    "DeviceApi",
    "DiscoveryResult",
    "HttpTransport",
    "VmosHost",
    "VmosInstance",
    "discover_hosts",
    "discover_instances",
    "find_adb",
    "hosts_from_adb",
    "list_devices",
    "load_instances",
    "local_prefixes",
    "normalize_state",
    "scan_lan_hosts",
    "select_instances",
]
