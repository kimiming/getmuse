"""Step 3: redeem a Muse referral code from the Settings entry."""

from __future__ import annotations

import logging
import re
import time

from muse_auto.apps.muse.app import MuseApp
from muse_auto.core.errors import FlowError, UiError
from muse_auto.core.stop import StopToken
from muse_auto.ui.node import UiNode
from muse_auto.ui.selector import Selector
from muse_auto.ui.session import UiSession

LOGGER = logging.getLogger("muse_auto.apps.muse.invite_center")
OWN_CODE_RE = re.compile(r"^[A-Z0-9]{6}$")
_NOT_CODES = {
    "INVITE",
    "FRIEND",
    "FRIENDS",
    "REDEEM",
    "MESSAGES",
    "WHATSAPP",
    "SHARE",
    "COPY",
    "MUSE",
    "META",
}


class InviteCenter:
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

    def redeem(self, code: str) -> bool:
        code = str(code or "").strip()
        if not code:
            raise FlowError("邀请码为空")
        self._open_drawer()
        self._open_settings()
        self._scroll_until("redeem referral code", attempts=10)
        node = self._find("redeem referral code", clickable=True)
        if node is None:
            raise FlowError("设置页没有找到 Redeem referral code")
        self._tap(node)
        self._wait(
            "enter your invite code",
            "congratulations",
            "redemption was successful",
            timeout=20,
        )
        if self._has("congratulations", "redemption was successful"):
            self.log.info("该账号已经兑换过邀请码，跳过输入")
            return False

        field = self.session.find(Selector(editable=True), timeout=10)
        if field is None:
            raise FlowError("邀请码页没有输入框")
        # Do NOT verify the text after typing: the invite page validates the
        # 6-character code automatically and can clear/replace the field before
        # a UIAutomator read. Verification used to raise here even though the
        # code had already been accepted, causing the whole step to be retried.
        try:
            self.session.fill(field, code, clear=True, settle=0.8, verify=False)
        except UiError as exc:
            self.log.warning("邀请码输入控件读取失败，继续检查页面结果：%s", exc)
        self.session.hide_keyboard()
        self.stop.sleep(1.0)

        for _ in range(6):
            if self._has("congratulations", "redemption was successful", "code redeemed"):
                self.log.info("邀请码已兑换：%s", code)
                return True
            if self._has("isn't valid", "not valid", "invalid code", "incorrect code"):
                raise FlowError(f"邀请码无效：{code}")
            if not self._has("enter your invite code"):
                # The page already left the invite form. Treat it as success;
                # a failed submission normally keeps the form with an error.
                self.log.info("邀请码页面已跳转，按已兑换处理：%s", code)
                return True
            self.stop.sleep(0.5)

        # Some builds do not auto-submit; tap the enabled Redeem button.
        button = self.session.find(
            Selector(resource_id_contains=("primary_button",)), timeout=1
        )
        if button is not None and button.enabled:
            self._tap(button)
        else:
            self.log.warning("邀请码页 Redeem 按钮未启用，等待页面结果")
        self._wait(
            "congratulations",
            "redemption was successful",
            "code redeemed",
            timeout=30,
        )
        self.log.info("邀请码已兑换：%s", code)
        return True

    def read_own_code(self) -> str:
        """Open the home Invite dialog and read this account's own code."""
        node = self._find_invite_button()
        if node is None:
            raise FlowError("首页右上角没有找到 Invite 按钮")
        self._tap(node)

        deadline = time.monotonic() + 30.0
        seen = False
        while time.monotonic() < deadline:
            self.stop.check()
            tree = self.session.dump(force=True)
            text = " ".join(tree.visible_texts(limit=300)).casefold()
            if "invite friends" in text or "invite a friend" in text or "uses left" in text:
                if not seen:
                    seen = True
                    self.log.info("Invite 弹框已打开，等待读取本号邀请码……")
                code = self._extract_own_code(tree)
                if code:
                    self.log.info("本号邀请码：%s", code)
                    self.session.back(settle=0.8)
                    return code
            self.stop.sleep(0.6)
        raise FlowError("Invite 弹框已出现，但 30 秒内没有读到本号邀请码")

    def _find_invite_button(self) -> UiNode | None:
        width, height = self.session.display_size()
        tree = self.session.dump(force=True)
        labelled: list[UiNode] = []
        top_right: list[UiNode] = []
        words = ("invite", "gift", "reward", "present", "bonus")
        for node in tree.nodes:
            if not node.visible:
                continue
            bounds = node.bounds
            if bounds is None:
                continue
            # Top-right entry (new builds use a gift icon instead of "Invite").
            if bounds.top > height * 0.3 or bounds.left < width * 0.65:
                continue
            labels = node.labels.casefold()
            target = node.clickable_ancestor() if not node.clickable else node
            if any(word in labels for word in words) and target.clickable:
                labelled.append(target)
            if node.clickable and bounds.width < width * 0.35:
                top_right.append(node)

        # Prefer the labelled child's clickable icon parent. If the build has no
        # text/description at all (pure gift icon), use the rightmost top-right
        # button, not the adjacent phone-call button.
        candidates = labelled or top_right
        if not candidates:
            return None
        return max(candidates, key=lambda item: (item.bounds.right, -item.bounds.top))

    @staticmethod
    def _extract_own_code(tree) -> str:
        for node in tree.nodes:
            if not node.visible:
                continue
            for raw in (node.text, node.desc):
                text = str(raw or "").strip()
                if not text:
                    continue
                compact = re.sub(r"[^A-Za-z0-9]", "", text).upper()
                if (
                    len(compact) == 6
                    and compact not in _NOT_CODES
                ):
                    return compact
                match = re.search(r"\b[A-Z0-9]{6}\b", text.upper())
                if match:
                    candidate = match.group(0)
                    if candidate not in _NOT_CODES:
                        return candidate
        return ""

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

    def _scroll_until(self, needle: str, attempts: int = 10) -> None:
        for _ in range(max(1, attempts)):
            if self._has(needle):
                return
            self.session.swipe(540, 2200, 540, 300, 500)
            self.stop.sleep(0.7)
        if not self._has(needle):
            raise FlowError(f"设置页滚动后仍未找到 {needle}")

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _has(self, *needles: str) -> bool:
        tree = self.session.dump(force=True)
        text = " ".join(tree.visible_texts(limit=300)).casefold()
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

    def _tap(self, node: UiNode) -> None:
        bounds = node.bounds
        if bounds is None:
            raise FlowError("控件没有坐标")
        self.session.tap(
            bounds.left + min(140, max(30, bounds.width // 3)),
            bounds.center[1],
            settle=0.8,
        )

    def _tap_bottom_button(self) -> None:
        width, height = self.session.display_size()
        tree = self.session.dump(force=True)
        candidates = [
            node
            for node in tree.nodes
            if node.clickable
            and node.bounds is not None
            and node.bounds.width > width * 0.5
            and node.bounds.top > height * 0.8
        ]
        if not candidates:
            raise FlowError("邀请码页没有找到底部 Redeem 按钮")
        node = max(candidates, key=lambda item: item.bounds.bottom)
        self.session.tap(node.bounds.center[0], node.bounds.center[1], settle=0.8)
