"""Accessibility node model.

A dump is a tree of ``<node>`` elements. This module turns each element into a
small immutable-ish object and provides bounds/ancestor helpers so selectors and
page detectors never touch ElementTree directly.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Iterable, Iterator

_BOUNDS_RE = re.compile(r"\[(-?\d+),(-?\d+)\]\[(-?\d+),(-?\d+)\]")


def parse_bool(value: object, default: bool = False) -> bool:
    text = str(value or "").strip().lower()
    if text in {"true", "1", "yes"}:
        return True
    if text in {"false", "0", "no"}:
        return False
    return default


@dataclass(frozen=True)
class Rect:
    left: int
    top: int
    right: int
    bottom: int

    @classmethod
    def from_bounds(cls, value: str | None) -> "Rect | None":
        match = _BOUNDS_RE.search(value or "")
        if not match:
            return None
        left, top, right, bottom = (int(part) for part in match.groups())
        if right <= left or bottom <= top:
            return None
        return cls(left, top, right, bottom)

    @property
    def width(self) -> int:
        return self.right - self.left

    @property
    def height(self) -> int:
        return self.bottom - self.top

    @property
    def area(self) -> int:
        return self.width * self.height

    @property
    def center(self) -> tuple[int, int]:
        return (self.left + self.right) // 2, (self.top + self.bottom) // 2

    def __str__(self) -> str:
        return f"[{self.left},{self.top}][{self.right},{self.bottom}]"


@dataclass
class UiNode:
    index: int = 0
    text: str = ""
    desc: str = ""
    resource_id: str = ""
    class_name: str = ""
    package: str = ""
    clickable: bool = False
    enabled: bool = True
    focused: bool = False
    password: bool = False
    checkable: bool = False
    checked: bool = False
    scrollable: bool = False
    selected: bool = False
    bounds: Rect | None = None
    children: list["UiNode"] = field(default_factory=list)
    parent: "UiNode | None" = field(default=None, repr=False, compare=False)
    attributes: dict[str, str] = field(default_factory=dict, repr=False, compare=False)

    # -- text --------------------------------------------------------------

    @property
    def label(self) -> str:
        return self.text or self.desc

    @property
    def labels(self) -> str:
        return " ".join(part for part in (self.text, self.desc) if part)

    @property
    def editable(self) -> bool:
        return self.class_name.endswith("EditText") or "EditText" in self.class_name

    @property
    def visible(self) -> bool:
        return self.bounds is not None

    @property
    def center(self) -> tuple[int, int] | None:
        return self.bounds.center if self.bounds else None

    @property
    def area(self) -> int:
        return self.bounds.area if self.bounds else 0

    def ancestors(self, limit: int = 12) -> Iterator["UiNode"]:
        node = self.parent
        count = 0
        while node is not None and count < limit:
            yield node
            node = node.parent
            count += 1

    def clickable_ancestor(self, limit: int = 6) -> "UiNode":
        if self.clickable:
            return self
        for ancestor in self.ancestors(limit):
            if ancestor.clickable:
                return ancestor
        return self

    def walk(self) -> Iterator["UiNode"]:
        yield self
        for child in self.children:
            yield from child.walk()

    def contains(self, x: int, y: int) -> bool:
        if not self.bounds:
            return False
        return (
            self.bounds.left <= x <= self.bounds.right
            and self.bounds.top <= y <= self.bounds.bottom
        )

    def __str__(self) -> str:
        parts = [self.class_name or "Node"]
        if self.text:
            parts.append(f"text={self.text!r}")
        if self.desc:
            parts.append(f"desc={self.desc!r}")
        if self.resource_id:
            parts.append(f"id={self.resource_id!r}")
        if self.bounds:
            parts.append(f"bounds={self.bounds}")
        return f"<{' '.join(parts)}>"


def iter_nodes(nodes: Iterable[UiNode]) -> Iterator[UiNode]:
    for node in nodes:
        yield from node.walk()
