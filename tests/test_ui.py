from __future__ import annotations

import unittest
from pathlib import Path

from muse_auto.core.errors import UiError
from muse_auto.ui.parser import parse_dump
from muse_auto.ui.selector import Selector

FIXTURES = Path(__file__).parent / "fixtures"


def load(name: str):
    return parse_dump((FIXTURES / name).read_text(encoding="utf-8"))


class ParserTests(unittest.TestCase):
    def test_tree_shape_and_bounds(self):
        tree = load("welcome.xml")
        self.assertGreaterEqual(len(tree.nodes), 6)
        node = Selector(text="Get started").find(tree)
        self.assertIsNotNone(node)
        assert node is not None
        self.assertTrue(node.clickable)
        self.assertEqual(node.center, (540, 2030))
        self.assertEqual(node.bounds.width, 920)

    def test_selector_label_contains(self):
        tree = load("welcome.xml")
        node = Selector(label_contains=("continue with email",)).find(tree)
        self.assertIsNotNone(node)
        assert node is not None
        self.assertEqual(node.text, "Continue with email")

    def test_selector_text_contains_is_text_only(self):
        tree = load("welcome.xml")
        node = Selector(text_contains=("personal",)).find(tree)
        self.assertIsNotNone(node)
        self.assertEqual(node.text, "Your personal AI agent")

    def test_edit_text(self):
        tree = load("email.xml")
        node = Selector(editable=True).find(tree)
        self.assertIsNotNone(node)
        assert node is not None
        self.assertEqual(node.resource_id, "com.facebook.aura:id/email_input")

    def test_clickable_ancestor(self):
        xml = """<hierarchy><node class="android.widget.FrameLayout" clickable="true" bounds="[0,0][100,100]">
        <node class="android.widget.TextView" text="Continue" clickable="false" bounds="[10,10][90,40]" />
        </node></hierarchy>"""
        tree = parse_dump(xml)
        node = Selector(text="Continue").find(tree)
        self.assertIsNotNone(node)
        assert node is not None
        self.assertFalse(node.clickable)
        self.assertTrue(node.clickable_ancestor().clickable)

    def test_invalid_xml(self):
        with self.assertRaises(UiError):
            parse_dump("not xml")
        with self.assertRaises(UiError):
            parse_dump("<hierarchy><node")

    def test_invisible_nodes_are_ignored(self):
        xml = """<hierarchy><node class="android.widget.FrameLayout">
        <node class="android.widget.TextView" text="Hidden" bounds="[10,10][10,10]" />
        <node class="android.widget.TextView" text="Visible" bounds="[10,10][100,40]" />
        </node></hierarchy>"""
        tree = parse_dump(xml)
        self.assertIsNone(Selector(text="Hidden").find(tree))
        self.assertIsNotNone(Selector(text="Visible").find(tree))

    def test_control_characters_are_sanitized(self):
        xml = (
            '<hierarchy><node class="android.widget.TextView" '
            'text="bad\x01text" bounds="[10,10][100,40]" /></hierarchy>'
        )
        tree = parse_dump(xml)
        self.assertIsNotNone(Selector(text="badtext").find(tree))


if __name__ == "__main__":
    unittest.main()
