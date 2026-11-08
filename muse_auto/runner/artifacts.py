"""Artifact directories for screenshots, dumps, and run metadata."""

from __future__ import annotations

import re
import time
from pathlib import Path


class ArtifactStore:
    def __init__(self, root: Path, label: str) -> None:
        self.root = Path(root)
        safe = re.sub(r"[^A-Za-z0-9_.-]+", "_", label).strip("_") or "instance"
        stamp = time.strftime("%Y%m%d-%H%M%S")
        self.directory = self.root / f"{stamp}_{safe}"
        self.directory.mkdir(parents=True, exist_ok=True)

    def path(self, name: str) -> Path:
        return self.directory / name

    def save_text(self, name: str, content: str) -> Path:
        target = self.path(name)
        target.write_text(content, encoding="utf-8")
        return target

    def save_bytes(self, name: str, content: bytes) -> Path:
        target = self.path(name)
        target.write_bytes(content)
        return target
