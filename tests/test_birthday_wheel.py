from __future__ import annotations

import datetime as dt
import unittest

from muse_auto.apps.muse.app import MuseApp
from muse_auto.apps.muse.components import MuseComponents
from muse_auto.core.stop import StopToken
from muse_auto.ui.node import Rect, UiNode
from muse_auto.ui.session import UiSession


class SwipeDevice:
    def __init__(self):
        self.swipes: list[tuple[int, int, int, int]] = []

    def swipe(self, x1, y1, x2, y2, duration):
        self.swipes.append((x1, y1, y2, duration))


class BirthdayWheelTests(unittest.TestCase):
    def test_direction_and_counts(self):
        device = SwipeDevice()
        session = UiSession(device, stop=StopToken(), action_delay=0)
        components = MuseComponents(session, MuseApp(device, stop=StopToken()), stop=StopToken())
        wheels = {
            "month": UiNode(bounds=Rect(100, 100, 200, 200)),
            "day": UiNode(bounds=Rect(300, 100, 400, 200)),
            "year": UiNode(bounds=Rect(500, 100, 600, 200)),
        }
        components._apply_birthday_delta(
            dt.date(2026, 11, 4),
            dt.date(1992, 6, 15),
            wheels,
        )
        by_x = {}
        for x, y1, y2, _duration in device.swipes:
            by_x.setdefault(x, []).append((y1, y2))

        # Year 2026 -> 1992: 34 steps to previous years (finger down).
        self.assertEqual(len(by_x[550]), 34)
        self.assertTrue(all(y1 < y2 for y1, y2 in by_x[550]))
        # Month November -> June: 5 steps back (finger down).
        self.assertEqual(len(by_x[150]), 5)
        self.assertTrue(all(y1 < y2 for y1, y2 in by_x[150]))
        # Day 4 -> 15: 11 steps forward (finger up).
        self.assertEqual(len(by_x[350]), 11)
        self.assertTrue(all(y1 > y2 for y1, y2 in by_x[350]))


if __name__ == "__main__":
    unittest.main()
