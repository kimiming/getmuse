from __future__ import annotations

import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from muse_auto.config import load_settings
from muse_auto.vmos.models import VmosHost, VmosInstance

try:
    import tkinter as tk
except Exception:  # noqa: BLE001
    tk = None


@unittest.skipIf(tk is None, "tkinter not available")
class GuiTests(unittest.TestCase):
    def test_construct_and_render(self):
        try:
            root = tk.Tk()
        except Exception as exc:  # noqa: BLE001 - headless CI
            self.skipTest(f"no display: {exc}")
            return
        root.withdraw()
        from muse_auto.gui.app import MuseAutoApp

        settings = load_settings()
        with tempfile.TemporaryDirectory() as temp:
            settings = replace(settings, project_root=Path(temp))
            app = MuseAutoApp(root, settings, auto_discover=False, auto_balance=False)
            try:
                self.assertEqual(len(app.scripts()), 2)
                self.assertEqual(app.scripts_view.current.id, "muse.register")
                app.instances_view.set_instances(
                    [
                        VmosInstance(
                            host=VmosHost("192.168.1.104"),
                            db_id="DB1",
                            name="US13X-010",
                            state="running",
                        ),
                        VmosInstance(
                            host=VmosHost("192.168.1.104"),
                            db_id="DB2",
                            name="OFF-1",
                            state="offline",
                        ),
                    ]
                )
                root.update()
                self.assertEqual(len(app.instances_view.tree.get_children()), 2)

                app.instances_view.tree.selection_set(app.instances_view.tree.get_children()[0])
                root.update()
                self.assertIn("已选 1", app.selection_var.get())

                app.instances_view.state_var.set("offline")
                app.instances_view.refresh_display()
                root.update()
                self.assertEqual(len(app.instances_view.tree.get_children()), 1)
            finally:
                root.destroy()


if __name__ == "__main__":
    unittest.main()
