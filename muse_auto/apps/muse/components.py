"""Reusable Muse UI components.

A component owns one widget group (a form, a permission sheet, the age gate) and
knows how to operate it. Flows compose components; they do not contain selectors
or coordinates.
"""

from __future__ import annotations

import datetime as dt
import logging
import random
import time
from typing import Iterable

from muse_auto.apps.muse import selectors as S
from muse_auto.apps.muse.app import MuseApp
from muse_auto.apps.muse.pages import Page, MusePages
from muse_auto.core.errors import FlowError, NodeNotFound, ResetRequired, UiError
from muse_auto.core.stop import StopToken
from muse_auto.services import identity
from muse_auto.ui.node import UiNode
from muse_auto.ui.parser import parse_dump
from muse_auto.ui.selector import Selector
from muse_auto.ui.session import UiSession

LOGGER = logging.getLogger("muse_auto.apps.muse.components")

# Words that mean "this is a different auth provider" and must not be clicked
# when we asked for the plain email flow.
_OTHER_PROVIDERS = ("google", "instagram", "facebook", "apple", "meta account")


class MuseComponents:
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

    # -- generic helpers ---------------------------------------------------

    def ensure_foreground(self, attempts: int = 5) -> None:
        """Make sure Muse is the top app, closing startup sheets if needed.

        Muse triggers a Google credential-manager sheet shortly after launch.
        It can appear *after* page detection, so every component checks again
        right before touching the form.
        """
        for _ in range(max(1, attempts)):
            top = self.session.top_activity().get("package_name", "")
            if top == self.app.package:
                return
            if top in MusePages.SYSTEM_SHEET_PACKAGES:
                self.dismiss_system_sheet()
            elif top in MusePages.PERMISSION_PACKAGES:
                self.dismiss_permission()
            else:
                self.stop.sleep(0.8)
        top = self.session.top_activity().get("package_name", "")
        raise FlowError(f"系统弹层未关闭，当前前台：{top or '未知'}")

    def _short_labels(self, labels: Iterable[str], max_length: int = 80) -> list[UiNode]:
        nodes: list[UiNode] = []
        for node in self.session.dump().nodes:
            if not node.visible or not node.labels:
                continue
            label = node.labels.strip()
            if len(label) > max_length:
                continue
            if any(value.casefold() in label.casefold() for value in labels):
                nodes.append(node)
        nodes.sort(key=lambda item: ((item.center or (0, 0))[1], (item.center or (0, 0))[0]))
        return nodes

    def click_text_in_order(
        self,
        labels: Iterable[str],
        *,
        deny: Iterable[str] = (),
        timeout: float = 0.0,
        settle: float | None = None,
    ) -> bool:
        """Click the first visible control matching the first label that exists."""
        denied = tuple(value.casefold() for value in deny)
        for label in labels:
            for node in self._short_labels((label,)):
                text = node.labels.casefold()
                if any(value in text for value in denied):
                    continue
                try:
                    self.session.click(node, settle=settle)
                    self.log.debug("点击文案 %r -> %s", label, node.labels)
                    return True
                except UiError:
                    continue
        return False

    def click_selector(self, selector: Selector, *, timeout: float = 2.0) -> bool:
        try:
            self.session.click(selector, timeout=timeout)
            return True
        except (NodeNotFound, UiError):
            return False

    # -- permission / popups ----------------------------------------------

    def dismiss_permission(self) -> bool:
        """Accept a system permission dialog (notably Muse notifications).

        Muse is expected to run with notifications allowed; the ALLOW button is
        preferred over DON'T ALLOW. Matching is exact so "ALLOW" never hits
        "DON'T ALLOW".
        """
        tree = self.session.dump(force=True)
        top = self.session.top_activity().get("package_name", "")
        labels = " ".join(tree.visible_texts(limit=80)).casefold()
        is_permission = top in MusePages.PERMISSION_PACKAGES or (
            "permission" in top.casefold() or "permissioncontroller" in top.casefold()
        )
        looks_like_notification = (
            "allow" in labels
            and "don't allow" in labels
            and "notification" in labels
        )
        if not is_permission and not looks_like_notification:
            return False

        trees = [tree]
        if is_permission:
            # The v2 accessibility dump can contain Muse's tree behind a
            # system dialog. Force uiautomator to see the permission buttons.
            try:
                trees.append(parse_dump(self.app.device.dump_uiautomator()))
            except Exception as exc:  # noqa: BLE001
                self.log.debug("权限弹窗 uiautomator dump 失败：%s", exc)

        for candidate in trees:
            for label in (
                "allow",
                "while using the app",
                "only this time",
                "ok",
                "允许",
                "使用时允许",
                "仅此一次",
                "确定",
            ):
                node = self._find_exact_label(candidate, label)
                if node is not None:
                    self.session.click(node)
                    self.log.info("已允许系统权限弹窗（%s）", top or "permission")
                    # On some images granting the permission leaves the launcher
                    # on top; bring Muse back before the flow continues.
                    self.stop.sleep(1.2)
                    current = self.session.top_activity().get("package_name", "")
                    if current not in (self.app.package, *MusePages.PERMISSION_PACKAGES):
                        self.log.info("权限弹窗关闭后前台为 %s，重新拉起 Muse", current or "未知")
                        try:
                            self.app.launch(force_stop=False)
                        except Exception as exc:  # noqa: BLE001
                            self.log.warning("重新拉起 Muse 失败：%s", exc)
                    return True

        # Some builds expose only a close/back action for non-grantable prompts.
        self.log.warning("权限弹窗没有找到 ALLOW 按钮，尝试返回")
        self.session.back(settle=0.8)
        return True

    def _find_exact_label(self, tree, label: str):
        wanted = label.casefold()
        for node in tree.nodes:
            if not node.visible or not node.enabled:
                continue
            if node.text.strip().casefold() == wanted or node.desc.strip().casefold() == wanted:
                return node
        return None

    def dismiss_soft_popup(self) -> bool:
        """Dismiss a non-destructive promotional popup on welcome/home."""
        for label in ("not now", "no thanks", "maybe later", "got it", "skip"):
            if self.click_text_in_order((label,), settle=0.8):
                self.log.info("已关闭弹窗：%s", label)
                return True
        return False

    def dismiss_permission_retry(self, attempts: int = 3, interval: float = 2.0) -> bool:
        """Give the post-registration permission dialog three chances to appear."""
        handled = False
        for attempt in range(1, max(1, attempts) + 1):
            try:
                if self.dismiss_permission():
                    handled = True
                    self.log.info("已处理系统权限弹窗（第 %s/%s 次）", attempt, attempts)
            except Exception as exc:  # noqa: BLE001
                self.log.warning("尝试处理权限弹窗 %s/%s 失败：%s", attempt, attempts, exc)
            self.stop.sleep(interval)
        if not handled:
            self.log.debug("未发现系统权限弹窗")
        return handled

    def dismiss_system_sheet(self) -> bool:
        """Close Google credential-manager / account-picker sheets."""
        for label in ("close sheet", "not now", "no thanks", "cancel", "dismiss"):
            if self.click_text_in_order((label,), settle=0.8):
                self.log.info("已关闭系统账号弹层：%s", label)
                return True
        # Fallback for a sheet whose close icon has no text.
        try:
            node = Selector(desc_contains=("close", "dismiss")).find(self.session.dump())
        except Exception:  # noqa: BLE001
            node = None
        if node is not None:
            self.session.click(node)
            return True
        self.session.back(settle=0.8)
        return True

    def acknowledge_error(self) -> bool:
        """Dismiss a generic app error dialog (best effort)."""
        for label in ("ok", "got it", "dismiss", "close"):
            if self.click_text_in_order((label,), settle=0.6):
                return True
        return False

    # -- sign-up -----------------------------------------------------------

    def advance_welcome(self) -> bool:
        self.ensure_foreground()
        # Prefer the explicit email entry; never fall through to Google/IG/FB.
        if self.click_text_in_order(
            ("continue with email", "sign up with email", "use email"),
            deny=_OTHER_PROVIDERS,
            settle=1.0,
        ):
            return True
        return self.click_text_in_order(
            ("get started", "create an account", "sign up", "continue", "next"),
            deny=_OTHER_PROVIDERS,
            settle=1.0,
        )

    def enter_email(self, email: str) -> None:
        self.ensure_foreground()
        field = self.session.find(S.EMAIL_FIELD, timeout=3.0) or self.session.find(S.ANY_EDIT, timeout=1.0)
        if field is None:
            raise FlowError("邮箱页没有找到输入框")
        self.session.fill(field, email, clear=True, settle=0.6)
        self.session.hide_keyboard()
        if not self.click_text_in_order(("continue", "next", "done"), settle=1.2):
            self.session.enter(settle=1.2)
        # Avoid submitting the same address twice while the OTP screen loads.
        for _ in range(8):
            self.stop.sleep(1.0)
            if self._page() is not Page.EMAIL:
                break
        self.log.info("已提交邮箱：%s", email)

    def enter_code(self, code: str) -> None:
        self.ensure_foreground()
        edits = [node for node in self.session.dump(force=True).nodes if node.editable and node.visible]
        if not edits:
            raise FlowError("验证码页没有找到输入框")

        # Muse can auto-submit on the last digit before input verification runs;
        # the field then disappears and fill() reports "text not found". Treat
        # that as success when the page has already left OTP.
        try:
            # A single (often visually hidden) input is the common implementation.
            if len(edits) == 1:
                self.session.fill(edits[0], code, clear=True, settle=0.5, verify=False)
            elif len(edits) >= 6:
                # Six real one-character boxes: type one digit per box.
                for node, digit in zip(edits[: len(code)], code):
                    self.session.fill(node, digit, clear=True, settle=0.2, verify=False)
            else:
                self.session.fill(edits[0], code, clear=True, settle=0.5, verify=False)
        except UiError as exc:
            # The app often auto-submits on the 6th digit before input
            # verification completes; the input node then disappears. Do not
            # fail immediately: the next poll below will see birthday/loading.
            self.log.warning("验证码输入后校验未通过，等待页面跳转：%s", exc)

        # Muse auto-submits once the sixth digit is entered. Do not press BACK
        # (it would leave the loading screen) and do not re-click Confirm on the
        # already-submitted code.
        for _ in range(8):
            self.stop.sleep(1.5)
            if self._page() is not Page.OTP:
                self.log.info("验证码已提交")
                return
            summary = self.session.summary(limit=300).casefold()
            if "invalid" in summary or "incorrect" in summary or "expired" in summary:
                raise FlowError(f"验证码被拒绝：{self.session.summary(limit=120)}")

        # Older builds may require an explicit Confirm; try once.
        if self.click_text_in_order(("verify", "confirm", "submit"), settle=1.5):
            self.stop.sleep(3.0)
            if self._page() is not Page.OTP:
                self.log.info("已提交邮箱验证码")
                return
        raise FlowError("验证码提交后页面仍停留在验证码页")

    def choose_new_account(self) -> None:
        """Meta found an existing account; create a fresh Muse account instead."""
        self.ensure_foreground()
        if self.click_text_in_order(
            ("create new account", "create a new account", "create account"),
            deny=("continue with",),
            settle=1.5,
        ):
            self.log.info("已选择 Create new account")
            return
        raise FlowError("账号选择页没有找到 Create new account")

    def enter_birthday(
        self,
        value: str,
        first_names: str = "",
        last_names: str = "",
    ) -> None:
        self.ensure_foreground()
        try:
            birth = dt.date.fromisoformat(value)
        except ValueError as exc:
            raise FlowError(f"生日格式应为 YYYY-MM-DD：{value}") from exc

        tree = self.session.dump(force=True)
        labels = " ".join(tree.visible_texts(limit=160)).casefold()
        if "last name" in labels and (
            "first name" in labels or "name" in labels
        ):
            return self._fill_name_birthday_form(
                tree, birth, first_names, last_names
            )
        edits = [node for node in tree.nodes if node.editable and node.visible]

        # Muse's current build uses a "Birthday, not set" button that opens three
        # wheel pickers (SeekBar Month/Day/Year). Handle that before text fields.
        birthday_button = Selector(desc_contains=("birthday",)).find(self.session.dump())
        if birthday_button is not None and birthday_button.clickable:
            self._set_birthday_wheels(birth)
            self.session.hide_keyboard()
            self.stop.sleep(1.0)
            # The primary button becomes enabled only after the wheel closes.
            for _ in range(2):
                primary = Selector(resource_id_contains=("primary_button",)).find(
                    self.session.dump(force=True)
                )
                if primary is not None:
                    self.session.click(primary, settle=2.0)
                else:
                    self.click_text_in_order(("confirm", "continue", "next", "done"), settle=2.0)
                self.stop.sleep(2.0)
                if self._page() is not Page.BIRTHDAY:
                    break
            self.log.info("已设置生日：%s", birth.isoformat())
            return

        if not edits:
            # Android's DatePicker usually offers a keyboard/text-input toggle
            # (pencil icon). Use it when present; do not guess wheel gestures.
            if self.click_text_in_order(
                ("switch to text input", "text input", "enter date", "type date", "keyboard"),
                settle=1.0,
            ):
                self.stop.sleep(0.8)
                edits = [
                    node for node in self.session.dump().nodes if node.editable and node.visible
                ]

        if len(edits) >= 3:
            self._fill_split_date(edits, birth)
            self.session.hide_keyboard()
            if not self.click_text_in_order(("continue", "next", "done", "confirm"), settle=1.2):
                self.session.enter(settle=1.2)
            self.log.info("已填写生日：%s", birth.isoformat())
            return

        if not edits:
            raise FlowError("生日页没有可用的日期控件（既不是滚轮也不是文本框）")

        field = self.session.find(S.BIRTHDAY_FIELD, timeout=1.0) or edits[0]
        # Muse shows a prefilled "March 17, 2000" field (screenshot-confirmed),
        # so try the long month format first, then the numeric format.
        for index, pattern in enumerate(("%B %d, %Y", "%m/%d/%Y")):
            self.session.fill(field, birth.strftime(pattern), clear=True, settle=0.6)
            self.session.hide_keyboard()
            if not self.click_text_in_order(("continue", "next", "done", "confirm"), settle=1.5):
                self.session.enter(settle=1.5)
            self.stop.sleep(2.0)
            if self._page() is not Page.BIRTHDAY:
                self.log.info("已填写生日：%s（%s）", birth.isoformat(), pattern)
                return
            if index == 0:
                self.log.warning("长月份格式未通过，尝试数字日期格式")

        raise FlowError("生日提交后页面仍停留在生日页（可能需要日历选择器）")

    def _fill_name_birthday_form(
        self,
        tree,
        birth: dt.date,
        first_names: str,
        last_names: str,
    ) -> None:
        """Fill the alternate Birthday page that also asks for a name."""
        first = self._pick_name(first_names, identity.FIRST_NAMES)
        last = self._pick_name(last_names, identity.LAST_NAMES)
        self.log.info("生日页需要姓名，自动填写：%s %s", first, last)

        filled = False
        for attempt in range(1, 4):
            edits = self._name_edits(tree)
            if len(edits) < 2:
                raise FlowError("生日页需要姓名，但没有找到 First/Last name 输入框")
            # Fill one field at a time and re-dump: opening the keyboard moves
            # the form, so stale coordinates can type the last name into the
            # first field.
            self.session.fill(edits[0], first, clear=True, settle=0.5)
            self.session.hide_keyboard()
            self.stop.sleep(0.5)
            tree = self.session.dump(force=True)
            edits = self._name_edits(tree)
            if len(edits) < 2:
                raise FlowError("填写 First name 后找不到 Last name 输入框")
            self.session.fill(edits[1], last, clear=True, settle=0.5)
            self.session.hide_keyboard()
            self.stop.sleep(0.5)
            tree = self.session.dump(force=True)
            values = [node.text.strip() for node in self._name_edits(tree)]
            if len(values) >= 2 and values[0] == first and values[1] == last:
                filled = True
                break
            self.log.warning(
                "姓名填写校验失败（第 %s/3 次）：%s", attempt, values[:2]
            )
        if not filled:
            raise FlowError("姓名输入框填写后校验失败")

        # The alternate form shows a prefilled birthday button. Re-select the
        # configured birthday; the prefilled value does not enable Confirm on
        # some builds even though it looks valid.
        birthday_button = Selector(desc_contains=("birthday",)).find(tree)
        if birthday_button is not None and birthday_button.clickable:
            self._set_birthday_wheels(birth)
            self.session.hide_keyboard()
            self.stop.sleep(1.0)

        # Some builds show a third editable birthday field. The current build
        # uses a Birthday button with a prefilled date, so only try this when
        # an actual third input exists.
        edits = self._name_edits(tree)
        if len(edits) >= 3:
            try:
                self.session.fill(
                    edits[2],
                    birth.strftime("%B %d, %Y"),
                    clear=True,
                    settle=0.5,
                )
                self.session.hide_keyboard()
            except UiError as exc:
                self.log.warning("生日输入框填写失败，保留页面预填值：%s", exc)
        self.stop.sleep(0.8)

        for attempt in range(1, 4):
            tree = self.session.dump(force=True)
            primary = Selector(resource_id_contains=("primary_button",)).find(tree)
            if primary is not None:
                self.log.info(
                    "姓名/生日页确认按钮 enabled=%s bounds=%s 当前姓名=%s",
                    primary.enabled,
                    primary.bounds,
                    [node.text for node in self._name_edits(tree)][:2],
                )
                # The Compose primary button can ignore a center tap on this
                # alternate form. Tap several horizontal points (left to right)
                # and give the loading transition enough time.
                left = primary.bounds.left
                width = primary.bounds.width
                y = primary.bounds.center[1]
                for fraction in (0.25, 0.5, 0.75):
                    x = left + max(60, int(width * fraction))
                    self.session.tap(x, y, settle=2.5)
                    self.stop.sleep(3.0)
                    if self._page() is not Page.BIRTHDAY:
                        self.log.info(
                            "已填写姓名和生日：%s %s / %s",
                            first,
                            last,
                            birth.isoformat(),
                        )
                        return
            else:
                self.click_text_in_order(("confirm", "continue", "next", "done"), settle=2.0)
                self.stop.sleep(3.0)
                if self._page() is not Page.BIRTHDAY:
                    self.log.info("已填写姓名和生日：%s %s / %s", first, last, birth.isoformat())
                    return
            if attempt < 3:
                self.log.warning("姓名/生日页确认未跳转，重试第 %s/3 次", attempt)

        raise FlowError("填写姓名和生日后仍停留在 Finish creating your account")

    @staticmethod
    def _name_edits(tree) -> list:
        edits = [node for node in tree.nodes if node.editable and node.visible]
        edits.sort(key=lambda item: (item.bounds.top, item.bounds.left))
        return edits

    @staticmethod
    def _pick_name(pool: str, fallback: Iterable[str]) -> str:
        names = [part.strip() for part in str(pool or "").split(",") if part.strip()]
        if names:
            return random.choice(names)
        return random.choice(tuple(fallback))

    def _set_birthday_wheels(self, birth: dt.date) -> None:
        """Set the three-wheel picker, using the button label as feedback.

        A 100 px vertical drag moves exactly one item on the tested build.
        After Done, the button exposes the selected date ("Birthday, June 15,
        1992"), so we can verify and correct instead of trusting open-loop
        gestures.
        """
        current = self._birthday_from_button() or dt.date.today()
        button = Selector(desc_contains=("birthday",)).find(self.session.dump())
        if button is None:
            raise FlowError("生日页没有找到 Birthday 按钮")
        self.session.click(button, settle=1.5)

        for attempt in range(3):
            wheels = self._wait_wheels(timeout=6.0)
            if not wheels:
                raise FlowError("日期滚轮没有出现")
            self._apply_birthday_delta(current, birth, wheels)
            self.stop.sleep(1.0)
            for _ in range(2):
                if not self._click_done():
                    raise FlowError("日期滚轮没有找到 Done")
                self.stop.sleep(1.5)
                if not self._wait_wheels(timeout=1.0):
                    break
            else:
                raise FlowError("点击 Done 后日期滚轮没有关闭")
            actual = self._birthday_from_button()
            if actual == birth:
                return
            if actual is None:
                raise FlowError("点击 Done 后生日未设置")
            self.log.info("生日轮盘实际为 %s，按差值再校正一次", actual.isoformat())
            current = actual
            button = Selector(desc_contains=("birthday",)).find(self.session.dump())
            if button is None:
                raise FlowError("校正生日时找不到 Birthday 按钮")
            self.session.click(button, settle=1.2)

        raise FlowError(f"日期滚轮校正 3 次仍未得到 {birth.isoformat()}")

    def _wait_wheels(self, timeout: float) -> dict[str, UiNode]:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            tree = self.session.dump(force=True)
            wheels = {}
            for key in ("month", "day", "year"):
                node = Selector(desc_contains=(key,)).find(tree)
                if node is not None:
                    wheels[key] = node
            if len(wheels) == 3:
                return wheels
            self.stop.sleep(0.4)
        return {}

    def _apply_birthday_delta(
        self,
        current: dt.date,
        target: dt.date,
        wheels: dict[str, UiNode],
    ) -> None:
        # direction=+1 -> next item (finger up), -1 -> previous item (finger down).
        year_steps = target.year - current.year
        if year_steps:
            self._spin(wheels["year"], abs(year_steps), direction=1 if year_steps > 0 else -1)

        month_steps = target.month - current.month
        if month_steps:
            self._spin(wheels["month"], abs(month_steps), direction=1 if month_steps > 0 else -1)

        day_steps = target.day - current.day
        if day_steps:
            self._spin(wheels["day"], abs(day_steps), direction=1 if day_steps > 0 else -1)

    def _spin(self, wheel: UiNode, steps: int, direction: int, interval: float = 0.16) -> None:
        if steps <= 0 or wheel.center is None:
            return
        x, y = wheel.center
        # direction=+1 -> next item (finger up); -1 -> previous item (finger down).
        for _ in range(steps):
            if direction > 0:
                self.session.device.swipe(x, y + 150, x, y + 50, 220)
            else:
                self.session.device.swipe(x, y + 50, x, y + 150, 220)
            self.stop.sleep(interval)

    def _click_done(self) -> bool:
        return self.click_text_in_order(("done", "ok", "confirm"), settle=1.0)

    def _birthday_from_button(self) -> dt.date | None:
        node = Selector(desc_contains=("birthday",)).find(self.session.dump())
        if node is None:
            return None
        text = (node.desc or node.text).strip()
        if "," not in text:
            return None
        value = text.split(",", 1)[1].strip()
        if not value or value.casefold() == "not set":
            return None
        for pattern in ("%B %d, %Y", "%b %d, %Y", "%m/%d/%Y"):
            try:
                return dt.datetime.strptime(value, pattern).date()
            except ValueError:
                continue
        return None

    def _fill_split_date(self, edits: list[UiNode], birth: dt.date) -> None:
        month, day, year = f"{birth.month:02d}", f"{birth.day:02d}", str(birth.year)
        for node in edits[:3]:
            hint = (node.text or node.desc or node.resource_id).casefold()
            if "year" in hint or "yyyy" in hint:
                value = year
            elif "month" in hint or "mm" in hint:
                value = month
            elif "day" in hint or "dd" in hint:
                value = day
            else:
                # Order used by Meta apps: MM / DD / YYYY.
                value = (month, day, year)[edits.index(node) % 3]
            self.session.fill(node, value, clear=True, settle=0.3)

    def skip_age_gate(self, provider: str) -> None:
        self.ensure_foreground()
        provider = (provider or "none").casefold()
        if provider == "none":
            raise FlowError("Muse 要求年龄验证，但 run.age_gate=none")
        selector = S.SOCIAL_INSTAGRAM if provider == "instagram" else S.SOCIAL_FACEBOOK
        start_page = self._page()
        if start_page in (Page.WELCOME, Page.ONBOARDING, Page.HOME):
            self.log.info("年龄验证页已自动进入 %s，无需点击 OAuth", start_page.value)
            return
        clicked = self.click_selector(selector, timeout=3.0)
        if not clicked:
            # The copy is sometimes a single combined link:
            # "Continue with your Instagram or Facebook profile/account".
            fallbacks = (
                S.SOCIAL_INSTAGRAM,
                S.SOCIAL_FACEBOOK,
                Selector(
                    label_contains=(
                        "instagram or facebook",
                        "continue with your instagram",
                        "continue with your facebook",
                    )
                ),
            )
            for fallback in fallbacks:
                if self.click_selector(fallback, timeout=1.0):
                    clicked = True
                    self.log.info("使用通用社媒入口完成年龄验证")
                    break
        if not clicked:
            # Give the page a few chances to settle before declaring failure.
            for _ in range(3):
                page_match = self._page()
                if page_match in (Page.WELCOME, Page.ONBOARDING, Page.HOME):
                    self.log.info(
                        "年龄验证页已自动进入 %s，跳过 OAuth", page_match.value
                    )
                    return
                self.stop.sleep(2.0)
            self._reset_for_next_round(
                f"年龄验证页没有找到 Continue with {provider.title()}"
            )

        self.log.info("已选择用 %s 完成年龄验证，等待 OAuth 返回……", provider)
        deadline = time.monotonic() + 60.0
        retried = False
        left_muse = False
        while time.monotonic() < deadline:
            self.stop.check()
            top = self.session.top_activity().get("package_name", "")
            if top and top != self.app.package:
                left_muse = True
            if left_muse and top == self.app.package:
                self.stop.sleep(2.0)
                self.log.info("已从 %s 返回 Muse", provider)
                return

            page_match = self._page()
            if page_match in (Page.WELCOME, Page.ONBOARDING, Page.HOME):
                self.log.info(
                    "点击 %s 后已进入下一页（%s），无需等待 OAuth",
                    provider,
                    page_match.value,
                )
                return
            if not left_muse and not retried and time.monotonic() > deadline - 45:
                # Some builds ignore the first tap while the OAuth button is
                # still rendering; retry once before giving up.
                retried = True
                self.log.info("年龄验证按钮可能未生效，重试一次")
                self.click_selector(selector, timeout=3.0)
            self.stop.sleep(2.0)

        if left_muse:
            self._reset_for_next_round(f"{provider} 授权未在 60 秒内返回 Muse")
        self._reset_for_next_round(f"点击 {provider} 后年龄验证页没有跳转")

    # -- fatal page reset ------------------------------------------------

    def _reset_for_next_round(self, reason: str) -> None:
        """Clear Muse data/storage and stop this instance for the next round."""
        self.log.warning("%s；清除 Muse 缓存/存储，下一轮重新开始", reason)
        try:
            ok = self.app.clear_data()
            if not ok:
                self.log.warning("pm clear 未返回 Success")
        except Exception as exc:  # noqa: BLE001
            self.log.warning("清除 Muse 数据失败：%s", exc)
        self.session.invalidate()
        raise ResetRequired(f"{reason}；已清除 Muse 缓存/存储，下一轮重新开始")

    # -- settings / invite -------------------------------------------------

    def open_settings(self) -> bool:
        top_package = self.session.top_activity().get("package_name", "")
        if MusePages.detect(self.session.dump(), top_package).page is Page.SETTINGS:
            return True
        if self.click_selector(S.SETTINGS_BUTTON, timeout=1.5):
            self.stop.sleep(1.2)
            if self._page() is Page.SETTINGS:
                return True
        # Common fallback: avatar/profile tab -> menu -> Settings.
        for label in ("open menu", "navigation menu", "menu", "more", "profile", "you"):
            if self.click_text_in_order((label,), settle=1.0):
                break
        if self.click_selector(S.SETTINGS_MENU, timeout=2.0):
            self.stop.sleep(1.2)
            return self._page() is Page.SETTINGS
        return False

    def redeem_invite(self, code: str) -> bool:
        self.ensure_foreground()
        code = (code or "").strip()
        if not code:
            return False

        # The chat home screen exposes an "Invite" button directly.
        if not self.click_selector(S.INVITE_ENTRY, timeout=2.0):
            if not self.open_settings():
                self.log.warning("没有进入设置页，跳过邀请码")
                return False
            if not self.click_selector(S.INVITE_ENTRY, timeout=3.0):
                # Some builds put invite redemption under "Refer a friend".
                if not self.click_text_in_order(("refer", "invite", "reward"), settle=1.0):
                    self.log.warning("设置页没有找到邀请码入口")
                    return False

        field = self.session.find(S.ANY_EDIT, timeout=2.0)
        if field is None:
            self.log.warning("邀请码页没有输入框")
            return False
        self.session.fill(field, code, clear=True, settle=0.5)
        self.session.hide_keyboard()
        if not self.click_selector(S.REDEEM_BUTTON, timeout=2.0):
            self.session.enter(settle=1.5)

        self.stop.sleep(2.0)
        summary = self.session.summary(limit=300).casefold()
        if any(word in summary for word in ("invalid", "expired", "not valid", "错误", "无效")):
            self.log.warning("邀请码兑换失败：%s", self.session.summary(limit=120))
            return False
        if any(word in summary for word in ("redeemed", "success", "applied", "tokens", "成功")):
            self.log.info("邀请码已兑换：%s", code)
            return True
        self.log.info("邀请码已提交，但未捕获到明确的成功文案")
        return False

    def _page(self) -> Page:
        # This is used while polling transitions (OTP -> birthday). A cached
        # dump would keep returning the old OTP page forever, so force a fresh
        # tree every time.
        return MusePages.detect(
            self.session.dump(force=True),
            self.session.top_activity().get("package_name", ""),
        ).page
