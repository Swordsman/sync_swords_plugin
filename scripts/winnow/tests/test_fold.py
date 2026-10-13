"""Unit tests for fold.py — fold semantics, validation, snapshot, hash ids,
meta/profile, stats. The views have their own files: test_frontier.py,
test_digest.py, test_query.py; the reader is test_sexpr.py. Zero dependencies: python3 -m unittest discover tests
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from fold import Graph, parse, tokenize, sx, Lit  # noqa: E402,F401


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
