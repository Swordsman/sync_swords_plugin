"""Unit tests for split.py — procedural log slicing."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from fold import Graph, parse, tokenize  # noqa: E402
from split import slice_ids, split, render  # noqa: E402


def graph_from(src):
    g = Graph()
    for form in parse(tokenize(src)):
        if form[0] == "meta":
            g.set_meta(form)
        else:
            g.apply(form)
    return g


def refold(text):
    g = Graph()
    for form in parse(tokenize(text)):
        if form[0] == "meta":
            g.set_meta(form)
        else:
            g.apply(form)
    g.validate()
    return g


# two disconnected topic clusters + one live hard constraint + a claim
# whose payload references a decision by node id
SRC = """
(delta :turn 1
  (term topic-a :gloss "first topic")
  (term topic-b :gloss "second topic")
  (add (constraint k1 (has system reliability)
       :strength hard :by user :src t1))
  (add (decision d1 (implement topic-a plan) :by user :src t1))
  (add (claim c1 (about-detail topic-a) :by user :src t1))
  (add (edge (about c1 d1)))
  (add (claim c2 (achieves d1 goal) :by assistant :src t2))
  (add (decision d2 (implement topic-b other) :by user :src t3))
  (add (claim c3 (about-detail topic-b) :by user :src t3))
  (add (edge (about c3 d2))))
"""


class TestSliceIds(unittest.TestCase):
    def setUp(self):
        self.g = graph_from(SRC)

    def test_seed_plus_hop(self):
        sel = slice_ids(self.g, ["d1"], hops=1, carry_constraints=False)
        self.assertIn("c1", sel)          # one hop via about edge
        self.assertNotIn("c3", sel)       # other cluster excluded
        self.assertNotIn("d2", sel)

    def test_component_expansion(self):
        sel = slice_ids(self.g, ["c1"], hops=-1, carry_constraints=False)
        self.assertEqual(sel, {"c1", "d1", "c2"})

    def test_constraints_carried_by_default(self):
        sel = slice_ids(self.g, ["d2"], hops=0)
        self.assertIn("k1", sel)          # temperature-exempt, rides along

    def test_no_constraints_flag(self):
        sel = slice_ids(self.g, ["d2"], hops=0, carry_constraints=False)
        self.assertNotIn("k1", sel)

    def test_validity_closure_pulls_payload_refs(self):
        # c2's payload references d1; selecting only c2 must pull d1
        sel = slice_ids(self.g, ["c2"], hops=0, carry_constraints=False)
        self.assertIn("d1", sel)

    def test_zero_hops_no_expansion(self):
        sel = slice_ids(self.g, ["d1"], hops=0, carry_constraints=False)
        self.assertNotIn("c1", sel)       # edge neighbor NOT pulled
        self.assertEqual(sel, {"d1"})


class TestSplit(unittest.TestCase):
    def setUp(self):
        self.g = graph_from(SRC)

    def test_edges_kept_only_inside(self):
        sel = slice_ids(self.g, ["d1"], hops=1, carry_constraints=False)
        terms, ids, kept, cut = split(self.g, sel)
        self.assertIn(("about", "c1", "d1"), kept)
        self.assertNotIn(("about", "c3", "d2"), kept)

    def test_cut_edges_reported(self):
        sel = slice_ids(self.g, ["c1"], hops=0, carry_constraints=False)
        # c1 selected, d1 not (no closure need: c1 payload has no node ref)
        terms, ids, kept, cut = split(self.g, sel)
        self.assertIn(("about", "c1", "d1"), cut)
        self.assertEqual(kept, [])

    def test_terms_scoped_to_slice(self):
        sel = slice_ids(self.g, ["d2"], hops=1, carry_constraints=False)
        terms, *_ = split(self.g, sel)
        self.assertIn("topic-b", terms)
        self.assertNotIn("topic-a", terms)

    def test_ids_preserved(self):
        sel = slice_ids(self.g, ["d1"], hops=1, carry_constraints=False)
        terms, ids, kept, cut = split(self.g, sel)
        self.assertIn("d1", ids)          # parent ids, no renumbering


class TestRender(unittest.TestCase):
    def test_slice_folds_clean(self):
        g = graph_from(SRC)
        sel = slice_ids(g, ["d1"], hops=1)
        text = render(g, *split(g, sel))
        s = refold(text)
        self.assertEqual(s.errors, [])
        self.assertIn("d1", s.nodes)
        self.assertIn("k1", s.nodes)
        self.assertEqual(s.nodes["d1"]["status"], "proposed")

    def test_cut_edges_are_comments_not_ops(self):
        g = graph_from(SRC)
        sel = slice_ids(g, ["c1"], hops=0, carry_constraints=False)
        text = render(g, *split(g, sel))
        self.assertIn("; cut edge (about c1 d1)", text)
        s = refold(text)
        self.assertEqual(s.edges, [])     # comment, not a dangling edge

    def test_meta_carried_from_parent(self):
        g = graph_from('(meta :winnow-version "0.2" '
                       ':semantic-rep "registry-v0.1")' + SRC)
        text = render(g, *split(g, slice_ids(g, ["d1"])))
        self.assertTrue(text.startswith('(meta :winnow-version "0.2"'))

    def test_cover_property_slice_plus_rest(self):
        g = graph_from(SRC)
        sel = slice_ids(g, ["d1"], hops=-1)
        rest_sel = slice_ids(g, set(g.nodes) - sel, hops=0)
        self.assertEqual(sel | rest_sel, set(g.nodes))  # cover

    def test_status_conflict_free_roundtrip_with_merge(self):
        # split then merge the pieces: node set must be recovered
        from merge import merge as do_merge, render as merge_render
        g = graph_from(SRC)
        sel = slice_ids(g, ["d1"], hops=-1)
        rest_sel = slice_ids(g, set(g.nodes) - sel, hops=0)
        a = refold(render(g, *split(g, sel)))
        b = refold(render(g, *split(g, rest_sel)))
        merged = refold(merge_render(*do_merge([a, b])))
        self.assertEqual(len(merged.nodes), len(g.nodes))
        # every original edge survives the round trip (modulo renumbering)
        self.assertEqual(len(merged.edges), len(g.edges))


if __name__ == "__main__":
    unittest.main()
