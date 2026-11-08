"""Host discovery and instance enumeration.

Host sources, in order:

1. explicit ``vmos.hosts`` / ``--host``
2. host IPs found in ``adb devices``
3. a local private /24 scan on port 18182

The scan is TCP-connect based, then every open host is verified with
``/v1/net_info``. Only hosts that actually speak the VMOS protocol are kept.
"""

from __future__ import annotations

import concurrent.futures
import ipaddress
import logging
import socket
from dataclasses import dataclass, field
from typing import Callable, Iterable, Sequence

from muse_auto.core.stop import StopToken
from muse_auto.vmos.adb import hosts_from_adb
from muse_auto.vmos.container import ContainerApi
from muse_auto.vmos.models import CONTAINER_PORT, VmosHost, VmosInstance
from muse_auto.vmos.transport import HttpTransport

LOGGER = logging.getLogger("muse_auto.vmos.discovery")

ProgressCallback = Callable[[int, int], None]


@dataclass
class DiscoveryResult:
    hosts: list[VmosHost] = field(default_factory=list)
    instances: list[VmosInstance] = field(default_factory=list)
    failures: list[str] = field(default_factory=list)
    scanned: int = 0

    @property
    def running(self) -> list[VmosInstance]:
        return [item for item in self.instances if item.running]


# ---------------------------------------------------------------------------
# Local network
# ---------------------------------------------------------------------------


def local_ipv4_addresses() -> list[str]:
    addresses: list[str] = []
    for target in ("223.5.5.5", "8.8.8.8"):
        probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            probe.connect((target, 53))
            addresses.append(probe.getsockname()[0])
        except OSError:
            pass
        finally:
            probe.close()
    try:
        _name, _aliases, ips = socket.gethostbyname_ex(socket.gethostname())
        addresses.extend(ips)
    except OSError:
        pass
    return addresses


def local_prefixes(limit: int = 4) -> list[str]:
    """Return local private /24 prefixes, default route first.

    A VPN/virtual adapter can be the default route (e.g. 172.18.0.1), so keep
    more than one prefix; otherwise the real VMOS LAN (192.168.1.x) can be
    missed entirely.
    """
    prefixes: list[str] = []
    for address in local_ipv4_addresses():
        try:
            ip = ipaddress.IPv4Address(address)
        except ValueError:
            continue
        if not ip.is_private:
            continue
        prefix = ".".join(address.split(".")[:3])
        if prefix not in prefixes:
            prefixes.append(prefix)
    return prefixes[:limit]


def host_sort_key(host: str) -> tuple:
    try:
        return (0, tuple(int(part) for part in host.split(".")), "")
    except ValueError:
        return (1, (), str(host))


def scan_lan_hosts(
    *,
    port: int = CONTAINER_PORT,
    probe_timeout: float = 0.6,
    workers: int = 128,
    stop: StopToken | None = None,
    progress: ProgressCallback | None = None,
) -> list[VmosHost]:
    prefixes = local_prefixes()
    candidates = [f"{prefix}.{index}" for prefix in prefixes for index in range(1, 255)]
    if not candidates:
        return []

    open_hosts: list[str] = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=min(workers, len(candidates))) as pool:
        futures = {
            pool.submit(_tcp_open, host, port, probe_timeout): host for host in candidates
        }
        for done, future in enumerate(concurrent.futures.as_completed(futures), start=1):
            if stop is not None and stop.stopped:
                for pending in futures:
                    pending.cancel()
                break
            host = futures[future]
            try:
                if future.result():
                    open_hosts.append(host)
            except Exception:  # noqa: BLE001 - a probe failure is not fatal
                pass
            if progress and done % 16 == 0:
                progress(done, len(candidates))

    found: list[VmosHost] = []
    if open_hosts:
        with concurrent.futures.ThreadPoolExecutor(max_workers=min(16, len(open_hosts))) as pool:
            futures = {
                pool.submit(_probe, host, port, probe_timeout, stop): host for host in open_hosts
            }
            for future in concurrent.futures.as_completed(futures):
                if stop is not None and stop.stopped:
                    break
                try:
                    if future.result():
                        found.append(VmosHost(futures[future], port))
                except Exception:  # noqa: BLE001
                    pass

    found.sort(key=lambda item: host_sort_key(item.ip))
    return found


def _tcp_open(host: str, port: int, timeout: float) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def _probe(host: str, port: int, timeout: float, stop: StopToken | None) -> bool:
    api = ContainerApi(
        VmosHost(host, port),
        transport=HttpTransport(timeout=timeout, retries=0, stop=stop),
        timeout=timeout,
    )
    return api.probe(timeout=timeout)


# ---------------------------------------------------------------------------
# Hosts and instances
# ---------------------------------------------------------------------------


