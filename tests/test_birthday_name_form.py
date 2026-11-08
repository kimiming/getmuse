from __future__ import annotations

import unittest
from types import SimpleNamespace

from muse_auto.apps.muse.components import MuseComponents
from muse_auto.core.stop import StopToken
from muse_auto.services.identity import names_text, random_names


class NameSelectionTests(unittest.TestCase):
    def test_pick_name_from_pool(self):
        components = MuseComponents(
            SimpleNamespace(),
            SimpleNamespace(package="com.facebook.aura"),
            stop=StopToken(),
        )
        self.assertIn(components._pick_name("Alex, Parker", ()), {"Alex", "Parker"})
        self.assertTrue(components._pick_name("", ("Alex",)))

    def test_generate_20_names_each(self):
        first, last = names_text(20)
        self.assertEqual(len([x for x in first.split(",") if x.strip()]), 20)
        self.assertEqual(len([x for x in last.split(",") if x.strip()]), 20)
        first_list, last_list = random_names(20)
        self.assertEqual(len(first_list), 20)
        self.assertEqual(len(last_list), 20)


if __name__ == "__main__":
    unittest.main()
