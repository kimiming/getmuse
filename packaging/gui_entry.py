"""PyInstaller entry point for the GUI executable."""

from __future__ import annotations

from muse_auto.gui.__main__ import main

if __name__ == "__main__":
    raise SystemExit(main())
