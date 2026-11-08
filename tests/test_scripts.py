from __future__ import annotations

import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from muse_auto.config import load_settings
from muse_auto.core.stop import StopToken
from muse_auto.scripts import all_scripts, get_script


class ScriptRegistryTests(unittest.TestCase):
    def test_registry(self):
        scripts = all_scripts()
        self.assertGreaterEqual(len(scripts), 2)
        self.assertEqual(scripts[0].id, "muse.register")
        self.assertEqual(get_script("muse.register").app_name, "Muse")
        self.assertTrue(get_script("muse.register").billable)
        self.assertFalse(get_script("muse.smoke").billable)

    def test_muse_defaults_use_config(self):
        settings = load_settings()
        spec = get_script("muse.register")
        defaults = spec.defaults(settings)
        self.assertEqual(defaults["mail_service"], "Meta Ai")
        self.assertEqual(defaults["email_type_id"], 26)
        self.assertTrue(defaults["mail_api_key"])

    def test_prepare_register(self):
        settings = load_settings()
        with tempfile.TemporaryDirectory() as temp:
            settings = replace(settings, project_root=Path(temp))
            spec = get_script("muse.register")
            params = spec.defaults(settings)
            prepared = spec.prepare(settings, params, StopToken())
            self.assertTrue(prepared.billable)
            self.assertEqual(prepared.settings.mail.service, "Meta Ai")
            self.assertEqual(prepared.settings.mail.email_type_id, 26)
            self.assertTrue(hasattr(prepared.flow, "run"))

    def test_prepare_smoke(self):
        settings = load_settings()
        spec = get_script("muse.smoke")
        prepared = spec.prepare(settings, {}, StopToken())
        self.assertFalse(prepared.billable)
        self.assertTrue(hasattr(prepared.flow, "run"))


if __name__ == "__main__":
    unittest.main()
