"""Unit tests for digest.py — tier computation and the rendered window."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import digest  # noqa: E402
import frontier  # noqa: E402
from fold import fold  # noqa: E402


class TestTiers(unittest.TestCase):
    SRC = """
    (delta :turn 1
      (add (constraint k1 (has sys prop) :strength hard :by user :src t1))
      (add (claim c1 (has a b) :by user :src t1))
      (add (claim c2 (has c d) :by user :src t1)))
    (delta :turn 2
      (add (claim c3 (has e f) :by user :src t2))
      (add (question q1 (is g h) :status open :by user :src t2))
      (add (edge (supports c3 q1))))
    """

    def test_fire_is_last_delta_touch_plus_hop(self):
        fire, hot, warm, cold = digest.tiers(fold(self.SRC))
        self.assertIn("c3", fire)
        self.assertIn("q1", fire)
        self.assertNotIn("c1", fire)

    def test_invariant_holds_dormant_neighbors_warm(self):
        g = fold(self.SRC + """
        (delta :turn 3
          (add (decision d1 (implement x y) :by user :src t3))
          (add (decision d2 (implement x z) :by user :src t3))
          (supersede d2 d1)
          (add (claim c4 (has i j) :by user :src t3))
          (add (edge (about c4 d1))))
        """)
        fire, hot, warm, cold = digest.tiers(g)
        # d1 superseded but edge-held by c4/d2 (both touched -> fire)
        self.assertIn("d1", fire | set(hot) | set(warm))

    HOP_SRC = """
    (delta :turn 1
      (add (claim c1 (has a b) :by user :src t1))
      (add (claim c2 (has c d) :by user :src t1))
      (add (edge (supports c1 c2))))
    (delta :turn 2
      (update c1 :conf 0.9))
    """

    def test_fire_hop_expansion(self):
        fire, _, _, _ = digest.tiers(fold(self.HOP_SRC))   # default fire-hops 1
        self.assertIn("c1", fire)       # touched (P1)
        self.assertIn("c2", fire)       # one hop from c1

    def test_profile_knobs_respected(self):
        g = fold('(meta :profile (:tail 1 :fire-hops 0))' + self.HOP_SRC)
        fire, _, _, _ = digest.tiers(g)
        self.assertIn("c1", fire)       # touched
        self.assertNotIn("c2", fire)    # 0 hops: neighbors excluded
        self.assertEqual(g.profile["tail"], 1)

    def test_tiers_never_logged(self):
        self.assertNotIn("fire", fold(self.SRC).snapshot())


class TestHotTier(unittest.TestCase):
    SRC = """
    (delta :turn 1
      (add (constraint k1 (has sys prop) :by user :src t1))
      (add (claim c1 (has a b) :by user :src t1))
      (add (claim c2 (has c d) :by user :src t1))
      (add (claim c3 (has e f) :by user :src t1)))
    (delta :turn 2
      (add (question q1 (is g h) :by user :src t2)))
    """

    def test_hot_is_frontier_plus_recent_tail(self):
        g = fold(self.SRC)
        fire, hot, _, _ = digest.tiers(g)
        self.assertEqual(fire, {"q1"})
        self.assertEqual(set(hot), {"k1", "c1", "c2", "c3"})
        self.assertEqual(frontier.frontier_ids(g), ["k1", "q1"])

    def test_tail_length_is_the_profile_knob(self):
        g = fold('(meta :profile (:tail 2))' + self.SRC)
        _, hot, _, cold = digest.tiers(g)
        self.assertEqual(set(hot), {"k1", "c2", "c3"})
        self.assertIn("c1", cold)
        self.assertEqual(digest.tail_ids(g), ["c2", "c3"])

    def test_render_labels_hot_tier(self):
        out = digest.render(fold(self.SRC))
        self.assertIn("; --- hot: frontier + recent tail ---", out)
        self.assertIn("(claim c3 (has e f))", out)


class TestPromotion(unittest.TestCase):
    SRC = """
    (delta :turn 1
      (add (decision d1 (use x) :status frozen :by user :src t1)))
    (delta :turn 2
      (add (claim c1 (has a b) :by user :src t2)))
    """

    def test_fold_never_ages_promotions(self):
        g = fold(self.SRC)
        digest.promote(g, "d1")
        before = dict(g.promotions)
        g.apply(["delta", ":turn", "3"])
        self.assertEqual(g.promotions, before)   # expiry is read, not counted down
        self.assertIn("d1", digest.tiers(g)[0])

    def test_promote_prunes_expired_entries(self):
        g = fold(self.SRC)
        digest.promote(g, "d1")
        for t in (3, 4):
            g.apply(["delta", ":turn", str(t)])
        digest.promote(g, "c1")
        self.assertEqual(set(g.promotions), {"c1"})


if __name__ == "__main__":
    unittest.main()
