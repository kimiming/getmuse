from __future__ import annotations

import unittest
from pathlib import Path
from types import SimpleNamespace

from muse_auto.apps.muse.components import MuseComponents
from muse_auto.apps.muse.pages import Page
from muse_auto.core.stop import StopToken
from muse_auto.ui.parser import parse_dump

FIXTURES = Path(__file__).parent / "fixtures"


class CachedSession:
    """Mimics UiSession: a non-forced dump returns stale cached XML."""

    def __init__(self) -> None:
        self.otp = parse_dump((FIXTURES / "otp_real.xml").read_text(encoding="utf-8"))
        self.birthday = parse_dump((FIXTURES / "birthday_real.xml").read_text(encoding="utf-8"))
        self.forced = 0

    def dump(self, force: bool = False):
        if force:
            self.forced += 1
            return self.birthday
        return self.otp

    def top_activity(self):
        return {"package_name": "com.facebook.aura", "class_name": "AuraMainActivity"}


class PagePollingTests(unittest.TestCase):
    def test_page_poll_forces_fresh_dump(self):
        session = CachedSession()
        components = MuseComponents(
            session,
            SimpleNamespace(package="com.facebook.aura"),
            stop=StopToken(),
        )
        self.assertIs(components._page(), Page.BIRTHDAY)
        self.assertEqual(session.forced, 1)


if __name__ == "__main__":
    unittest.main()
