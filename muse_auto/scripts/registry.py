"""Script registry.

Add a new app by creating a module with a `ScriptSpec` and appending it below.
The GUI discovers scripts from this list; no GUI changes are needed.
"""

from __future__ import annotations

from muse_auto.scripts.base import ScriptSpec
from muse_auto.scripts.muse import MUSE_REGISTER, MUSE_SMOKE

_SCRIPTS: tuple[ScriptSpec, ...] = (MUSE_REGISTER, MUSE_SMOKE)


def all_scripts() -> list[ScriptSpec]:
    return list(_SCRIPTS)


def default_script_id() -> str:
    return _SCRIPTS[0].id


def get_script(script_id: str) -> ScriptSpec:
    for spec in _SCRIPTS:
        if spec.id == script_id:
            return spec
    raise KeyError(f"未知脚本：{script_id}")


def script_names() -> dict[str, str]:
    return {spec.id: spec.name for spec in _SCRIPTS}