def discover_hosts(
    configured: Sequence[str] | None = None,
    *,
    port: int = CONTAINER_PORT,
    scan: bool = True,
    use_adb: bool = True,
    probe_timeout: float = 0.6,
    scan_workers: int = 128,
    stop: StopToken | None = None,
    progress: ProgressCallback | None = None,
) -> tuple[list[VmosHost], list[str]]:
    """Resolve candidate IPs into verified VMOS hosts."""
    candidates: list[str] = []
    failures: list[str] = []

    def add(ip: str) -> None:
        value = str(ip or "").strip()
        if not value or value in candidates:
            return
        try:
            parsed = ipaddress.IPv4Address(value)
        except ValueError:
            failures.append(f"忽略非法 IP：{value!r}")
            return
        if not parsed.is_private:
            failures.append(f"忽略非私网 IP：{value}")
            return
        candidates.append(value)

    for ip in configured or []:
        add(ip)

    if use_adb:
        for ip in hosts_from_adb():
            add(ip)

    found: list[VmosHost] = []
    if scan:
        found.extend(scan_lan_hosts(
            port=port,
            probe_timeout=probe_timeout,
            workers=scan_workers,
            stop=stop,
            progress=progress,
        ))

    # Explicit and adb-derived hosts still need a probe.
    pending = [ip for ip in candidates if not any(host.ip == ip for host in found)]
    if pending:
        with concurrent.futures.ThreadPoolExecutor(max_workers=min(16, len(pending))) as pool:
            futures = {
                pool.submit(_probe, ip, port, probe_timeout, stop): ip for ip in pending
            }
            for future in concurrent.futures.as_completed(futures):
                ip = futures[future]
                try:
                    if future.result():
                        found.append(VmosHost(ip, port))
                    else:
                        failures.append(f"{ip} 不是 VMOS 主机（18182 无响应）")
                except Exception as exc:  # noqa: BLE001
                    failures.append(f"{ip} 探测失败：{exc}")

    known = {host.ip for host in found}
    for ip in candidates:
        if ip not in known and not any(item.startswith(ip) for item in failures):
            failures.append(f"{ip} 不可达")

    found.sort(key=lambda item: host_sort_key(item.ip))
    return found, failures


def load_instances(
    hosts: Iterable[VmosHost],
    *,
    timeout: float = 10.0,
    workers: int = 16,
    stop: StopToken | None = None,
) -> DiscoveryResult:
    hosts = list(hosts)
    result = DiscoveryResult(hosts=list(hosts))
    if not hosts:
        return result

    with concurrent.futures.ThreadPoolExecutor(max_workers=min(workers, len(hosts))) as pool:
        futures = {
            pool.submit(_list_host, host, timeout, stop): host for host in hosts
        }
        for future in concurrent.futures.as_completed(futures):
            host = futures[future]
            try:
                items = future.result()
            except Exception as exc:  # noqa: BLE001
                result.failures.append(f"{host}：{exc}")
                continue
            result.instances.extend(items)

    result.instances.sort(key=lambda item: (host_sort_key(item.host.ip), item.name.casefold()))
    result.failures.sort()
    return result


def _list_host(host: VmosHost, timeout: float, stop: StopToken | None) -> list[VmosInstance]:
    api = ContainerApi(
        host,
        transport=HttpTransport(timeout=timeout, retries=0, stop=stop),
        timeout=timeout,
    )
    return api.list_instances(timeout=timeout)


def discover_instances(
    configured: Sequence[str] | None = None,
    *,
    port: int = CONTAINER_PORT,
    scan: bool = True,
    use_adb: bool = True,
    probe_timeout: float = 0.6,
    list_timeout: float = 10.0,
    scan_workers: int = 128,
    host_workers: int = 16,
    stop: StopToken | None = None,
    progress: ProgressCallback | None = None,
) -> DiscoveryResult:
    hosts, failures = discover_hosts(
        configured,
        port=port,
        scan=scan,
        use_adb=use_adb,
        probe_timeout=probe_timeout,
        scan_workers=scan_workers,
        stop=stop,
        progress=progress,
    )
    result = load_instances(hosts, timeout=list_timeout, workers=host_workers, stop=stop)
    result.failures = failures + result.failures
    return result


def select_instances(
    instances: Sequence[VmosInstance],
    terms: Sequence[str] | None = None,
) -> list[VmosInstance]:
    """Match by display name, db_id, or full key (case-insensitive, substring)."""
    if not terms:
        return list(instances)
    wanted = [str(term).strip().casefold() for term in terms if str(term).strip()]
    selected: list[VmosInstance] = []
    for instance in instances:
        fields = (
            instance.name.casefold(),
            instance.db_id.casefold(),
            instance.key.casefold(),
            f"{instance.name} [{instance.db_id}]".casefold(),
        )
        if any(term == field or term in field for term in wanted for field in fields):
            selected.append(instance)
    return selected
