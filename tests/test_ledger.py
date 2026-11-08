from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from muse_auto.services.ledger import AccountRecord, Ledger, STATUS_EMAIL, STATUS_REGISTERED


class LedgerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / "accounts.jsonl"
        self.ledger = Ledger(self.path)

    def tearDown(self):
        self.temp.cleanup()

    def test_append_and_read(self):
        self.ledger.upsert(AccountRecord(email="a@example.com", order_id="1"))
        records = self.ledger.all()
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].email, "a@example.com")
        self.assertEqual(records[0].status, "mailbox_bought")

    def test_upsert_updates_existing(self):
        self.ledger.upsert(AccountRecord(email="a@example.com", order_id="1"))
        self.ledger.upsert(AccountRecord(email="a@example.com", status=STATUS_EMAIL))
        records = self.ledger.all()
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].status, STATUS_EMAIL)
        self.assertEqual(records[0].order_id, "1")

    def test_update_and_counts(self):
        self.ledger.upsert(AccountRecord(email="a@example.com", order_id="1"))
        self.ledger.upsert(AccountRecord(email="b@example.com", order_id="2"))
        self.ledger.mark("a@example.com", STATUS_REGISTERED, note="ok")
        self.assertEqual(self.ledger.counts()[STATUS_REGISTERED], 1)
        self.assertEqual(self.ledger.find("a@example.com").note, "ok")

    def test_export_csv(self):
        self.ledger.upsert(AccountRecord(email="a@example.com", order_id="1"))
        target = Path(self.temp.name) / "out.csv"
        self.ledger.export_csv(target)
        text = target.read_text(encoding="utf-8-sig")
        self.assertIn("a@example.com", text)
        self.assertIn("order_id", text)

    def test_missing_update_raises(self):
        with self.assertRaises(KeyError):
            self.ledger.update("missing@example.com", status="x")


if __name__ == "__main__":
    unittest.main()
