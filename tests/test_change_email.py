from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from muse_auto.services.account_store import AccountRow, MuseAccountStore
from muse_auto.services.email_pool import EmailPool
from muse_auto.services.yich8_mail import Yich8MailClient, api_with_username

SAMPLE = """mbox_id：1 主题：Your confirmation code 发件人：notification@email.meta.com
内容：<html>Enter the following confirmation code 186461</html>
"""
API_TEMPLATE = (
    "http://mail.example/api?imap_key=k&fun=imap_read&imap_ip=127.0.0.1"
    "&port=143&delete=0&username=old@example.com&password=Aa123456"
)


class EmailPoolTests(unittest.TestCase):
    def test_take_and_restore(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "emails.txt"
            path.write_text("a@example.com\nb@example.com\n", encoding="utf-8")
            pool = EmailPool(path)
            self.assertEqual(pool.take(), "a@example.com")
            self.assertEqual(pool.remaining(), 1)
            pool.restore("a@example.com")
            self.assertEqual(pool.take(), "a@example.com")
            self.assertEqual(pool.take(), "b@example.com")
            self.assertIsNone(pool.take())


class AccountStoreTests(unittest.TestCase):
    def test_append_rows(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "muse账号.xls"
            store = MuseAccountStore(path, api_template=API_TEMPLATE)
            store.append(
                "a@example.com",
                "2026-11-04 10:00:00",
                invite_code="INV1",
                own_invite_code="OWN1",
            )
            store.append("b@example.com", "2026-11-04 11:00:00", invite_code="INV2")
            rows = store.read_all()
            self.assertEqual(
                [(row.account, row.created_at) for row in rows],
                [
                    ("a@example.com", "2026-11-04 10:00:00"),
                    ("b@example.com", "2026-11-04 11:00:00"),
                ],
            )
            self.assertTrue(rows[0].account_api.startswith("a@example.com----http://"))
            self.assertIn("username=a@example.com&", rows[0].account_api)
            self.assertIn("username=b@example.com&", rows[1].account_api)
            self.assertEqual(rows[0].invite_code, "INV1")
            self.assertEqual(rows[1].invite_code, "INV2")
            self.assertEqual(rows[0].own_invite_code, "OWN1")

    def test_locked_workbook_uses_snapshot_and_journal(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "muse账号.xls"
            store = MuseAccountStore(path, api_template=API_TEMPLATE)
            store.append("a@example.com", "2026-11-04 10:00:00")
            real_replace = __import__("os").replace

            def fake_replace(source, destination):
                if Path(destination) == path:
                    raise PermissionError("locked by Excel")
                return real_replace(source, destination)

            with patch("muse_auto.services.account_store.os.replace", side_effect=fake_replace):
                returned = store.append("b@example.com", "2026-11-04 11:00:00")
            self.assertNotEqual(returned, path)
            self.assertTrue(store.pending_path.exists())
            self.assertEqual(
                [(row.account, row.created_at) for row in store.read_all()],
                [
                    ("a@example.com", "2026-11-04 10:00:00"),
                    ("b@example.com", "2026-11-04 11:00:00"),
                ],
            )
            self.assertIn("username=b@example.com", store.read_all()[1].account_api)
            # Once Excel releases the file, the next append merges and clears
            # the journal.
            store.append("c@example.com", "2026-11-04 12:00:00")
            self.assertFalse(store.pending_path.exists())
            self.assertEqual(len(store.read_all()), 3)

    def test_old_two_column_file_is_backfilled(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "muse账号.xls"
            import xlwt

            book = xlwt.Workbook()
            sheet = book.add_sheet("muse账号")
            sheet.write(0, 0, "账号")
            sheet.write(0, 1, "创建时间")
            sheet.write(1, 0, "old@example.com")
            sheet.write(1, 1, "2026-11-04 09:00:00")
            book.save(str(path))

            store = MuseAccountStore(path, api_template=API_TEMPLATE)
            store.flush()
            rows = store.read_all()
            self.assertEqual(len(rows), 1)
            self.assertTrue(rows[0].account_api.startswith("old@example.com----http://"))
            self.assertIn("username=old@example.com&", rows[0].account_api)


class Yich8Tests(unittest.TestCase):
    def test_api_with_username_keeps_raw_email(self):
        api = api_with_username(API_TEMPLATE, "new@example.com")
        self.assertIn("username=new@example.com&", api)
        self.assertNotIn("%40", api)

    def test_url_and_code(self):
        client = Yich8MailClient(
            "http://mail.example/api?imap_key=k&fun=imap_read&username=old@example.com&password=p"
        )
        url = client.url_for("new@example.com")
        self.assertIn("username=new%40example.com", url)
        client.fetch = lambda email: SAMPLE  # type: ignore[method-assign]
        self.assertEqual(client.max_mbox_id("new@example.com"), 1)
        message = client.latest_code("new@example.com", 0)
        self.assertIsNotNone(message)
        assert message is not None
        self.assertEqual(message.code, "186461")
        self.assertIsNone(client.latest_code("new@example.com", 1))


if __name__ == "__main__":
    unittest.main()
