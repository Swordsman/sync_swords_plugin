"""Tests for mega-fold.py — canon-map application, junk-term exclusion."""
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from fold import Graph, Lit, parse, tokenize, anns  # noqa: E402
from merge import load  # noqa: E402
import importlib
mega_fold = importlib.import_module("mega-fold")
apply_canon_map = mega_fold.apply_canon_map
apply_exclude_terms = mega_fold.apply_exclude_terms
load_exclude_terms = mega_fold.load_exclude_terms


def make_graph(src):
    g = Graph()
    for form in parse(tokenize(src)):
        if form[0] == "meta":
            g.set_meta(form)
        else:
            g.apply(form)
    return g


GRAPH_A = """
(meta :winnow-version "0.2")
(delta :turn 1
  (term alpha :gloss "first concept")
  (term beta :gloss "second concept")
  (term junk-word :gloss "")
  (term has-property :gloss "")
  (add (claim c1 (has alpha beta) :by user :src t1)))
"""

GRAPH_B = """
(meta :winnow-version "0.2")
(delta :turn 1
  (term alpha-v2 :gloss "first concept restated")
  (term gamma :gloss "third concept")
  (term junk-word :gloss "")
  (add (claim c1 (is gamma real) :by user :src t1)))
"""


class TestExcludeTerms(unittest.TestCase):
    def test_removes_matching_terms(self):
        g = make_graph(GRAPH_A)
        self.assertIn("junk-word", g.terms)
        self.assertIn("has-property", g.terms)
        removed = apply_exclude_terms([g], {"junk-word", "has-property"})
        self.assertEqual(removed, 2)
        self.assertNotIn("junk-word", g.terms)
        self.assertNotIn("has-property", g.terms)
        self.assertIn("alpha", g.terms)
        self.assertIn("beta", g.terms)

    def test_ignores_non_matching(self):
        g = make_graph(GRAPH_A)
        removed = apply_exclude_terms([g], {"nonexistent-term"})
        self.assertEqual(removed, 0)
        self.assertEqual(len(g.terms), 4)

    def test_works_across_multiple_graphs(self):
        ga = make_graph(GRAPH_A)
        gb = make_graph(GRAPH_B)
        removed = apply_exclude_terms([ga, gb], {"junk-word"})
        self.assertEqual(removed, 2)
        self.assertNotIn("junk-word", ga.terms)
        self.assertNotIn("junk-word", gb.terms)

    def test_graph_still_validates(self):
        g = make_graph(GRAPH_A)
        apply_exclude_terms([g], {"junk-word", "has-property"})
        errs = g.validate()
        self.assertFalse(errs)


class TestLoadExcludeTerms(unittest.TestCase):
    def test_loads_categorized_json(self):
        data = {
            "_comment": "test",
            "edge_types": ["has-function", "supports"],
            "bare_words": ["claim", "question"],
        }
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(data, f)
            path = f.name
        try:
            result = load_exclude_terms(path)
            self.assertEqual(result, {"has-function", "supports", "claim", "question"})
        finally:
            os.unlink(path)

    def test_skips_underscore_keys(self):
        data = {"_comment": "ignored", "junk": ["a", "b"]}
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(data, f)
            path = f.name
        try:
            result = load_exclude_terms(path)
            self.assertEqual(result, {"a", "b"})
        finally:
            os.unlink(path)


class TestCanonMapWithExclusion(unittest.TestCase):
    def test_exclude_before_canon(self):
        """Exclusion runs before canon-map so junk terms don't get patched."""
        g = make_graph(GRAPH_A)
        apply_exclude_terms([g], {"junk-word", "has-property"})
        canon = {"alpha": "First concept", "beta": "First concept"}
        patched = apply_canon_map([g], canon)
        self.assertEqual(patched, 2)
        ta = anns(list(g.terms["alpha"]))
        self.assertEqual(ta["canon"], "First concept")

    def test_canon_collapses_after_junk_removal(self):
        """After junk removal and canon patching, remaining terms are clean."""
        ga = make_graph(GRAPH_A)
        gb = make_graph(GRAPH_B)
        apply_exclude_terms([ga, gb], {"junk-word", "has-property"})
        canon = {"alpha": "Alpha concept", "alpha-v2": "Alpha concept"}
        patched = apply_canon_map([ga, gb], canon)
        self.assertEqual(patched, 2)
        ta_a = anns(list(ga.terms["alpha"]))
        ta_b = anns(list(gb.terms["alpha-v2"]))
        self.assertEqual(ta_a["canon"], "Alpha concept")
        self.assertEqual(ta_b["canon"], "Alpha concept")


if __name__ == "__main__":
    unittest.main()
