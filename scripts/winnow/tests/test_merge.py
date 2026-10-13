"""Unit tests for merge.py — cross-log merge on content-hash join keys."""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from fold import Graph, parse, tokenize  # noqa: E402
from merge import merge, render, load  # noqa: E402


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


LOG_A = """
(delta :turn 1
  (term fuse-vfs :gloss "userspace vfs")
  (add (claim c1 (causes single-file-fs total-loss-risk) :by user :src t1))
  (add (constraint k1 (has target-fs json-semantics)
       :strength hard :by user :src t1))
  (add (edge (motivates c1 k1))))
"""

LOG_B = """
(delta :turn 3
  (term fuse-vfs :gloss "userspace vfs")
  (term xattr :gloss "extended attribute")
  (add (claim c1 (causes single-file-fs total-loss-risk)
       :by assistant :src t3))
  (add (claim c2 (stores-in type-metadata xattr) :by assistant :src t3)))
"""


class TestMerge(unittest.TestCase):
    def test_shared_proposition_collapses(self):
        terms, nodes, edges, conflicts = merge(
            [graph_from(LOG_A), graph_from(LOG_B)])
        claims = [n for n in nodes.values() if n["frame"] == "claim"]
        risk = [n for n in claims
                if "total-loss-risk" in str(n["payload"])]
        self.assertEqual(len(risk), 1)                 # deduped
        self.assertEqual(risk[0]["src"], ["t1", "t3"])  # provenance unioned
        self.assertEqual(len(nodes), 3)                # c-risk, k1, c-xattr
        self.assertEqual(conflicts, [])

    def test_terms_union(self):
        terms, *_ = merge([graph_from(LOG_A), graph_from(LOG_B)])
        self.assertEqual(set(terms), {"fuse-vfs", "xattr"})

    def test_edges_rewire_to_merged_ids(self):
        terms, nodes, edges, _ = merge(
            [graph_from(LOG_A), graph_from(LOG_B)])
        self.assertEqual(len(edges), 1)
        et, a, b = edges[0]
        self.assertEqual(et, "motivates")
        self.assertIn(a, nodes)
        self.assertIn(b, nodes)

    def test_status_conflict_surfaces_as_question(self):
        a = graph_from("(delta :turn 1 "
                       "(add (question q1 (is x y) :status open "
                       ":by user :src t1)))")
        b = graph_from("(delta :turn 2 "
                       "(add (question q1 (is x y) :status answered "
                       ":by user :src t2)))")
        terms, nodes, edges, conflicts = merge([a, b])
        self.assertEqual(len(conflicts), 1)
        qid, target, kept, other = conflicts[0]
        self.assertEqual((kept, other), ("open", "answered"))
        self.assertIn(("about", qid, target), edges)
        self.assertEqual(nodes[target]["status"], "open")  # first-seen kept

    def test_node_ref_args_join_across_serials(self):
        # same decision under different serials; claims referencing it
        # must land on one merged decision id
        a = graph_from("""
        (delta :turn 1
          (add (decision d1 (implement s t) :by user :src t1))
          (add (claim c1 (achieves d1 goal) :by user :src t1)))
        """)
        b = graph_from("""
        (delta :turn 4
          (add (decision d9 (implement s t) :by user :src t4))
          (add (claim c7 (achieves d9 goal) :by assistant :src t4)))
        """)
        terms, nodes, edges, _ = merge([a, b])
        self.assertEqual(len(nodes), 2)  # one decision, one claim
        claim = next(n for n in nodes.values() if n["frame"] == "claim")
        dec_id = next(i for i, n in nodes.items()
                      if n["frame"] == "decision")
        self.assertIn(dec_id, claim["payload"])

    def test_rendered_output_folds_clean(self):
        text = render(*merge([graph_from(LOG_A), graph_from(LOG_B)]))
        g = refold(text)
        self.assertEqual(g.errors, [])
        self.assertEqual(len(g.nodes), 3)
        self.assertEqual(len(g.edges), 1)

    def test_conflict_output_folds_clean(self):
        a = graph_from("(delta :turn 1 (add (question q1 (is x y) "
                       ":status open :by user :src t1)))")
        b = graph_from("(delta :turn 2 (add (question q1 (is x y) "
                       ":status answered :by user :src t2)))")
        g = refold(render(*merge([a, b])))
        self.assertEqual(g.errors, [])
        self.assertEqual(len(g.nodes), 2)  # disputed q + reconcile q

    def test_merge_is_idempotent(self):
        text1 = render(*merge([graph_from(LOG_A), graph_from(LOG_B)]))
        g1 = refold(text1)
        text2 = render(*merge([g1, graph_from(LOG_B)]))
        g2 = refold(text2)
        self.assertEqual(len(g2.nodes), len(g1.nodes))
        self.assertEqual(sorted(g2.edges), sorted(g1.edges))

    def test_three_way(self):
        c = graph_from("(delta :turn 1 (add (claim c1 (has p q) "
                       ":by user :src t1)))")
        text = render(*merge([graph_from(LOG_A), graph_from(LOG_B), c]))
        self.assertEqual(len(refold(text).nodes), 4)

    def test_load_rejects_invalid_log(self):
        with tempfile.NamedTemporaryFile("w", suffix=".wno",
                                         delete=False) as f:
            f.write("(delta :turn 1 (add (edge (supports zz yy))))")
            path = f.name
        try:
            with self.assertRaises(SystemExit):
                load(path)
        finally:
            os.unlink(path)


