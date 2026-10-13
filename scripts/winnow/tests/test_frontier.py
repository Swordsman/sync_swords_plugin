"""Unit tests for frontier.py — the open items of a folded graph."""
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import frontier  # noqa: E402
from fold import fold, load  # noqa: E402

BASIC = """
(delta :turn 1
  (term alpha :gloss "first")
  (add (claim c1 (has alpha beta) :by user :src t1))
  (add (question q1 (is x y) :status open :by user :src t1))
  (add (edge (answers c1 q1))))
"""

STATUSES = """
(delta :turn 1
  (add (constraint k1 (has sys prop) :by user :src t1))
  (add (constraint k2 (has sys other) :status relaxed :by user :src t1))
  (add (decision d1 (use x) :by user :src t1))
  (add (decision d2 (use y) :status frozen :by user :src t1))
  (add (question q1 (is a b) :by user :src t1))
  (add (question q2 (is c d) :status answered :by user :src t1))
  (add (action a1 (do e) :by user :src t1))
  (add (action a2 (do f) :status doing :by user :src t1))
  (add (action a3 (do g) :status blocked :by user :src t1))
  (add (action a4 (do h) :status done :by user :src t1))
  (add (def f1 tid "a definition" :by user :src t1))
  (add (artifact r1 (file x) :by user :src t1)))
"""


class TestFrontier(unittest.TestCase):
    def test_keeps_open_question(self):
        self.assertIn("(question q1 (is x y))", frontier.render(fold(BASIC)))

    def test_answered_question_leaves(self):
        g = fold(BASIC + "(delta :turn 2 (update q1 :status answered))")
        self.assertNotIn("(question q1", frontier.render(g))

    def test_claims_never_appear_however_recent(self):
        # the recency tail lives in the digest now, not here
        self.assertNotIn("(claim c1", frontier.render(fold(BASIC)))

    def test_open_set_per_frame(self):
        self.assertEqual(frontier.frontier_ids(fold(STATUSES)),
                         ["k1", "d1", "q1", "a1", "a2", "a3"])

    def test_count_line(self):
        out = frontier.render(fold(STATUSES))
        self.assertTrue(out.splitlines()[-1].startswith("; +6 nodes not open"))

    def test_demo_log_entering_turn_8(self):
        # spec section 11: six constraints, the live proposal, the open question
        g = load(os.path.join(ROOT, "demo-deltas.wno"), upto=4)
        self.assertEqual(frontier.frontier_ids(g),
                         ["k1", "k2", "k3", "k4", "k5", "k6", "d3", "q3"])


if __name__ == "__main__":
    unittest.main()
