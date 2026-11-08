"""Flow result type shared by smoke and registration."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class FlowResult:
    ok: bool
    status: str
    message: str = ""
    page: str = ""
    email: str = ""
    order_id: str = ""
    artifacts: dict[str, str] = field(default_factory=dict)
    data: dict[str, Any] = field(default_factory=dict)

    @property
    def short(self) -> str:
        if self.ok:
            return self.status
        return f"{self.status}: {self.message}" if self.message else self.status
