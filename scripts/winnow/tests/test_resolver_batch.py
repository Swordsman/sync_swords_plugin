"""Unit tests for the resolver-layer batch: term-usage index and
status-gated mass, --concepts and --stale views, ranked resolution,
constituent-aware term matching, and Kimi vocabulary aliases."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from fold import Graph, parse, tokenize  # noqa: E402
from winnow import Resolver  # noqa: E402


def graph_from(src):
    g = Graph()
    for form in parse(tokenize(src)):
        if form[0] == "meta":
            g.set_meta(form)
        else:
            g.apply(form)
    return g


MASS_SRC = """
(delta :turn 1
  (term auth-system :gloss "the login stack")
  (term reach :gloss "pull query against dormant material")
  (term term-registry :gloss "alias table travelling with the log")
  (add (claim c1 (uses auth-system tokens) :by user :src t1))
  (add (claim c2 (has auth-system audit-log) :by user :src t1))
  (add (decision d1 (adopt auth-system oauth) :status superseded
       :by user :src t1)))
(delta :turn 2
  (add (question q1 (secure auth-system how) :status open :by user :src t2))
  (add (decision d2 (review term-registry aliases) :status proposed
       :by user :src t2))
  (add (action a1 (harden auth-system) :status doing :by user :src t2)))
(delta :turn 3
  (add (claim c3 (has other topic) :by user :src t3)))
(delta :turn 4
  (add (claim c4 (has more topic) :by user :src t4)))
(delta :turn 5
  (add (claim c5 (has still more) :by user :src t5)))
"""


class TestUsageMass(unittest.TestCase):
    def setUp(self):
        self.g = graph_from(MASS_SRC)

    def test_usage_index_lists_referencing_nodes(self):
        usage = self.g.term_usage()
        self.assertEqual(set(usage["auth-system"]),
                         {"c1", "c2", "d1", "q1", "a1"})
        self.assertEqual(usage["reach"], [])

    def test_mass_is_status_gated(self):
        # d1 is superseded -> gated out: 5 refs but mass 4
        mass = self.g.term_mass()
        self.assertEqual(mass["auth-system"], 4)
        self.assertEqual(mass["term-registry"], 1)
        self.assertEqual(mass["reach"], 0)

    def test_concepts_sorted_by_mass_desc(self):
        lines = self.g.concepts().splitlines()
        self.assertTrue(lines[0].startswith("auth-system"))
        self.assertIn("mass=4", lines[0])

    def test_node_mass_gates_dead_endpoints(self):
        g = graph_from(MASS_SRC + """
(delta :turn 6
  (add (edge (supports c1 q1)))
  (add (edge (about d1 c1))))
""")
        # c1 touches q1 (open, counts) and d1 (superseded, gated)
        self.assertEqual(g.node_mass("c1"), 1)


class TestStaleView(unittest.TestCase):
    def test_untouched_actionables_surface(self):
        g = graph_from(MASS_SRC)
        out = g.stale(3)
        self.assertIn("q1", out)
        self.assertIn("d2", out)
        self.assertIn("a1", out)
        self.assertNotIn("c5", out)   # claims aren't stale-tracked

    def test_touch_resets_age(self):
        g = graph_from(MASS_SRC + """
(delta :turn 6 (update q1 :by user))
""")
        out = g.stale(3)
        self.assertNotIn("q1", out)
        self.assertIn("a1", out)

    def test_quiet_when_nothing_stale(self):
        g = graph_from(MASS_SRC)
        self.assertEqual(g.stale(99), "; no stale nodes")


class TestConstituentMatching(unittest.TestCase):
    def test_constituent_finds_compound_term(self):
        g = graph_from(MASS_SRC)
        rung, hits = Resolver(g).resolve(["auth"])
        self.assertLessEqual(rung, 3)
        self.assertIn("q1", hits)     # references auth-system

    def test_whole_id_not_its_own_constituent(self):
        g = graph_from(MASS_SRC)
        r = Resolver(g)
        self.assertNotIn(kebab_id := "reach", r.constituents.get(kebab_id,
                                                                 set()))


class TestRanking(unittest.TestCase):
    def test_rank_key_status_then_mass_then_recency(self):
        g = graph_from(MASS_SRC)
        r = Resolver(g)
        # q1 open (class 0, delta 2) > c1 live (class 0, delta 1) > d1
        # superseded (class 2)
        self.assertEqual(r._rank(["d1", "c1", "q1"]), ["q1", "c1", "d1"])

    def test_cold_hits_come_back_ranked(self):
        # a0 (done, class 1) and d1 (superseded, class 2) are both cold
        # and both mention oauth; nothing resident does
        g = graph_from(MASS_SRC.replace(
            "(add (question q1",
            "(add (action a0 (deploy oauth) :status done :by user :src t2))\n"
            "  (add (question q1"))
        rung, hits = Resolver(g).resolve(["oauth"])
        self.assertEqual(rung, 3)
        self.assertEqual(hits, ["a0", "d1"])


POLY_SRC = """
(delta :turn 1
  (term tap/faucet :gloss "water fixture sense")
  (term tap/strike :gloss "light blow sense")
  (add (claim p1 (drips tap/faucet kitchen) :by user :src t1))
  (add (claim p2 (heard tap/strike window) :by user :src t1)))
"""


class TestSenseQualifiedTerms(unittest.TestCase):
    def setUp(self):
        self.g = graph_from(POLY_SRC)

    def test_bare_word_reaches_all_senses(self):
        rung, hits = Resolver(self.g).resolve(["tap"])
        self.assertEqual(set(hits), {"p1", "p2"})

    def test_qualified_reference_hits_one_sense(self):
        rung, hits = Resolver(self.g).resolve(["tap/faucet"])
        self.assertEqual(hits, ["p1"])

    def test_senses_map_built(self):
        r = Resolver(self.g)
        self.assertEqual(r.senses.get("tap"),
                         {"tap/faucet", "tap/strike"})


class TestKimiAliases(unittest.TestCase):
    def test_kimi_vocabulary_reaches_canonical_terms(self):
        g = graph_from(MASS_SRC)
        rung, hits = Resolver(g).resolve(["concept-space"])
        self.assertLessEqual(rung, 3)
        self.assertIn("d2", hits)     # references term-registry
        # echo -> usage-mass/promotion: no such terms here -> honest miss
        rung, hits = Resolver(g).resolve(["echo"])
        self.assertEqual((rung, hits), (5, []))


class TestCanonAnchorResolution(unittest.TestCase):
    def test_canon_value_reaches_term(self):
        g = graph_from("""
(delta :turn 1
  (term auth-system :gloss "authentication" :canon "Authentication")
  (add (claim c1 (uses app auth-system) :by user :src t1)))
""")
        rung, hits = Resolver(g).resolve(["authentication"])
        self.assertLessEqual(rung, 3)
        self.assertIn("c1", hits)


if __name__ == "__main__":
    unittest.main()
