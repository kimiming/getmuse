from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from muse_auto.config import load_settings
from muse_auto.core.errors import ConfigError

ROOT = Path(__file__).resolve().parents[1]


class ConfigTests(unittest.TestCase):
    def test_load_real_config(self):
        settings = load_settings(ROOT / "config" / "settings.json")
        self.assertEqual(settings.app.package, "com.facebook.aura")
        self.assertEqual(settings.mail.service, "Meta Ai")
        self.assertTrue(settings.mail.api_key)
        self.assertEqual(settings.project_root, ROOT)
        self.assertEqual(settings.artifact_dir, ROOT / "artifacts")
        self.assertEqual(settings.run.rounds, 2)
        self.assertEqual(settings.run.round_interval, 10.0)

    def test_env_api_key_wins(self):
        with mock.patch.dict(os.environ, {"MUSE_MAIL_API_KEY": "from-env"}):
            settings = load_settings(ROOT / "config" / "settings.json")
        self.assertEqual(settings.mail.api_key, "from-env")
        self.assertNotEqual(settings.masked_api_key, "from-env")

    def test_unknown_key_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "config" / "settings.json"
            path.parent.mkdir()
            path.write_text('{"vmos": {"bogus": 1}}', encoding="utf-8")
            with self.assertRaises(ConfigError):
                load_settings(path)

    def test_underage_birthday_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "config" / "settings.json"
            path.parent.mkdir()
            path.write_text('{"run": {"birthday": "2020-01-01"}}', encoding="utf-8")
            with self.assertRaises(ConfigError):
                load_settings(path)

    def test_bad_port_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "config" / "settings.json"
            path.parent.mkdir()
            path.write_text('{"vmos": {"port": 70000}}', encoding="utf-8")
            with self.assertRaises(ConfigError):
                load_settings(path)


if __name__ == "__main__":
    unittest.main()
