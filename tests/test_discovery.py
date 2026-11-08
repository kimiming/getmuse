from __future__ import annotations

import unittest

from muse_auto.vmos.discovery import host_sort_key, select_instances
from muse_auto.vmos.models import VmosHost, VmosInstance, normalize_state


def make(name: str, db_id: str = "DB1", host: str = "192.168.1.18"):
    return VmosInstance(host=VmosHost(host), db_id=db_id, name=name, state="running")


class ModelTests(unittest.TestCase):
    def test_normalize(self):
        self.assertEqual(normalize_state("Started"), "running")
        self.assertEqual(normalize_state("exited"), "offline")
        self.assertEqual(normalize_state(None), "unknown")

    def test_label_and_key(self):
        item = make("PH19L-003")
        self.assertIn("PH19L-003", item.label)
        self.assertEqual(item.key, "192.168.1.18:18182/DB1")


class SelectTests(unittest.TestCase):
    def setUp(self):
        self.items = [
            make("PH19L-001", "A1"),
            make("PH19L-002", "A2"),
            make("PH20L-001", "B1", "192.168.1.19"),
        ]

    def test_exact_name(self):
        self.assertEqual([item.name for item in select_instances(self.items, ["PH19L-002"])], ["PH19L-002"])

    def test_substring(self):
        self.assertEqual(len(select_instances(self.items, ["PH19"])), 2)

    def test_db_id(self):
        self.assertEqual(len(select_instances(self.items, ["B1"])), 1)

    def test_case_insensitive(self):
        self.assertEqual(len(select_instances(self.items, ["ph19l-001"])), 1)

    def test_no_terms_returns_all(self):
        self.assertEqual(len(select_instances(self.items, [])), 3)

    def test_sort_key(self):
        hosts = ["192.168.1.10", "192.168.1.2", "host"]
        self.assertEqual(sorted(hosts, key=host_sort_key), ["192.168.1.2", "192.168.1.10", "host"])


if __name__ == "__main__":
    unittest.main()
