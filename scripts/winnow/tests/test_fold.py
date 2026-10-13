"""Unit tests for fold.py — parse, fold semantics, views, tiers, query,
hash ids, meta/profile. Zero dependencies: python3 -m unittest discover tests
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from fold import Graph, parse, tokenize, sx, Lit  # noqa: E402


def fold(src):
    g = Graph()
    for form in parse(tokenize(src)):
        if form[0] == "meta":
            g.set_meta(form)
        else:
            g.apply(form)
    return g


BASIC = """
(delta :turn 1
  (term alpha :gloss "first")
  (add (claim c1 (has alpha beta) :by user :src t1))
  (add (question q1 (is x y) :status open :by user :src t1))
  (add (edge (answers c1 q1))))
"""


class TestParse(unittest.TestCase):
    def test_roundtrip(self):
        forms = parse(tokenize('(a (b "c d") 1.0 :key val)'))
        self.assertEqual(sx(forms[0]), '(a (b "c d") 1.0 :key val)')

    def test_comments_stripped(self):
        forms = parse(tokenize("; comment\n(a b) ; tail\n(c)"))
        self.assertEqual(len(forms), 2)

    def test_string_literals_keep_spaces_and_parens_matter(self):
        forms = parse(tokenize('(x "a (b) ; c")'))
        self.assertIsInstance(forms[0][1], Lit)
        self.assertEqual(str(forms[0][1]), "a (b) ; c")


class TestFoldOps(unittest.TestCase):
    def test_add_and_defaults(self):
        g = fold(BASIC)
        self.assertEqual(g.nodes["c1"]["status"], "live")
        self.assertEqual(g.nodes["q1"]["status"], "open")
        self.assertEqual(g.edges, [("answers", "c1", "q1")])
        self.assertIn("alpha", g.terms)

    def test_duplicate_add_is_error(self):
        g = fold(BASIC + "(delta :turn 2 (add (claim c1 (has p q))))")
        self.assertTrue(any("duplicate" in e for e in g.errors))

    def test_update_shallow_merge(self):
        g = fold(BASIC + "(delta :turn 2 (update q1 :status answered))")
        self.assertEqual(g.nodes["q1"]["status"], "answered")

    def test_update_unknown_id(self):
        g = fold(BASIC + "(delta :turn 2 (update zz :status live))")
        self.assertTrue(any("unknown id zz" in e for e in g.errors))

    def test_supersede(self):
        g = fold("""
        (delta :turn 1
          (add (decision d1 (implement a b) :by user :src t1))
          (add (decision d2 (implement a c) :by user :src t1))
          (supersede d2 d1 :conf 0.8))
        """)
        self.assertEqual(g.nodes["d1"]["status"], "superseded")
        self.assertEqual(g.nodes["d1"]["status-conf"], "0.8")
        self.assertIn(("supersedes", "d2", "d1"), g.edges)

    def test_merge_rewrites_edges(self):
        g = fold("""
        (delta :turn 1
          (add (claim c1 (has a b) :by user :src t1))
          (add (claim c2 (has a b2) :by user :src t1))
          (add (claim c3 (has a b3) :by user :src t1))
          (add (edge (supports c1 c3)))
          (merge c1 c2))
        """)
        self.assertNotIn("c1", g.nodes)
        self.assertIn(("supports", "c2", "c3"), g.edges)

    def test_del_node_removes_incident_edges(self):
        g = fold(BASIC + "(delta :turn 2 (del c1))")
        self.assertNotIn("c1", g.nodes)
        self.assertEqual(g.edges, [])

    def test_del_edge(self):
        g = fold(BASIC + "(delta :turn 2 (del (edge (answers c1 q1))))")
        self.assertEqual(g.edges, [])
        self.assertIn("c1", g.nodes)

    def test_validate_dangling(self):
        g = fold("(delta :turn 1 (add (edge (supports zz yy))))")
        g.validate()
        self.assertTrue(any("dangling" in e for e in g.errors))

    def test_about_targets_term_valid(self):
        g = fold(BASIC + '(delta :turn 2 (add (edge (about q1 alpha))))')
        g.validate()
        self.assertEqual(g.errors, [])
        self.assertIn(("about", "q1", "alpha"), g.edges)

    def test_about_targets_unknown_still_dangles(self):
        g = fold(BASIC + '(delta :turn 2 (add (edge (about q1 no-such-thing))))')
        g.validate()
        self.assertTrue(any("dangling" in e for e in g.errors))

    def test_non_about_edge_to_term_still_dangles(self):
        g = fold(BASIC + '(delta :turn 2 (add (edge (supports q1 alpha))))')
        g.validate()
        self.assertTrue(any("dangling" in e for e in g.errors))


class TestViews(unittest.TestCase):
    def test_snapshot_deterministic_and_sorted(self):
        g = fold(BASIC)
        snap = g.snapshot()
        self.assertIn('(term alpha :gloss "first")', snap)
        # question sorts before claim in FRAME_ORDER
        self.assertLess(snap.index("(question q1"), snap.index("(claim c1"))

    def test_frontier_keeps_open_question(self):
        g = fold(BASIC)
        self.assertIn("(question q1 (is x y))", g.frontier())

    def test_frontier_dormant_count(self):
        g = fold(BASIC + "(delta :turn 2 (update q1 :status answered))")
        # q1 answered and out of the recency window? claims/defs tail keeps
        # c1; q1 should not appear as a question line
        self.assertNotIn("(question q1", g.frontier())


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
        g = fold(self.SRC)
        fire, hot, warm, cold = g.tiers()
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
        fire, hot, warm, cold = g.tiers()
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
        g = fold(self.HOP_SRC)          # default fire-hops 1
        fire, _, _, _ = g.tiers()
        self.assertIn("c1", fire)       # touched (P1)
        self.assertIn("c2", fire)       # one hop from c1

    def test_profile_knobs_respected(self):
        g = fold('(meta :profile (:tail 1 :fire-hops 0))' + self.HOP_SRC)
        fire, _, _, _ = g.tiers()
        self.assertIn("c1", fire)       # touched
        self.assertNotIn("c2", fire)    # 0 hops: neighbors excluded
        self.assertEqual(g.profile["tail"], 1)

    def test_tiers_never_logged(self):
        g = fold(self.SRC)
        self.assertNotIn("fire", g.snapshot())


class TestMeta(unittest.TestCase):
    def test_headerless_defaults(self):
        g = fold(BASIC)
        self.assertEqual(g.meta, {})
        self.assertEqual(g.profile["tail"], 6)

    def test_header_parsed(self):
        g = fold('(meta :winnow-version "0.2" :semantic-rep "registry-v0.1" '
                 ':profile (:tail 3 :widening-base 4))' + BASIC)
        self.assertEqual(str(g.meta["winnow-version"]), "0.2")
        self.assertEqual(g.profile["tail"], 3)
        self.assertEqual(g.profile["widening-base"], 4)
        self.assertEqual(g.profile["fire-hops"], 1)   # default survives


class TestQuery(unittest.TestCase):
    def test_query_by_frame_status_by(self):
        g = fold(BASIC)
        out = g.query("frame=claim status=live by=user")
        self.assertIn("c1", out)
        self.assertNotIn("q1", out)

    def test_query_by_term(self):
        g = fold(BASIC)
        self.assertIn("c1", g.query("term=alpha"))
        self.assertEqual(g.query("term=nonexistent"), "")

    def test_query_by_src(self):
        g = fold(BASIC)
        self.assertIn("c1", g.query("src=t1"))


class TestHashIds(unittest.TestCase):
    def test_same_payload_same_hash_across_logs(self):
        a = fold('(delta :turn 1 (add (claim c1 (has x y) :by user :src t1)))')
        b = fold('(delta :turn 5 (add (claim c9 (has x y) :by other :src t5)))')
        self.assertEqual(a.hash_id("c1"), b.hash_id("c9"))

    def test_different_frame_different_hash(self):
        g = fold("""
        (delta :turn 1
          (add (claim c1 (has x y) :by user :src t1))
          (add (constraint k1 (has x y) :strength hard :by user :src t1)))
        """)
        self.assertNotEqual(g.hash_id("c1"), g.hash_id("k1"))

    def test_node_ref_args_resolve_recursively(self):
        # (achieves d1 goal) must hash identically even when d1's serial
        # differs between logs, because the ref resolves to d1's own hash
        a = fold("""
        (delta :turn 1
          (add (decision d1 (implement s t) :by user :src t1))
          (add (claim c1 (achieves d1 goal) :by user :src t1)))
        """)
        b = fold("""
        (delta :turn 1
          (add (decision d7 (implement s t) :by user :src t3))
          (add (claim c9 (achieves d7 goal) :by user :src t3)))
        """)
        self.assertEqual(a.hash_id("c1"), b.hash_id("c9"))

    def test_cycle_terminates(self):
        g = fold("""
        (delta :turn 1
          (add (claim c1 (about-ref c2) :by user :src t1))
          (add (claim c2 (about-ref c1) :by user :src t1)))
        """)
        self.assertTrue(g.hash_id("c1"))  # no infinite recursion


class TestStatsDict(unittest.TestCase):
    def test_returns_structured_metrics(self):
        g = fold(BASIC)
        d = g.stats_dict()
        self.assertEqual(d["nodes"], 2)
        self.assertEqual(d["edges"], 1)
        self.assertEqual(d["terms"], 1)
        self.assertEqual(d["deltas"], 1)
        self.assertAlmostEqual(d["edges_per_node"], 0.5)
        self.assertEqual(d["edge_types_used"], 1)
        self.assertIn("claim", d["frames"])
        self.assertIn("answers", d["edge_types"])
        self.assertGreater(d["snapshot_chars"], 0)

    def test_empty_graph(self):
        g = Graph()
        d = g.stats_dict()
        self.assertEqual(d["nodes"], 0)
        self.assertEqual(d["edges_per_node"], 0)

    def test_yield_curve_monotonic(self):
        src = BASIC + """
        (delta :turn 2
          (add (claim c2 (needs beta gamma) :by assistant :src t2))
          (add (edge (supports c2 c1))))
        """
        g = Graph()
        prev_nodes = 0
        for form in parse(tokenize(src)):
            if form[0] == "meta":
                g.set_meta(form)
                continue
            g.apply(form)
            d = g.stats_dict()
            self.assertGreaterEqual(d["nodes"], prev_nodes)
            prev_nodes = d["nodes"]
        self.assertEqual(prev_nodes, 3)


class TestDemoLog(unittest.TestCase):
    """Pin the spec section 11 verbatim numbers."""

    def setUp(self):
        path = os.path.join(os.path.dirname(__file__), "..",
                            "demo-deltas.wno")
        with open(path) as f:
            self.g = fold(f.read())

    def test_counts(self):
        self.assertEqual(len(self.g.nodes), 37)
        self.assertEqual(len(self.g.edges), 25)
        self.assertEqual(len(self.g.terms), 7)

    def test_validation_clean(self):
        self.assertEqual(self.g.validate(), [])

    def test_snapshot_size(self):
        self.assertEqual(len(self.g.snapshot()), 4465)


if __name__ == "__main__":
    unittest.main()
