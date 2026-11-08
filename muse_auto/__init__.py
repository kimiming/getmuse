"""Muse (Meta) automation on VMOS Edge.

The package is intentionally layered:

    cli -> runner -> apps.muse -> ui -> vmos
                         |
                         +-> services (mail, ledger)

Only ``vmos`` knows about HTTP endpoints. Only ``ui`` knows about the
accessibility XML tree. Only ``apps.muse`` knows Muse page text and business
steps. This keeps each piece replaceable and testable in isolation.
"""

from __future__ import annotations

__version__ = "0.1.0"
__all__ = ["__version__"]
