from __future__ import annotations

import json
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from muse_auto.apps.muse.pages import MusePages, Page
from muse_auto.ui.parser import parse_dump
from muse_auto.ui.selector import Selector
from muse_auto.ui.session import UiSession
from muse_auto.core.stop import StopToken
from muse_auto.vmos.device import DeviceApi
from muse_auto.vmos.discovery import discover_instances
from muse_auto.vmos.models import VmosHost

FIXTURES = Path(__file__).parent / "fixtures"
PNG = b"\x89PNG\r\n\x1a\n" + b"fake-png"


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_args):
        return

    def _send(self, payload, code=200, content_type="application/json"):
        body = payload if isinstance(payload, bytes) else json.dumps(payload).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path = self.path.split("?")[0]
        if path == "/v1/net_info":
            self._send({"code": 200, "data": {"host_ip": "127.0.0.1"}})
        elif path == "/container_api/v1/list_names":
            self._send({"code": 200, "data": {"list": [
                {"db_id": "DB1", "user_name": "PH19L-003", "state": "running", "adb": 31050}
            ]}})
        elif path == "/android_api/v2/DB1/activity/top_activity":
            self._send({"code": 200, "data": {
                "package_name": "com.facebook.aura", "class_name": "com.facebook.aura.MainActivity"
            }})
        elif path == "/android_api/v2/DB1/display/info":
            self._send({"code": 200, "data": {"width": 1080, "height": 2400}})
        elif path == "/android_api/v2/DB1/package/list":
            self._send({"code": 200, "data": [
                {"package_name": "com.facebook.aura", "version_name": "14.0.0.4.149"}
            ]})
        elif path == "/android_api/v2/DB1/accessibility/dump":
            xml = (FIXTURES / "welcome.xml").read_text(encoding="utf-8")
            self._send({"code": 200, "data": xml})
        elif path == "/android_api/v2/DB1/screenshot/format":
            self._send(PNG, content_type="image/png")
        else:
            self._send({"code": 404, "msg": "not found"}, code=404)

    def do_POST(self):
        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length) if length else b"{}"
        path = self.path.split("?")[0]
        if path == "/android_api/v2/DB1/input/click":
            data = json.loads(body)
            self._send({"code": 200, "data": data})
        elif path == "/android_api/v2/DB1/activity/start":
            self._send({"code": 200, "data": True})
        else:
            self._send({"code": 404, "msg": "not found"}, code=404)


class VmosHttpTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        cls.port = cls.server.server_address[1]
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def test_discovery_and_device(self):
        result = discover_instances(
            ["127.0.0.1"],
            port=self.port,
            scan=False,
            use_adb=False,
            probe_timeout=2.0,
            list_timeout=2.0,
        )
        self.assertEqual(len(result.instances), 1)
        instance = result.instances[0]
        self.assertEqual(instance.name, "PH19L-003")
        self.assertTrue(instance.running)

        device = DeviceApi(instance, timeout=5.0)
        self.assertEqual(device.display_info(), (1080, 2400))
        self.assertEqual(device.top_activity()["package_name"], "com.facebook.aura")
        self.assertTrue(device.is_installed("com.facebook.aura"))
        self.assertEqual(device.app_version("com.facebook.aura"), "14.0.0.4.149")
        xml = device.dump()
        tree = parse_dump(xml)
        match = MusePages.detect(tree, "com.facebook.aura")
        self.assertIs(match.page, Page.WELCOME)

        with tempfile.TemporaryDirectory() as temp:
            path = device.screenshot(Path(temp) / "a.png")
            self.assertTrue(path.exists())
            self.assertTrue(path.read_bytes().startswith(b"\x89PNG"))

        session = UiSession(device, stop=StopToken(), action_delay=0)
        self.assertTrue(session.click(Selector(text="Get started")).clickable)


if __name__ == "__main__":
    unittest.main()
