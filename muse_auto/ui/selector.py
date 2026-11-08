"""Declarative UI selectors.

A selector is data, not code. Page definitions can be changed without touching
the automation engine, and a selector can be unit-tested against a saved dump.

All string comparisons are case-insensitive. ``label_contains`` checks both
``text`` and ``content-desc``; Android accessibility trees often put the visible
button label in one or the other depending on the toolkit.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from muse_auto.ui.node import UiNode
from muse_auto.ui.parser import UiTree


def _tuple(values: Iterable[str] | str | None) -> tuple[str, ...]:
    if values is None:
        return ()
    if isinstance(values, str):
        return (values,)
    return tuple(str(value) for value in values if str(value))


@dataclass(frozen=True)
class Selector:
    text: str | None = None
    text_contains: tuple[str, ...] = ()
    desc_contains: tuple[str, ...] = ()
    label_contains: tuple[str, ...] = ()
    resource_id: str | None = None
    resource_id_contains: tuple[str, ...] = ()
    class_name: str | None = None
    class_contains: tuple[str, ...] = ()
    clickable: bool | None = None
    enabled: bool | None = None
    focused: bool | None = None
    password: bool | None = None
    editable: bool | None = None
    scrollable: bool | None = None
    min_area: int | None = None
    max_area: int | None = None
    visible_only: bool = True

    def __post_init__(self) -> None:
        for name in ("text_contains", "desc_contains", "label_contains", "resource_id_contains", "class_contains"):
            object.__setattr__(self, name, _tuple(getattr(self, name)))
        if not any(
            (
                self.text,
                self.text_contains,
                self.desc_contains,
                self.label_contains,
                self.resource_id,
                self.resource_id_contains,
                self.class_name,
                self.class_contains,
                self.clickable is not None,
                self.enabled is not None,
                self.focused is not None,
                self.password is not None,
                self.editable is not None,
                self.scrollable is not None,
            )
        ):
            raise ValueError("Selector 至少需要一个匹配条件")

    # -- matching ----------------------------------------------------------

    def matches(self, node: UiNode) -> bool:
        if self.visible_only and not node.visible:
            return False
        if self.text is not None and node.text.casefold() != self.text.casefold():
            return False
        if self.text_contains and not any(
            value.casefold() in node.text.casefold() for value in self.text_contains
        ):
            return False
        if self.desc_contains and not any(
            value.casefold() in node.desc.casefold() for value in self.desc_contains
        ):
            return False
        if self.label_contains:
            label = node.labels.casefold()
            if not any(value.casefold() in label for value in self.label_contains):
                return False
        if self.resource_id is not None:
            rid = node.resource_id.casefold()
            wanted = self.resource_id.casefold()
            if not (rid == wanted or rid.endswith(f":id/{wanted}") or rid.endswith(f"/{wanted}")):
                return False
        if self.resource_id_contains and not any(
            value.casefold() in node.resource_id.casefold()
            for value in self.resource_id_contains
        ):
            return False
        if self.class_name is not None and node.class_name.casefold() != self.class_name.casefold():
            return False
        if self.class_contains and not any(
            value.casefold() in node.class_name.casefold() for value in self.class_contains
        ):
            return False
        if self.clickable is not None and node.clickable != self.clickable:
            return False
        if self.enabled is not None and node.enabled != self.enabled:
            return False
        if self.focused is not None and node.focused != self.focused:
            return False
        if self.password is not None and node.password != self.password:
            return False
        if self.editable is not None and node.editable != self.editable:
            return False
        if self.scrollable is not None and node.scrollable != self.scrollable:
            return False
        if self.min_area is not None and node.area < self.min_area:
            return False
        if self.max_area is not None and node.area > self.max_area:
            return False
        return True

    # -- lookup ------------------------------------------------------------

    def find_all(self, tree: UiTree) -> list[UiNode]:
        return tree.find_all(self)

    def find(self, tree: UiTree) -> UiNode | None:
        candidates = self.find_all(tree)
        if not candidates:
            return None
        exact = (self.text or "").casefold()

        def score(node: UiNode) -> tuple:
            is_exact = 0 if exact and node.text.casefold() == exact else 1
            is_clickable = 0 if node.clickable else 1
            center = node.center or (0, 0)
            return (is_exact, is_clickable, node.area, center[1], center[0])

        return min(candidates, key=score)

    def __repr__(self) -> str:
        parts: list[str] = []
        for name in (
            "text",
            "text_contains",
            "desc_contains",
            "label_contains",
            "resource_id",
            "resource_id_contains",
            "class_name",
            "class_contains",
            "clickable",
            "editable",
        ):
            value = getattr(self, name)
            if value not in (None, (), ""):
                parts.append(f"{name}={value!r}")
        return f"Selector({', '.join(parts)})"


# -- concise constructors ---------------------------------------------------


def text_is(value: str, **kwargs) -> Selector:
    return Selector(text=value, **kwargs)


def text_has(*values: str, **kwargs) -> Selector:
    return Selector(label_contains=values, **kwargs)


def id_has(*values: str, **kwargs) -> Selector:
    return Selector(resource_id_contains=values, **kwargs)


def edit_text(**kwargs) -> Selector:
    return Selector(editable=True, **kwargs)


def clickable_label(*values: str, **kwargs) -> Selector:
    return Selector(label_contains=values, clickable=True, **kwargs)
