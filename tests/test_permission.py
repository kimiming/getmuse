from __future__ import annotations

import unittest
from pathlib import Path
from types import SimpleNamespace

from muse_auto.apps.muse.components import MuseComponents
from muse_auto.core.stop import StopToken
from muse_auto.ui.parser import parse_dump

FIXTURES = Path(__file__).parent / "fixtures"


class FakeSession:
    def __init__(self, tree):
        self.tree = tree
        self.clicked: list[str] = []

    def dump(self, force: bool = False):
        return self.tree

    def top_activity(self):
        return {"package_name": "com.google.android.permissioncontroller", "class_name": "Permission"}

    def click(self, node, **_kwargs):
        self.clicked.append(node.labels)

    def back(self, **_kwargs):
        self.clicked.append("BACK")


class PermissionTests(unittest.TestCase):
    def test_allow_is_clicked_not_deny(self):
        tree = parse_dump((FIXTURES / "permission.xml").read_text(encoding="utf-8"))
        session = FakeSession(tree)
        components = MuseComponents(
            session,
            SimpleNamespace(package="com.facebook.aura"),
            stop=StopToken(),
        )
        self.assertTrue(components.dismiss_permission())
        self.assertEqual(len(session.clicked), 1)
        self.assertIn("Allow", session.clicked[0])
        self.assertNotIn("Don't", session.clicked[0])


if __name__ == "__main__":
    unittest.main()
