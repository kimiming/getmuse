"""Meta Account email-change navigation for Muse.

Muse's Meta Account screen is a WebView. On the tested build a normal center tap
on a WebView row sometimes does nothing; tapping near the left edge of the row
is reliable. This module owns those UI quirks, while the flow owns email-pool and
XLS concerns.
"""

from __future__ import annotations

import logging
import re
import time

from muse_auto.apps.muse.app import MuseApp
from muse_auto.apps.muse.pages import MusePages
from muse_auto.core.errors import FlowError
from muse_auto.core.stop import StopToken
from muse_auto.services.yich8_mail import Yich8MailClient
from muse_auto.ui.node import UiNode
from muse_auto.ui.selector import Selector
from muse_auto.ui.session import UiSession

LOGGER = logging.getLogger("muse_auto.apps.muse.account_center")
EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")


class AccountCenter:
    def __init__(
        self,
        session: UiSession,
        app: MuseApp,
        *,
        stop: StopToken,
        logger: logging.Logger | None = None,
    ) -> None:
        self.session = session
        self.app = app
        self.stop = stop
        self.log = logger or LOGGER

    # ------------------------------------------------------------------
    # Public
    # ------------------------------------------------------------------

    def change_email(self, new_email: str, mail: Yich8MailClient, baseline: int) -> None:
        """Walk Settings → Meta Account and add ``new_email``."""
        self._open_drawer()
        self._open_settings()
        self._open_meta_account()
        self._open_default_contact_info()
        self._open_contact_points()
        self._open_contact_info()
        self._open_add_contact_menu()
        self._open_add_email_form()
        self._submit_email(new_email)
        self._submit_code(new_email, mail, baseline)

    def current_email(self) -> str:
        tree = self.session.dump(force=True)
        for node in tree.nodes:
            if not node.visible:
                continue
            match = EMAIL_RE.search(node.labels)
            if match:
                return match.group(0)
        return ""

    def read_current_email(self) -> str:
        """Navigate to Accounts Center and read the currently bound email."""
        self._open_drawer()
        self._open_settings()
        self._open_meta_account()
        deadline = time.monotonic() + 30.0
        while time.monotonic() < deadline:
            email = self.current_email()
            if email:
                return email
            self.stop.sleep(0.8)
        raise FlowError("Meta Account 页没有读到当前邮箱")

    # ------------------------------------------------------------------
    # Navigation
    # ------------------------------------------------------------------

    def _open_drawer(self) -> None:
        if self._has("settings"):
            return
        node = self._find("open side panel", clickable=False)
        if node is None:
            raise FlowError("首页没有找到左上角抽屉按钮")
        self._tap(node)
        self._wait("settings", timeout=10)

    def _open_settings(self) -> None:
        node = self._find("settings", clickable=False)
        if node is None:
            raise FlowError("抽屉里没有找到 Settings")
        self._tap(node)
        self._wait("connectors", "free plan", "settings", timeout=12)

    def _open_meta_account(self) -> None:
        if self._is_account_center():
            return
        self._scroll_until("meta account", attempts=8)
        node = self._find("meta account", clickable=True)
        if node is None:
            raise FlowError("设置页底部没有找到 Meta Account")
        self._tap(node)
        # Accounts Center is a WebView and can take a while to render. The
        # current build no longer shows an "Account settings" heading; it shows
        # the Meta Account menu with the bound email and "Login and security".
        self._wait(
            "account settings",
            "login and security",
            "default contact info",
            timeout=35,
        )

    def _is_account_center(self) -> bool:
        try:
            top = self.session.top_activity()
        except Exception:  # noqa: BLE001
            return False
        return "accountcenter" in str(top.get("class_name", "")).casefold()

    def _open_default_contact_info(self) -> None:
        node = self._find_email(clickable=True, timeout=12)
        if node is None:
            raise FlowError("Meta Account 页没有找到当前邮箱")
        self._tap_until(node, "default contact info", timeout=20)

    def _open_contact_points(self) -> None:
        node = self._find_email(clickable=True, timeout=10)
        if node is None:
            raise FlowError("Default contact info 页没有找到邮箱按钮")
        self._tap_until(node, "add or edit contact info", "contact points", timeout=20)

    def _open_contact_info(self) -> None:
        node = self._find("add or edit contact info", clickable=True)
        if node is None:
            raise FlowError("没有找到 Add or edit contact info")
        self._tap_until(node, "add new contact info", timeout=20)

    def _open_add_contact_menu(self) -> None:
        node = self._find("add new contact info", clickable=True)
        if node is None:
            raise FlowError("Contact info 页没有找到 Add new contact info")
        self._tap_until(node, "add email", "add mobile number", timeout=15)

    def _open_add_email_form(self) -> None:
        node = self._find("add email", clickable=True)
        if node is None:
            raise FlowError("没有找到 Add email")
        self._tap_until(node, "enter email", timeout=20)

    def _submit_email(self, email: str) -> None:
        field = self.session.find(Selector(editable=True), timeout=10)
        if field is None:
            raise FlowError("Add email 页没有输入框")
        self.session.fill(field, email, clear=True, settle=0.8)
        self.session.hide_keyboard()
        self._click_next()
        # The Accounts Center WebView can take tens of seconds to render the
        # confirmation page, especially right after adding a contact point.
        self._wait("confirmation code", "confirmation", timeout=45)

    def _submit_code(self, email: str, mail: Yich8MailClient, baseline: int) -> None:
        code = mail.wait_for_code(email, baseline=baseline, timeout=180, interval=4)
        field = self.session.find(Selector(editable=True), timeout=8)
        if field is None:
            raise FlowError("确认码页没有输入框")
        self.session.fill(field, code, clear=True, settle=0.8)
        self.session.hide_keyboard()
        self._click_next()
        # The page header itself says "Meta Account"; wait for the actual
        # "Email added" confirmation instead of matching the header early.
        deadline = time.monotonic() + 25.0
        while time.monotonic() < deadline:
            self.stop.check()
            if self._has("email added"):
                return
            if not self._has("confirmation code"):
                return
            self.stop.sleep(0.8)
        raise FlowError("提交确认码后仍停留在确认码页")

    def _click_next(self) -> None:
        node = self._find("next", clickable=True)
        if node is None:
            raise FlowError("页面没有找到 Next")
        self._tap(node)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _scroll_until(self, needle: str, attempts: int = 8) -> None:
        for _ in range(max(1, attempts)):
            if self._has(needle):
                return
            self.session.swipe(540, 2200, 540, 300, 500)
            self.stop.sleep(0.7)
        if not self._has(needle):
            raise FlowError(f"设置页滚动后仍未找到 {needle}")

    def _has(self, *needles: str) -> bool:
        tree = self.session.dump(force=True)
        text = " ".join(tree.visible_texts(limit=250)).casefold()
        return any(needle.casefold() in text for needle in needles)

    def _wait(self, *needles: str, timeout: float = 10.0) -> None:
        deadline = time.monotonic() + max(0.0, timeout)
        while True:
            self.stop.check()
            if self._has(*needles):
                return
            if time.monotonic() >= deadline:
                raise FlowError(f"等待页面文字超时：{needles}")
            self.stop.sleep(0.5)

    def _find(self, needle: str, *, clickable: bool | None = None) -> UiNode | None:
        wanted = needle.casefold()
        tree = self.session.dump(force=True)
        for node in tree.nodes:
            if not node.visible or not node.labels:
                continue
            if wanted not in node.labels.casefold():
                continue
            target = node.clickable_ancestor() if clickable else node
            if clickable is True and not target.clickable:
                continue
            if clickable is False and node.clickable:
                continue
            return target
        return None

    def _find_email(self, *, clickable: bool = True, timeout: float = 8.0) -> UiNode | None:
        deadline = time.monotonic() + timeout
        while True:
            tree = self.session.dump(force=True)
            for node in tree.nodes:
                if not node.visible:
                    continue
                if not EMAIL_RE.search(node.labels):
                    continue
                target = node.clickable_ancestor() if clickable else node
                if clickable and not target.clickable:
                    continue
                return target
            if time.monotonic() >= deadline:
                return None
            self.stop.sleep(0.5)

    def _tap(self, node: UiNode) -> None:
        """Tap near the left of a WebView row; works where center taps do not."""
        bounds = node.bounds
        if bounds is None:
            raise FlowError("控件没有坐标")
        x = bounds.left + min(140, max(30, bounds.width // 3))
        y = bounds.center[1]
        self.session.tap(x, y, settle=0.8)

    def _tap_until(self, node: UiNode, *needles: str, timeout: float = 20.0) -> None:
        """Tap a WebView row; fall back to a center tap if the page does not move."""
        bounds = node.bounds
        if bounds is None:
            raise FlowError("控件没有坐标")
        x_left = bounds.left + min(140, max(30, bounds.width // 3))
        x_center = bounds.center[0]
        y = bounds.center[1]
        last_error: Exception | None = None
        for attempt, x in enumerate((x_left, x_center), start=1):
            self.session.tap(x, y, settle=0.8)
            try:
                self._wait(*needles, timeout=timeout)
                return
            except FlowError as exc:
                last_error = exc
                if attempt < 2:
                    self.log.warning("点击后页面未跳转，改用中间位置重试：%s", exc)
        raise last_error or FlowError(f"点击后页面未跳转：{needles}")
