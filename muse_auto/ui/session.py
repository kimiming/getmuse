"""High-level UI session.

The session hides the dump -> parse -> find -> click -> wait loop behind a few
intent-revealing methods. Business code says ``session.fill(EMAIL_FIELD, email)``
instead of manipulating XML and coordinates.
"""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Any

from muse_auto.core.errors import NodeNotFound, UiError
from muse_auto.core.retry import retry_call
from muse_auto.core.stop import StopToken
from muse_auto.ui.node import UiNode
from muse_auto.ui.parser import UiTree, parse_dump
from muse_auto.ui.selector import Selector
from muse_auto.vmos.device import DeviceApi

LOGGER = logging.getLogger("muse_auto.ui.session")

Target = Selector | UiNode


class UiSession:
    def __init__(
        self,
        device: DeviceApi,
        *,
        stop: StopToken,
        logger: logging.Logger | Any | None = None,
        action_delay: float = 0.6,
        dump_retries: int = 3,
        dump_timeout: float = 20.0,
    ) -> None:
        self.device = device
        self.stop = stop
        self.log = logger or LOGGER
        self.action_delay = max(0.0, action_delay)
        self.dump_retries = max(1, dump_retries)
        self.dump_timeout = dump_timeout
        self._tree: UiTree | None = None

    # -- tree --------------------------------------------------------------

    @property
    def tree(self) -> UiTree:
        return self.dump()

    def invalidate(self) -> None:
        self._tree = None

    def dump(self, force: bool = False) -> UiTree:
        if self._tree is not None and not force:
            return self._tree
        tree = retry_call(
            self._load_tree,
            attempts=self.dump_retries,
            delay=0.5,
            stop=self.stop,
            on_error=lambda attempt, exc: self.log.debug(
                "读取控件树失败（%s/%s）：%s", attempt, self.dump_retries, exc
            ),
        )
        self._tree = tree
        return self._tree

    def _load_tree(self) -> UiTree:
        raw = self.device.dump(timeout=self.dump_timeout)
        return parse_dump(raw)

    # -- lookup ------------------------------------------------------------

    def find(self, selector: Selector, timeout: float = 0.0, poll: float = 0.4) -> UiNode | None:
        deadline = time.monotonic() + max(0.0, timeout)
        while True:
            self.stop.check()
            tree = self.dump(force=True)
            node = selector.find(tree)
            if node is not None:
                return node
            if time.monotonic() >= deadline:
                return None
            self.stop.sleep(min(poll, max(0.0, deadline - time.monotonic())))

    def require(self, selector: Selector, timeout: float = 0.0, poll: float = 0.4) -> UiNode:
        node = self.find(selector, timeout=timeout, poll=poll)
        if node is None:
            raise NodeNotFound(selector, timeout)
        return node

    def wait_for(self, selector: Selector, timeout: float = 10.0, poll: float = 0.5) -> bool:
        return self.find(selector, timeout=timeout, poll=poll) is not None

    def wait_gone(self, selector: Selector, timeout: float = 10.0, poll: float = 0.5) -> bool:
        deadline = time.monotonic() + max(0.0, timeout)
        while True:
            self.stop.check()
            if self.find(selector) is None:
                return True
            if time.monotonic() >= deadline:
                return False
            self.stop.sleep(poll)

    def any_label(self, *labels: str) -> bool:
        """Cheap text presence check against the current dump."""
        tree = self.dump()
        haystack = " ".join(tree.visible_texts(limit=200)).casefold()
        return any(label.casefold() in haystack for label in labels if label)

    # -- actions -----------------------------------------------------------

    def _resolve(self, target: Target) -> UiNode:
        if isinstance(target, Selector):
            node = self.require(target)
        else:
            node = target
        return node

    def click(self, target: Target, *, timeout: float = 0.0, settle: float | None = None) -> UiNode:
        node = self._resolve(target) if not isinstance(target, Selector) else self.require(target, timeout)
        clickable = node.clickable_ancestor()
        center = clickable.center or node.center
        if center is None:
            raise UiError(f"控件没有可点击坐标：{node}")
        self.log.debug("点击 %s @ %s", node.label or node.resource_id or node.class_name, center)
        self.device.click(*center)
        self.stop.sleep(self.action_delay if settle is None else settle)
        self.invalidate()
        return clickable

    def tap(self, x: int, y: int, settle: float | None = None) -> None:
        self.device.click(int(x), int(y))
        self.stop.sleep(self.action_delay if settle is None else settle)
        self.invalidate()

    def type_text(self, value: str, settle: float | None = None) -> None:
        if value == "":
            return
        self.device.text(value)
        self.stop.sleep(self.action_delay if settle is None else settle)
        self.invalidate()

    def fill(
        self,
        target: Target,
        value: str,
        *,
        clear: bool = True,
        timeout: float = 10.0,
        settle: float | None = None,
        verify: bool = True,
    ) -> UiNode:
        node = self.find(target, timeout=timeout) if isinstance(target, Selector) else target
        if node is None:
            raise NodeNotFound(target, timeout)
        center = node.center
        if center is None:
            raise UiError(f"输入框没有坐标：{node}")
        self.device.click(*center)
        self.stop.sleep(max(0.35, self.action_delay * 0.7))
        if clear:
            # Ctrl+A does not select all on Compose fields; read the current
            # value and send exactly that many BACKSPACE events instead.
            current = self._focused_text(node)
            self.device.key(123)  # MOVE_END
            self.stop.sleep(0.15)
            if current:
                self.device.clear_chars(len(current))
                self.stop.sleep(0.2)
        if value:
            if verify:
                self.device.text(value)
            else:
                try:
                    self.device.text(value, verify=False)
                except TypeError:
                    # Older fake devices/tests may not accept the keyword.
                    self.device.text(value)
        self.stop.sleep(self.action_delay if settle is None else settle)
        self.invalidate()
        return node

    def _focused_text(self, fallback: UiNode) -> str:
        try:
            tree = self.dump(force=True)
        except UiError:
            return fallback.text
        focused = next(
            (item for item in tree.nodes if item.editable and item.focused),
            None,
        )
        if focused is None:
            focused = next((item for item in tree.nodes if item.editable), None)
        return focused.text if focused is not None else fallback.text

    def swipe(self, start_x: int, start_y: int, end_x: int, end_y: int, duration: int = 350) -> None:
        self.device.swipe(start_x, start_y, end_x, end_y, duration)
        self.stop.sleep(max(0.3, self.action_delay * 0.7))
        self.invalidate()

    def swipe_up(self, duration: int = 350) -> None:
        width, height = self.display_size()
        self.swipe(width // 2, int(height * 0.75), width // 2, int(height * 0.3), duration)

    def swipe_down(self, duration: int = 350) -> None:
        width, height = self.display_size()
        self.swipe(width // 2, int(height * 0.3), width // 2, int(height * 0.75), duration)

    def back(self, settle: float | None = None) -> None:
        self.device.back()
        self.stop.sleep(self.action_delay if settle is None else settle)
        self.invalidate()

    def enter(self, settle: float | None = None) -> None:
        self.device.enter()
        self.stop.sleep(self.action_delay if settle is None else settle)
        self.invalidate()

    def hide_keyboard(self) -> None:
        """Press BACK only when the IME is actually visible."""
        try:
            state = self.device.shell(
                "dumpsys input_method | grep -E 'mInputShown|mIsInputViewShown'",
                timeout=10,
            )
        except Exception:  # noqa: BLE001 - best effort
            return
        if "mInputShown=true" in state:
            self.device.back()
            self.stop.sleep(0.4)
            self.invalidate()

    # -- screen ------------------------------------------------------------

    def display_size(self) -> tuple[int, int]:
        cached = getattr(self, "_display", None)
        if cached is None:
            cached = self.device.display_info()
            self._display = cached
        return cached

    def top_activity(self) -> dict[str, str]:
        try:
            return self.device.top_activity()
        except Exception:  # noqa: BLE001 - diagnostics only
            return {"package_name": "", "class_name": ""}

    def screenshot(self, path: Path) -> Path:
        return self.device.screenshot(path)

    def summary(self, limit: int = 180) -> str:
        try:
            return self.dump().summary(limit=limit)
        except UiError:
            return ""

    def save_artifacts(self, directory: Path, tag: str = "fail") -> dict[str, str]:
        """Save XML + PNG + metadata; never raises because it runs on failure."""
        directory.mkdir(parents=True, exist_ok=True)
        saved: dict[str, str] = {}
        try:
            tree = self.dump()
            xml_path = directory / f"{tag}.xml"
            xml_path.write_text(tree.xml, encoding="utf-8")
            saved["xml"] = str(xml_path)
        except Exception as exc:  # noqa: BLE001
            self.log.warning("保存控件树失败：%s", exc)

        try:
            shot = self.screenshot(directory / f"{tag}.png")
            saved["screenshot"] = str(shot)
        except Exception as exc:  # noqa: BLE001
            self.log.warning("保存截图失败：%s", exc)

        try:
            activity = self.top_activity()
            width, height = self.display_size()
            meta = {
                "instance": self.device.instance.label,
                "db_id": self.device.instance.db_id,
                "activity": activity,
                "display": {"width": width, "height": height},
                "page_summary": self.summary(limit=500),
                "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
            }
            meta_path = directory / f"{tag}.json"
            meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
            saved["meta"] = str(meta_path)
        except Exception as exc:  # noqa: BLE001
            self.log.warning("保存元数据失败：%s", exc)
        return saved
