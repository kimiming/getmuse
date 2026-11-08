from __future__ import annotations

import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from muse_auto.apps.muse.app import MuseApp
from muse_auto.apps.muse.components import MuseComponents
from muse_auto.apps.muse.flows.register import RegisterFlow
from muse_auto.config import load_settings
from muse_auto.core.logging import InstanceLogger
from muse_auto.core.stop import StopToken
from muse_auto.runner.context import FlowContext
from muse_auto.services.ledger import Ledger, STATUS_REGISTERED
from muse_auto.ui.parser import parse_dump
from muse_auto.ui.session import UiSession
from muse_auto.vmos.models import VmosHost, VmosInstance

FIXTURES = Path(__file__).parent / "fixtures"


class FakeDevice:
    def __init__(self, instance):
        self.instance = instance
        self.page = "welcome"
        self.email = ""
        self.code = ""
        self.date_parts: list[str] = []
        self.clicks: list[str] = []

    def _xml(self) -> str:
        return (FIXTURES / f"{self.page}.xml").read_text(encoding="utf-8")

    def dump(self, **_kwargs) -> str:
        return self._xml()

    def top_activity(self):
        if self.page == "permission":
            return {"package_name": "com.google.android.permissioncontroller", "class_name": "Permission"}
        return {"package_name": "com.facebook.aura", "class_name": "com.facebook.aura.MainActivity"}

    def display_info(self):
        return 1080, 2400

    def screenshot(self, path):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        Path(path).write_bytes(b"\x89PNG\r\n\x1a\nfake")
        return Path(path)

    def click(self, x: int, y: int):
        tree = parse_dump(self._xml())
        candidates = [node for node in tree.nodes if node.bounds and node.contains(x, y)]
        if not candidates:
            return
        node = min(candidates, key=lambda item: item.area)
        clickable = node.clickable_ancestor()
        label = (clickable.labels or node.labels).casefold()
        self.clicks.append(label)

        if self.page == "welcome" and "continue with email" in label:
            self.page = "email"
        elif self.page == "email" and "continue" in label:
            self.page = "otp"
        elif self.page == "otp" and ("verify" in label or "continue" in label):
            self.page = "birthday"
        elif self.page == "birthday" and "continue" in label:
            self.page = "home"

    def text(self, value: str):
        if self.page == "email":
            self.email = value
        elif self.page == "otp":
            self.code = value

    def key(self, key_code):
        return None

    def back(self):
        return None

    def enter(self):
        return None

    def select_all_and_delete(self):
        return None

    def clear_chars(self, count: int):
        return None

    def shell(self, cmd: str, timeout: float = 30.0):
        return ""

    def is_installed(self, package: str) -> bool:
        return package == "com.facebook.aura"

    def app_version(self, package: str) -> str:
        return "14.0.0"

    def start_app(self, package: str):
        return None

    def force_stop(self, package: str):
        return None

    def clear_data(self, package: str) -> bool:
        return True


class FakeMail:
    def __init__(self):
        self.bought = 0

    def balance(self):
        return 10.0

    def buy_mailbox(self, *, service=None, email_type_id=None):
        self.bought += 1
        from muse_auto.services.mail import Mailbox

        return Mailbox(email="new@example.com", order_id="order-1")

    def latest_code(self, order_id):
        return None

    def wait_for_code(self, order_id, *, timeout, interval, baseline=None):
        return "123456"


class RegisterFlowTests(unittest.TestCase):
    def test_full_flow_reaches_home(self):
        with tempfile.TemporaryDirectory() as temp:
            settings = load_settings(Path(__file__).parents[1] / "config" / "settings.json")
            settings = replace(
                settings,
                run=replace(
                    settings.run,
                    artifact_dir=temp,
                    invite_code="",
                    change_email=False,
                ),
            )
            instance = VmosInstance(host=VmosHost("192.168.1.18"), db_id="DB1", name="PH19L-003", state="running")
            device = FakeDevice(instance)
            stop = StopToken()
            session = UiSession(device, stop=stop, action_delay=0.0, dump_retries=1)
            app = MuseApp(device, launch_wait=0.1, stop=stop)
            logger = InstanceLogger(__import__("logging").getLogger("test"), instance.name)
            components = MuseComponents(session, app, stop=stop)
            ctx = FlowContext(
                instance=instance,
                device=device,
                session=session,
                app=app,
                components=components,
                settings=settings,
                stop=stop,
                logger=logger,
                artifacts=Path(temp),
            )
            ledger = Ledger(Path(temp) / "accounts.jsonl")
            flow = RegisterFlow(settings=settings, mail_client=FakeMail(), ledger=ledger)

            result = flow.run(ctx)

            self.assertTrue(result.ok, result.message)
            self.assertEqual(result.status, STATUS_REGISTERED)
            self.assertEqual(device.email, "new@example.com")
            self.assertEqual(device.code, "123456")
            self.assertEqual(device.page, "home")
            record = ledger.find("new@example.com")
            self.assertIsNotNone(record)
            assert record is not None
            self.assertEqual(record.status, STATUS_REGISTERED)


if __name__ == "__main__":
    unittest.main()
