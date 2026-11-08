from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from muse_auto.services.registration_mail import CustomMailProvider


class CustomMailParseTests(unittest.TestCase):
    def test_extracts_subject_code(self):
        self.assertEqual(
            CustomMailProvider._extract("Use code 134016 to verify your identity"),
            "134016",
        )

    def test_extracts_json_code(self):
        self.assertEqual(
            CustomMailProvider._extract('{"data": {"code": "654321"}}'),
            "654321",
        )

    def test_buy_consumes_one_line(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "registerEmail.txt.txt"
            path.write_text(
                "a@example.com----https://example.test/a\n"
                "b@example.com----https://example.test/b\n",
                encoding="utf-8",
            )
            provider = CustomMailProvider(path)
            box = provider.buy_mailbox()
            self.assertEqual(box.email, "a@example.com")
            self.assertEqual(box.order_id, "https://example.test/a")
            self.assertEqual(provider.remaining(), 1)
            self.assertNotIn("a@example.com", path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
