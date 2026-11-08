from __future__ import annotations

import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

from muse_auto.apps.muse.pipeline import (
    DEFAULT_STEPS,
    MusePipelineFlow,
    normalize_steps,
    steps_label,
)
from muse_auto.config import load_settings
from muse_auto.core.stop import StopToken
from muse_auto.services.ledger import Ledger


class FakeLogger:
    def info(self, *args, **kwargs):
        pass

    def warning(self, *args, **kwargs):
        pass

    def error(self, *args, **kwargs):
        pass

    def exception(self, *args, **kwargs):
        pass


class FakeApp:
    def __init__(self):
        self.cleared = False

    def installed(self):
        return True

    def clear_data(self):
        self.cleared = True
        return True


class StepSelectionTests(unittest.TestCase):
    def test_default_is_123456(self):
        self.assertEqual(normalize_steps(None), DEFAULT_STEPS)
        self.assertEqual(normalize_steps(""), DEFAULT_STEPS)
        self.assertEqual(normalize_steps("1,2,3,4"), (1, 2, 3, 4))
        self.assertEqual(normalize_steps("1,2,3,4,5,6"), (1, 2, 3, 4, 5, 6))

    def test_subset_and_order(self):
        self.assertEqual(normalize_steps("4,2"), (2, 4))
        self.assertEqual(normalize_steps([3, 1, 3]), (1, 3))
        self.assertEqual(normalize_steps("1，3"), (1, 3))

    def test_invalid_values_are_dropped(self):
        self.assertEqual(normalize_steps("9,abc"), DEFAULT_STEPS)
        self.assertEqual(normalize_steps("1,2,3,4,5,6"), (1, 2, 3, 4, 5, 6))
        self.assertIn("4.获取本号邀请码", steps_label((1, 2, 3, 4, 5, 6)))

    def test_step6_only_clears(self):
        with tempfile.TemporaryDirectory() as temp:
            settings = load_settings()
            app = FakeApp()
            ctx = SimpleNamespace(
                logger=FakeLogger(),
                session=None,
                app=app,
                artifacts=Path(temp),
                stop=StopToken(),
            )
            flow = MusePipelineFlow(
                settings=settings,
                mail_client=None,
                ledger=Ledger(Path(temp) / "ledger.jsonl"),
                steps="6",
            )
            result = flow.run(ctx)
            self.assertTrue(result.ok)
            self.assertTrue(app.cleared)

    def test_step3_empty_pool_fails(self):
        with tempfile.TemporaryDirectory() as temp:
            settings = load_settings()
            settings = replace(
                settings,
                run=replace(
                    settings.run,
                    invite_pool_path=str(Path(temp) / "missing.txt"),
                ),
            )
            ctx = SimpleNamespace(
                logger=FakeLogger(),
                session=None,
                app=FakeApp(),
                artifacts=Path(temp),
                stop=StopToken(),
            )
            flow = MusePipelineFlow(
                settings=settings,
                mail_client=None,
                ledger=Ledger(Path(temp) / "ledger.jsonl"),
                steps="3",
            )
            result = flow.run(ctx)
            self.assertFalse(result.ok)
            self.assertIn("邀请码", result.message)


if __name__ == "__main__":
    unittest.main()
