"""Persist GUI-only state: instance→script assignment and script parameters.

Kept out of ``config/settings.json`` so instance bindings and per-script forms
can evolve independently. File: ``data/gui_state.json``.
"""

from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from typing import Any, Mapping


class GuiStore:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._data: dict[str, Any] = {"assignments": {}, "script_params": {}}
        self._load()

    def _load(self) -> None:
        if not self.path.exists():
            return
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return
        if not isinstance(data, dict):
            return
        assignments = data.get("assignments")
        if isinstance(assignments, dict):
            self._data["assignments"] = {
                str(key): str(value) for key, value in assignments.items()
            }
        params = data.get("script_params")
        if isinstance(params, dict):
            self._data["script_params"] = {
                str(key): dict(value) for key, value in params.items() if isinstance(value, dict)
            }

    def _save(self) -> None:
        temp = self.path.with_suffix(self.path.suffix + ".tmp")
        with temp.open("w", encoding="utf-8") as handle:
            json.dump(self._data, handle, ensure_ascii=False, indent=2)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp, self.path)

    # -- assignments -------------------------------------------------------

    def assignment(self, instance_key: str, default: str) -> str:
        with self._lock:
            value = self._data["assignments"].get(str(instance_key), "")
            return str(value) or default

    def set_assignments(self, keys: list[str], script_id: str) -> None:
        with self._lock:
            for key in keys:
                self._data["assignments"][str(key)] = str(script_id)
            self._save()

    def assignments(self) -> dict[str, str]:
        with self._lock:
            return dict(self._data["assignments"])

    # -- script parameters -------------------------------------------------

    def params(self, script_id: str, defaults: Mapping[str, Any]) -> dict[str, Any]:
        with self._lock:
            saved = self._data["script_params"].get(str(script_id), {})
            merged = dict(defaults)
            if isinstance(saved, dict):
                merged.update(saved)
            return merged

    def set_params(self, script_id: str, values: Mapping[str, Any]) -> None:
        with self._lock:
            self._data["script_params"][str(script_id)] = dict(values)
            self._save()

    def all_params(self) -> dict[str, dict[str, Any]]:
        with self._lock:
            return {key: dict(value) for key, value in self._data["script_params"].items()}
