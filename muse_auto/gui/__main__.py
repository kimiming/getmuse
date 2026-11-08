from __future__ import annotations

import sys
import time

from muse_auto.config import load_settings
from muse_auto.core.errors import ConfigError
from muse_auto.core.logging import setup_logging


def main() -> int:
    try:
        settings = load_settings()
    except ConfigError as exc:
        print(f"配置错误：{exc}", file=sys.stderr)
        try:
            from tkinter import messagebox

            messagebox.showerror("Muse Auto 配置错误", str(exc))
        except Exception:  # noqa: BLE001
            pass
        return 2
    setup_logging(
        settings.log_level,
        settings.project_root / "logs" / f"gui_{time.strftime('%Y%m%d_%H%M%S')}.log",
    )
    try:
        from muse_auto.gui.app import run_gui
    except Exception as exc:  # noqa: BLE001
        print(f"无法加载 GUI：{exc}", file=sys.stderr)
        return 1
    return run_gui(settings)


if __name__ == "__main__":
    raise SystemExit(main())
