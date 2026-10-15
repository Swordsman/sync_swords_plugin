"""Unit tests for query.py — the key=value query layer and hash table.
(concepts and stale are pinned in test_resolver_batch.py, where their data
lives.)"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import query  # noqa: E402
from fold import fold  # noqa: E402

BASIC = """
(delta :turn 1
  (term alpha :gloss "first")
  (add (claim c1 (has alpha beta) :by user :src t1))
  (add (question q1 (is x y) :status open :by user :src t1))
  (add (edge (answers c1 q1))))
"""


class TestQuery(unittest.TestCase):
    def test_query_by_frame_status_by(self):
        out = query.query(fold(BASIC), "frame=claim status=live by=user")
        self.assertIn("c1", out)
        self.assertNotIn("q1", out)

    def test_query_by_term(self):
        g = fold(BASIC)
        self.assertIn("c1", query.query(g, "term=alpha"))
        self.assertEqual(query.query(g, "term=nonexistent"), "")

    def test_query_by_src(self):
        self.assertIn("c1", query.query(fold(BASIC), "src=t1"))

    def test_query_ids(self):
        self.assertEqual(query.query_ids(fold(BASIC), "frame=question"), ["q1"])

    def test_hashes_table_lists_every_node(self):
        g = fold(BASIC)
        rows = query.hashes(g).splitlines()
        self.assertEqual(len(rows), 2)
        self.assertIn(g.hash_id("c1"), "\n".join(rows))


if __name__ == "__main__":
    unittest.main()
