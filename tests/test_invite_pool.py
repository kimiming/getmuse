from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from muse_auto.services.invite_pool import InviteCodePool, InvitePoolExhausted


class InviteCodePoolTests(unittest.TestCase):
    def test_uses_then_next_code(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "inviteCode.txt"
            path.write_text("AAAA\nBBBB\n", encoding="utf-8")
            pool = InviteCodePool(path, uses_per_code=2)

            first = pool.acquire()
            second = pool.acquire()
            third = pool.acquire()
            self.assertEqual((first.code, first.used), ("AAAA", 1))
            self.assertEqual((second.code, second.used), ("AAAA", 2))
            self.assertEqual((third.code, third.used), ("BBBB", 1))
            text = path.read_text(encoding="utf-8")
            self.assertIn("AAAA---用了2次", text)
            self.assertIn("BBBB---用了1次", text)

    def test_exhausted(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "inviteCode.txt"
            path.write_text("AAAA---用了2次\n", encoding="utf-8")
            pool = InviteCodePool(path, uses_per_code=2)
            with self.assertRaises(InvitePoolExhausted):
                pool.acquire()

    def test_rollback(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "inviteCode.txt"
            path.write_text("AAAA\n", encoding="utf-8")
            pool = InviteCodePool(path, uses_per_code=2)
            pool.acquire()
            pool.rollback("AAAA")
            self.assertEqual(pool.status()[0].used, 0)


if __name__ == "__main__":
    unittest.main()
