from __future__ import annotations

import unittest

from muse_auto.core.errors import MailError
from muse_auto.services.mail import MailClient, extract_code


class ExtractCodeTests(unittest.TestCase):
    def test_plain(self):
        self.assertEqual(extract_code("Your code is 482913"), "482913")

    def test_label(self):
        self.assertEqual(extract_code("Verification code: 902105"), "902105")

    def test_html_span(self):
        html = '<span class="code">42851348</span>'
        self.assertEqual(extract_code(html), "42851348")

    def test_html_with_noise(self):
        html = "<p>Use this code</p><div><b>  731 245 </b></div>"
        self.assertEqual(extract_code(html), "731245")

    def test_none(self):
        self.assertIsNone(extract_code("Welcome to Muse"))
        self.assertIsNone(extract_code(""))


class ResolveServiceTests(unittest.TestCase):
    def setUp(self):
        self.client = MailClient(base_url="https://example.invalid", api_key="k")
        self.client.services = lambda: [  # type: ignore[method-assign]
            {"serviceId": "302", "serviceName": "Meta Ai"},
            {"serviceId": "5", "serviceName": "Facebook"},
        ]

    def test_exact(self):
        self.assertEqual(self.client.resolve_service("Meta Ai"), "302")

    def test_case_insensitive(self):
        self.assertEqual(self.client.resolve_service("meta ai"), "302")

    def test_substring(self):
        self.assertEqual(self.client.resolve_service("Facebook"), "5")

    def test_numeric(self):
        self.assertEqual(self.client.resolve_service("302"), "302")

    def test_missing(self):
        with self.assertRaises(MailError):
            self.client.resolve_service("Muse App")

    def test_pending_code(self):
        def boom(*_args, **_kwargs):
            raise MailError("VMOS 业务错误 code=42001 msg=等待接取验证码中")

        self.client._get = boom  # type: ignore[method-assign]
        self.assertIsNone(self.client.latest_code("123"))

    def test_pending_401(self):
        def boom(*_args, **_kwargs):
            raise MailError("VMOS 业务错误 code=401 msg=Waiting to receive verification code")

        self.client._get = boom  # type: ignore[method-assign]
        self.assertIsNone(self.client.latest_code("123"))


class BuyMailboxTests(unittest.TestCase):
    def test_buy_parses_orders(self):
        client = MailClient(base_url="https://example.invalid", api_key="k")
        client.services = lambda: [{"serviceId": "302", "serviceName": "Meta Ai"}]  # type: ignore[method-assign]
        client._get = lambda *a, **k: {  # type: ignore[method-assign]
            "orders": [{"orderId": "999", "email": "a@example.com"}]
        }
        box = client.buy_mailbox(service="Meta Ai", email_type_id=26)
        self.assertEqual(box.email, "a@example.com")
        self.assertEqual(box.order_id, "999")

    def test_meta_ai_rejects_25_before_request(self):
        client = MailClient(base_url="https://example.invalid", api_key="k")
        client.services = lambda: [{"serviceId": "302", "serviceName": "Meta Ai"}]  # type: ignore[method-assign]
        with self.assertRaises(MailError) as ctx:
            client.buy_mailbox(service="Meta Ai", email_type_id=25)
        self.assertIn("26", str(ctx.exception))
        self.assertIn("41001", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
