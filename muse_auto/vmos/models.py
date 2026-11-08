"""Value objects for VMOS hosts and instances.

The display name is not an API identifier. All device calls use ``db_id``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

CONTAINER_PORT = 18182


def normalize_state(value: object) -> str:
    state = str(value or "").strip().lower()
    if state in {"running", "started", "online"}:
        return "running"
    if state in {"starting", "launching", "creating", "initializing", "pending", "booting"}:
        return "starting"
    if state in {"failed", "error"}:
        return "failed"
    if state in {"stopped", "exited", "offline", "shutdown"}:
        return "offline"
    return state or "unknown"


@dataclass(frozen=True)
class VmosHost:
    ip: str
    port: int = CONTAINER_PORT

    def __post_init__(self) -> None:
        object.__setattr__(self, "ip", str(self.ip).strip())
        object.__setattr__(self, "port", int(self.port))

    @property
    def base_url(self) -> str:
        return f"http://{self.ip}:{self.port}"

    def __str__(self) -> str:
        return f"{self.ip}:{self.port}"


@dataclass(frozen=True)
class VmosInstance:
    host: VmosHost
    db_id: str
    name: str
    state: str = "unknown"
    adb_port: str = ""
    raw: Mapping[str, Any] = field(default_factory=dict, compare=False, repr=False)

    @property
    def running(self) -> bool:
        return self.state == "running"

    @property
    def key(self) -> str:
        return f"{self.host.ip}:{self.host.port}/{self.db_id}"

    @property
    def label(self) -> str:
        return f"{self.name} [{self.db_id}] {self.host.ip}"

    def __str__(self) -> str:
        return self.label


def instance_from_item(host: VmosHost, item: Mapping[str, Any]) -> VmosInstance | None:
    db_id = str(item.get("db_id") or item.get("dbId") or item.get("id") or "").strip()
    if not db_id:
        return None
    name = str(
        item.get("user_name")
        or item.get("name")
        or item.get("instance_name")
        or db_id
    ).strip()
    state = normalize_state(item.get("state") or item.get("status"))
    adb_port = str(item.get("adb") or item.get("adb_port") or "").strip()
    return VmosInstance(
        host=host,
        db_id=db_id,
        name=name,
        state=state,
        adb_port=adb_port,
        raw=dict(item),
    )
