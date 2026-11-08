from __future__ import annotations

import unittest
from pathlib import Path

from muse_auto.apps.muse.pages import MusePages, Page
from muse_auto.ui.parser import parse_dump
from muse_auto.ui.selector import Selector

FIXTURES = Path(__file__).parent / "fixtures"


def detect(name: str, top_package: str = "com.facebook.aura"):
    tree = parse_dump((FIXTURES / name).read_text(encoding="utf-8"))
    return MusePages.detect(tree, top_package)


class PageTests(unittest.TestCase):
    def test_welcome(self):
        self.assertIs(detect("welcome.xml").page, Page.WELCOME)

    def test_email(self):
        self.assertIs(detect("email.xml").page, Page.EMAIL)

    def test_otp_wins_over_email(self):
        self.assertIs(detect("otp.xml").page, Page.OTP)

    def test_real_otp_page(self):
        match = detect("otp_real.xml")
        self.assertIs(match.page, Page.OTP)
        self.assertEqual(match.edit_count, 1)

    def test_real_email_page(self):
        match = detect("email_real.xml")
        self.assertIs(match.page, Page.EMAIL)
        tree = parse_dump((FIXTURES / "email_real.xml").read_text(encoding="utf-8"))
        field = Selector(editable=True).find(tree)
        self.assertIsNotNone(field)
        assert field is not None
        self.assertIn("AuraTextInput", field.resource_id)

    def test_birthday(self):
        self.assertIs(detect("birthday.xml").page, Page.BIRTHDAY)

    def test_real_birthday_without_date(self):
        self.assertIs(detect("birthday_real2.xml").page, Page.BIRTHDAY)

    def test_onboarding_a_few_things_to_know(self):
        self.assertIs(detect("onboarding.xml").page, Page.ONBOARDING)

    def test_age_gate(self):
        self.assertIs(detect("age_gate.xml").page, Page.AGE_GATE)

    def test_home(self):
        self.assertIs(detect("home.xml").page, Page.HOME)

    def test_real_birthday_and_age_gate(self):
        self.assertIs(detect("birthday_real.xml").page, Page.BIRTHDAY)
        self.assertIs(detect("age_gate_real.xml").page, Page.AGE_GATE)

    def test_real_home_and_invite(self):
        from muse_auto.apps.muse import selectors as S
        from muse_auto.ui.parser import parse_dump

        tree = parse_dump((FIXTURES / "home_real.xml").read_text(encoding="utf-8"))
        self.assertIs(MusePages.detect(tree).page, Page.HOME)
        self.assertIsNotNone(S.INVITE_ENTRY.find(tree))

        age = parse_dump((FIXTURES / "age_gate_real.xml").read_text(encoding="utf-8"))
        self.assertIsNotNone(S.SOCIAL_INSTAGRAM.find(age))
        self.assertIsNotNone(S.SOCIAL_FACEBOOK.find(age))

    def test_permission_by_package(self):
        match = detect("permission.xml", "com.google.android.permissioncontroller")
        self.assertIs(match.page, Page.PERMISSION)

    def test_real_credential_sheet(self):
        match = detect("credential_sheet.xml", "com.android.credentialmanager")
        self.assertIs(match.page, Page.SYSTEM_SHEET)

    def test_network_error(self):
        match = detect("network_error.xml")
        self.assertIs(match.page, Page.ERROR)

    def test_account_chooser(self):
        match = detect("account_chooser.xml")
        self.assertIs(match.page, Page.ACCOUNT_CHOOSER)

    def test_unknown(self):
        match = detect("welcome.xml", "com.facebook.aura")
        self.assertIsNot(match.page, Page.UNKNOWN)

    def test_edit_count(self):
        match = detect("birthday.xml")
        self.assertEqual(match.edit_count, 3)

    def test_reason_is_populated(self):
        match = detect("email.xml")
        self.assertTrue(match.reason)
        self.assertTrue(match.known)


if __name__ == "__main__":
    unittest.main()
