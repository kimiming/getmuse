"""VMOS Container API (host and instance lifecycle)."""

from __future__ import annotations

import logging
from typing import Any, Iterable

from muse_auto.core.errors import VmosApiError, VmosConnectionError, VmosError
from muse_auto.vmos.models import (
    CONTAINER_PORT,
    VmosHost,
    VmosInstance,
    instance_from_item,
)
from muse_auto.vmos.transport import HttpTransport

LOGGER = logging.getLogger("muse_auto.vmos.container")


class ContainerApi:
    """Thin, typed wrapper around ``container_api`` endpoints."""

    def __init__(
        self,
        host: VmosHost,
        *,
        transport: HttpTransport | None = None,
        timeout: float = 10.0,
    ) -> None:
        self.host = host
        self.transport = transport or HttpTransport(timeout=timeout)
        self.timeout = timeout

    def _url(self, path: str) -> str:
        return f"{self.host.base_url}/{path.lstrip('/')}"

    # -- host --------------------------------------------------------------

    def probe(self, timeout: float | None = None) -> bool:
        """Return True when this IP speaks the VMOS container protocol."""
        for path in ("v1/net_info", "v1/heartbeat"):
            try:
                data = self.transport.request(
                    self._url(path),
                    timeout=timeout or self.timeout,
                    retries=0,
                )
            except (VmosConnectionError, VmosApiError, VmosError):
                continue
            if isinstance(data, dict):
                reported = str(data.get("host_ip") or "").strip()
                return not reported or reported == self.host.ip
        return False

    def host_info(self) -> dict[str, Any]:
        data = self.transport.request(self._url("v1/get_hardware_cfg"), timeout=self.timeout)
        return data if isinstance(data, dict) else {}

    def heartbeat(self) -> dict[str, Any]:
        data = self.transport.request(self._url("v1/heartbeat"), timeout=self.timeout)
        return data if isinstance(data, dict) else {}

    # -- instances ---------------------------------------------------------

    def list_instances(self, timeout: float | None = None) -> list[VmosInstance]:
        last: BaseException | None = None
        for path in ("container_api/v1/list_names", "v1/list_names"):
            try:
                data = self.transport.request(
                    self._url(path),
                    timeout=timeout or self.timeout,
                    retries=0,
                )
                items = self._extract_items(data)
                if items is None:
                    last = VmosApiError("list_names 返回格式异常", url=self._url(path))
                    continue
                result: list[VmosInstance] = []
                for item in items:
                    instance = instance_from_item(self.host, item)
                    if instance is not None:
                        result.append(instance)
                return result
            except (VmosConnectionError, VmosApiError, VmosError) as exc:
                last = exc
                continue
        if isinstance(last, VmosError):
            raise last
        raise VmosConnectionError(f"{self.host} 无法读取实例列表", url=self._url("container_api/v1/list_names"))

    @staticmethod
    def _extract_items(data: Any) -> list[dict[str, Any]] | None:
        if isinstance(data, dict):
            value = data.get("list")
            if value is None:
                value = data.get("instances")
            data = value
        if not isinstance(data, list):
            return None
        return [item for item in data if isinstance(item, dict)]

    def start(self, db_ids: Iterable[str], timeout: float = 60.0) -> dict[str, Any]:
        ids = [str(item).strip() for item in db_ids if str(item).strip()]
        if not ids:
            return {}
        data = self.transport.request(
            self._url("container_api/v1/run"),
            method="POST",
            body={"db_ids": ids},
            timeout=timeout,
        )
        return data if isinstance(data, dict) else {"result": data}

    def stop(self, db_ids: Iterable[str], timeout: float = 60.0) -> dict[str, Any]:
        ids = [str(item).strip() for item in db_ids if str(item).strip()]
        if not ids:
            return {}
        data = self.transport.request(
            self._url("container_api/v1/stop"),
            method="POST",
            body={"db_ids": ids},
            timeout=timeout,
        )
        return data if isinstance(data, dict) else {"result": data}


def make_container(ip: str, port: int = CONTAINER_PORT, *, stop=None) -> ContainerApi:
    return ContainerApi(
        VmosHost(ip, port),
        transport=HttpTransport(timeout=10.0, retries=1, stop=stop),
    )
