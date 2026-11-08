"""PyInstaller entry point for the CLI executable."""

from __future__ import annotations

from muse_auto.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
