"""Unit tests for the closed status vocabulary (spec section 2): fold.py
warns (never errors) on off-spec statuses -- existing runs/sessions logs
are grandfathered -- while the winnow.py normalizer rejects them outright
on new ops."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from fold import Graph, parse, tokenize  # noqa: E402
from winnow import Normalizer, extract_forms  # noqa: E402


def graph_from(src):
    g = Graph()
    for form in parse(tokenize(src)):
        if form[0] == "meta":
            g.set_meta(form)
        else:
            g.apply(form)
    return g


LEGAL_SRC = """
(delta :turn 1
  (add (claim c1 (has a b) :status corrected :by user :src t1))
  (add (question q1 (is a b) :status answered :by user :src t1))
  (add (decision d1 (adopt a b) :status frozen :by user :src t1))
  (add (constraint k1 (bounds a b) :status relaxed :by user :src t1))
  (add (action a1 (do a b) :status blocked :by user :src t1))
  (add (def f1 term-x "gloss" :status deprecated :by user :src t1))
  (add (artifact r1 "some/path" :status live :by user :src t1)))
"""


class TestFoldStatusWarnings(unittest.TestCase):
    def test_warns_on_offspec_status_in_add(self):
        g = graph_from(
            "(delta :turn 1 (add (question q3 (is a b) "
            ":status partially-answered :by user :src t1)))")
        self.assertEqual(len(g.warnings), 1)
        self.assertIn("partially-answered", g.warnings[0])
        self.assertIn("question", g.warnings[0])
        self.assertIn("q3", g.warnings[0])
        self.assertEqual(g.errors, [])

    def test_warns_on_offspec_status_via_update(self):
        g = graph_from(
            "(delta :turn 1 (add (question q1 (is a b) "
            ":status open :by user :src t1)))"
            "(delta :turn 2 (update q1 :status resolved))")
        self.assertEqual(len(g.warnings), 1)
        self.assertIn("resolved", g.warnings[0])
        self.assertIn("q1", g.warnings[0])
        self.assertEqual(g.errors, [])
        # node is still applied normally -- the warning is advisory
        self.assertEqual(g.nodes["q1"]["status"], "resolved")

    def test_no_warnings_for_legal_statuses(self):
        g = graph_from(LEGAL_SRC)
        self.assertEqual(g.warnings, [])

    def test_validation_ok_despite_warnings(self):
        g = graph_from(
            "(delta :turn 1 (add (claim c1 (has a b) "
            ":status open :by user :src t1)))")  # "open" is off-spec for claim
        errs = g.validate()
        self.assertEqual(errs, [])   # validation stays OK on warnings alone
        self.assertEqual(len(g.warnings), 1)

    def test_supersede_no_warning_for_legal_frame(self):
        # supersede sets :status superseded internally -- legal for claim,
        # must not warn.
        g = graph_from("""
(delta :turn 1
  (add (claim c1 (has a b) :by user :src t1))
  (add (claim c2 (has c d) :by user :src t1)))
(delta :turn 2
  (supersede c2 c1))
""")
        self.assertEqual(g.warnings, [])
        self.assertEqual(g.nodes["c1"]["status"], "superseded")

    def test_supersede_question_no_warning(self):
        # "superseded" is now legal for all frame types.
        g = graph_from("""
(delta :turn 1
  (add (question q1 (is a b) :by user :src t1))
  (add (claim c9 (has c d) :by user :src t1)))
(delta :turn 2
  (supersede c9 q1))
""")
        self.assertEqual(g.warnings, [])
        self.assertEqual(g.nodes["q1"]["status"], "superseded")


class TestNormalizerStatusRejection(unittest.TestCase):
    def test_rejects_offspec_status_on_add(self):
        ops, rejects = Normalizer(Graph()).normalize(extract_forms(
            '(add (claim x1 (has a b) :status open :by user :src t1))'))
        self.assertEqual(ops, [])
        self.assertEqual(len(rejects), 1)
        self.assertIn("off-spec status open for claim", rejects[0])

    def test_rejects_offspec_status_on_update(self):
        g = graph_from(
            "(delta :turn 1 (add (question q1 (is a b) "
            ":status open :by user :src t1)))")
        ops, rejects = Normalizer(g).normalize(extract_forms(
            '(update q1 :status resolved)'))
        self.assertEqual(ops, [])
        self.assertEqual(len(rejects), 1)
        self.assertIn("off-spec status resolved for question", rejects[0])

    def test_passes_legal_statuses(self):
        ops, rejects = Normalizer(Graph()).normalize(extract_forms(
            '(add (question x1 (is a b) :status answered '
            ':by user :src t1))'))
        self.assertEqual(rejects, [])
        self.assertEqual(len(ops), 1)


if __name__ == "__main__":
    unittest.main()
