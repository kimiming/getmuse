"""Parse VMOS accessibility XML into :class:`UiTree`."""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass

from muse_auto.core.errors import UiError
from muse_auto.ui.node import Rect, UiNode, parse_bool


@dataclass(frozen=True)
class UiTree:
    xml: str
    root: UiNode
    nodes: tuple[UiNode, ...]

    def walk(self):
        yield from self.root.walk()

    def find_all(self, selector) -> list[UiNode]:
        return [node for node in self.nodes if selector.matches(node)]

    def find(self, selector) -> UiNode | None:
        return selector.find(self)

    def visible_texts(self, limit: int = 80) -> list[str]:
        result: list[str] = []
        for node in self.nodes:
            if not node.visible:
                continue
            for value in (node.text, node.desc):
                value = value.strip()
                if value and value not in result:
                    result.append(value)
            if len(result) >= limit:
                break
        return result

    def summary(self, limit: int = 180) -> str:
        text = " / ".join(self.visible_texts(limit=40))
        return text[:limit]


def parse_dump(xml: str) -> UiTree:
    if not isinstance(xml, str) or "<hierarchy" not in xml:
        raise UiError("控件树为空或缺少 <hierarchy>")
    # Android often embeds control characters in content-desc; XML 1.0 forbids
    # them and ElementTree rejects the whole dump.
    xml = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", xml)
    try:
        root_element = ET.fromstring(xml)
    except ET.ParseError as exc:
        raise UiError(f"控件树 XML 解析失败：{exc}") from exc

    nodes: list[UiNode] = []

    def build(element: ET.Element, parent: UiNode | None, index: int) -> UiNode:
        attrs = dict(element.attrib)
        node = UiNode(
            index=index,
            text=str(attrs.get("text") or "").strip(),
            desc=str(attrs.get("content-desc") or "").strip(),
            resource_id=str(attrs.get("resource-id") or "").strip(),
            class_name=str(attrs.get("class") or "").strip(),
            package=str(attrs.get("package") or "").strip(),
            clickable=parse_bool(attrs.get("clickable")),
            enabled=parse_bool(attrs.get("enabled"), default=True),
            focused=parse_bool(attrs.get("focused")),
            password=parse_bool(attrs.get("password")),
            checkable=parse_bool(attrs.get("checkable")),
            checked=parse_bool(attrs.get("checked")),
            scrollable=parse_bool(attrs.get("scrollable")),
            selected=parse_bool(attrs.get("selected")),
            bounds=Rect.from_bounds(attrs.get("bounds")),
            parent=parent,
            attributes=attrs,
        )
        nodes.append(node)
        for child_index, child in enumerate(element):
            if child.tag.rsplit("}", 1)[-1] != "node":
                continue
            node.children.append(build(child, node, child_index))
        return node

    root = build(root_element, None, 0)
    if root.bounds is None and root.children:
        bounds = [child.bounds for child in root.children if child.bounds is not None]
        if bounds:
            root.bounds = Rect(
                min(item.left for item in bounds),
                min(item.top for item in bounds),
                max(item.right for item in bounds),
                max(item.bottom for item in bounds),
            )
    return UiTree(xml=xml, root=root, nodes=tuple(nodes))


def looks_like_dump(xml: str) -> bool:
    return bool(re.search(r"<hierarchy[\s>]", xml or ""))
