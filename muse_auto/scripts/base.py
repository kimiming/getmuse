"""Script registry contracts.

An *instance* is a VMOS cloud phone. A *script* is a business automation that
can run on an instance. Scripts own their parameters; the runner owns execution
parameters (concurrency/limit). This separation lets new apps be added without
touching the instance table or the runner.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Mapping

from muse_auto.config import Settings
from muse_auto.core.stop import StopToken


@dataclass(frozen=True)
class ScriptField:
    key: str
    label: str
    kind: str = "text"  # text | password | int | choice | bool | date | steps
    default: Any = ""
    choices: tuple[str, ...] = ()
    group: str = "参数"
    help: str = ""
    secret: bool = False
    required: bool = False
    width: int = 30


@dataclass
class PreparedScript:
    """Everything needed to run one script group."""

    settings: Settings
    flow: Any
    app_package: str = ""
    billable: bool = False


@dataclass(frozen=True)
class ScriptSpec:
    id: str
    name: str
    description: str
    app_package: str
    fields: tuple[ScriptField, ...] = ()
    defaults: Callable[[Settings], Mapping[str, Any]] = lambda _settings: {}
    factory: Callable[[Settings, Mapping[str, Any], StopToken], PreparedScript] = field(
        default=None  # type: ignore[assignment]
    )
    billable: bool = False
    cost_hint: str = ""
    version: str = "1.0"

    def prepare(
        self,
        settings: Settings,
        params: Mapping[str, Any],
        stop: StopToken,
    ) -> PreparedScript:
        if self.factory is None:
            raise RuntimeError(f"脚本 {self.id} 没有 factory")
        return self.factory(settings, params, stop)

    @property
    def app_name(self) -> str:
        if self.app_package == "com.facebook.aura":
            return "Muse"
        return self.app_package or "-"