class TestCanonAnchors(unittest.TestCase):
    """Canon anchors join terms across logs with different organic ids."""

    def test_same_canon_merges_terms(self):
        a = graph_from("""
(delta :turn 1
  (term auth-system :gloss "authentication" :canon "Authentication")
  (add (claim c1 (uses app auth-system) :by user :src t1)))
""")
        b = graph_from("""
(delta :turn 1
  (term authn :gloss "auth module" :canon "Authentication")
  (add (claim c1 (uses app authn) :by user :src t1)))
""")
        terms, nodes, edges, _ = merge([a, b])
        # only one term survives (first-seen wins)
        auth_terms = [t for t in terms if "auth" in t]
        self.assertEqual(len(auth_terms), 1)
        self.assertEqual(auth_terms[0], "auth-system")
        # both claims should reference the surviving term id
        for n in nodes.values():
            if n["frame"] == "claim":
                self.assertIn("auth-system", str(n["payload"]))
                self.assertNotIn("authn", str(n["payload"]))

    def test_no_canon_no_join(self):
        a = graph_from("""
(delta :turn 1
  (term auth-system :gloss "authentication")
  (add (claim c1 (uses app auth-system) :by user :src t1)))
""")
        b = graph_from("""
(delta :turn 1
  (term authn :gloss "auth module")
  (add (claim c1 (uses app authn) :by user :src t1)))
""")
        terms, nodes, _, _ = merge([a, b])
        self.assertIn("auth-system", terms)
        self.assertIn("authn", terms)

    def test_canon_join_output_folds_clean(self):
        a = graph_from("""
(delta :turn 1
  (term fuse-layer :gloss "FUSE vfs" :canon "FUSE")
  (add (claim c1 (has fuse-layer mount-point) :by user :src t1)))
""")
        b = graph_from("""
(delta :turn 1
  (term userspace-fs :gloss "userspace filesystem" :canon "FUSE")
  (add (claim c1 (has userspace-fs mount-point) :by user :src t1)))
""")
        text = render(*merge([a, b]))
        g = refold(text)
        self.assertEqual(g.errors, [])


class TestSrcQualification(unittest.TestCase):
    """Merge qualifies :src with :log-id from the meta header."""

    LOG_WITH_ID_A = """
(meta :winnow-version "0.2" :log-id "wno-aaa")
(delta :turn 1
  (add (claim c1 (causes single-file-fs total-loss-risk) :by user :src t1)))
"""

    LOG_WITH_ID_B = """
(meta :winnow-version "0.2" :log-id "wno-bbb")
(delta :turn 1
  (add (claim c1 (causes single-file-fs total-loss-risk) :by user :src t1)))
"""

    LOG_NO_ID = """
(delta :turn 3
  (add (claim c1 (causes single-file-fs total-loss-risk) :by user :src t3)))
"""

    def test_same_node_different_logs_qualified(self):
        a, b = graph_from(self.LOG_WITH_ID_A), graph_from(self.LOG_WITH_ID_B)
        _, nodes, _, _ = merge([a, b])
        claim = next(n for n in nodes.values() if n["frame"] == "claim")
        # src should be qualified with both log ids
        self.assertEqual(claim["src"],
                         [["wno-aaa", "t1"], ["wno-bbb", "t1"]])

    def test_no_log_id_stays_bare(self):
        a, b = graph_from(LOG_A), graph_from(LOG_B)
        _, nodes, _, _ = merge([a, b])
        risk = next(n for n in nodes.values()
                    if "total-loss-risk" in str(n["payload"]))
        # bare provenance union, no qualification
        self.assertEqual(risk["src"], ["t1", "t3"])

    def test_mixed_qualified_and_bare(self):
        a = graph_from(self.LOG_WITH_ID_A)
        b = graph_from(self.LOG_NO_ID)
        _, nodes, _, _ = merge([a, b])
        claim = next(n for n in nodes.values() if n["frame"] == "claim")
        # a's src is qualified, b's stays bare
        self.assertEqual(claim["src"], [["wno-aaa", "t1"], ["t3"]])

    def test_qualified_output_folds_clean(self):
        a, b = graph_from(self.LOG_WITH_ID_A), graph_from(self.LOG_WITH_ID_B)
        text = render(*merge([a, b]))
        g = refold(text)
        self.assertEqual(g.errors, [])

    def test_single_log_with_id_preserves_qualification(self):
        a = graph_from(self.LOG_WITH_ID_A)
        b = graph_from("""
(meta :winnow-version "0.2" :log-id "wno-aaa")
(delta :turn 2
  (add (claim c2 (has p q) :by user :src t2)))
""")
        _, nodes, _, _ = merge([a, b])
        # two nodes from the same log, each with single qualified src
        for n in nodes.values():
            src = n["src"]
            self.assertIsInstance(src, list)
            self.assertEqual(src[0], "wno-aaa")


if __name__ == "__main__":
    unittest.main()
