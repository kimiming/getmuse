from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from muse_auto.services.outlook_mail import OutlookMailProvider


class OutlookMailTests(unittest.TestCase):
    def test_buy_and_graph_code(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "outlookMail.txt"
            path.write_text(
                "user@outlook.com----pw----client-id----refresh-token\n"
                "other@outlook.com----pw2----client-id----token2\n",
                encoding="utf-8",
            )
            provider = OutlookMailProvider(path)
            box = provider.buy_mailbox()
            self.assertEqual(box.email, "user@outlook.com")
            self.assertEqual(provider.remaining(), 1)
            self.assertNotIn("user@outlook.com", path.read_text(encoding="utf-8"))

            provider._access_token = lambda _account: "access"  # type: ignore[method-assign]
            provider._graph_messages = lambda _token: {  # type: ignore[method-assign]
                "value": [
                    {"subject": "Security notice", "bodyPreview": "no code"},
                    {"subject": "Use code 654321 to verify", "bodyPreview": ""},
                ]
            }
            message = provider.latest_code(box.order_id)
            self.assertIsNotNone(message)
            assert message is not None
            self.assertEqual(message.code, "654321")


if __name__ == "__main__":
    unittest.main()
