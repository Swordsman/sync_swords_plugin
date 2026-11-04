"""Unit tests for trouble.py and the R13 normalizer rules."""
import os
import subprocess
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import basis  # noqa: E402
import trouble  # noqa: E402
from fold import fold, sx  # noqa: E402
from winnow import Normalizer, extract_forms, EXTRACTOR_SYSTEM, \
    NORMALIZER_SYSTEM  # noqa: E402

DEMO = os.path.join(ROOT, "demo-deltas.wno")

UPLOADS = """
(delta :turn 3
  (add (claim c1 (permits base64-text compressed-upload) :by assistant :src t3)))
(delta :turn 5
  (add (claim c2 (excludes claude-docs-upload compressed-upload) :by assistant :src t5)))
(delta :turn 6
  (add (claim c3 (permits claude-docs-upload compressed-upload) :by user :src t6))
  (add (edge (contradicts c3 c2)))
  (update c2 :status corrected)
  (add (claim c4 (fails c2 false-belief) :by user :src t6))
  (add (edge (depends c4 c3)))
  (add (claim c5 (omits c2 c1) :by assistant :src t6))
  (add (claim c6 (causes c5 c4) :by assistant :src t6))
  (add (edge (depends c6 c4)))
  (add (edge (depends c6 c5)))
  (add (artifact r1 "shared doc: measured upload facts" :by assistant :src t6))
  (add (edge (motivates c4 r1))))
"""


def view(src):
    g = fold(src)
    return g, basis.analyze(g)


class TestFailures(unittest.TestCase):
    def test_old_log_has_symptoms_only(self):
        g = fold(open(DEMO).read())
        self.assertEqual(trouble.failure_ids(g), [])
        out = trouble.render(g)
        self.assertIn("; none recorded", out)
        self.assertIn("(claim c17 (requires grid-membership incident-link)) "
                      "corrected, challenged by c19 (last changed t8)", out)

    def test_facets_of_a_recorded_failure(self):
        g, lab = view(UPLOADS)
        self.assertEqual(trouble.failure_ids(g), ["c4"])
        fx = trouble.facets(g, "c4", lab)
        self.assertEqual(fx["diagnosis"], ("holds", ["c6"]))
        self.assertEqual(fx["repair"], ("holds", ["c3"]))   # derived: c3 replaced c2
        self.assertEqual(fx["guard"], ("holds", ["r1"]))
        self.assertIn("reported t6 by user; c2 from t5 by assistant",
                      trouble.render(g))

    def test_a_fallen_diagnosis_leaves_the_failure_standing(self):
        g, lab = view(UPLOADS + "(delta :turn 9 (update c5 :status corrected))")
        self.assertEqual(lab["c4"].label, "holds")
        self.assertEqual(trouble.facets(g, "c4", lab)["diagnosis"][0], "undermined")
        self.assertEqual(trouble.facets(g, "c4", lab)["guard"][0], "holds")

    def test_fallen_evidence_undermines_report_and_guard(self):
        g, lab = view(UPLOADS + "(delta :turn 9 (update c3 :status corrected))")
        self.assertEqual(lab["c4"].label, "undermined")
        self.assertEqual(lab["r1"].label, "undermined")

    def test_hedged_and_disputed_diagnoses_are_pending(self):
        g, lab = view(UPLOADS.replace("(causes c5 c4) :by", "(causes c5 c4) :modal may :by"))
        self.assertEqual(trouble.facets(g, "c4", lab)["diagnosis"][0], "pending")
        g, lab = view(UPLOADS + """(delta :turn 9
          (add (claim c7 (excludes c5 c4) :by user :src t9))
          (add (edge (contradicts c7 c6))))""")
        self.assertEqual(trouble.facets(g, "c4", lab)["diagnosis"][0], "pending")
        self.assertIn("disputed by c7", trouble.render(g))

    def test_one_surviving_diagnosis_is_enough(self):
        g, lab = view(UPLOADS + """(delta :turn 9
          (add (claim c7 (causes summary-length c4) :by user :src t9))
          (add (edge (depends c7 c4)))
          (update c6 :status retracted))""")
        self.assertEqual(trouble.facets(g, "c4", lab)["diagnosis"], ("holds", ["c6", "c7"]))

    def test_repair_under_way_then_done(self):
        src = """(delta :turn 9
          (add (claim c1 (fails winnow-normalizer tool-failure) :by user :src t9))
          (add (action a1 (rejects winnow-normalizer dangling-key) :status doing :by assistant :src t9))
          (add (edge (answers a1 c1))))"""
        g, lab = view(src)
        self.assertEqual(trouble.facets(g, "c1", lab)["repair"][0], "pending")
        self.assertIn("(claim c1", trouble.render(g, only_unrepaired=True))
        g, lab = view(src + "(delta :turn 10 (update a1 :status done))")
        self.assertEqual(trouble.facets(g, "c1", lab)["repair"][0], "holds")
        self.assertNotIn("(claim c1", trouble.render(g, only_unrepaired=True))

    def test_retracted_failure_undermines_its_guards(self):
        g, lab = view("""(delta :turn 14
          (add (claim c1 (fails fold miscommunication) :by user :src t14))
          (add (claim c2 (causes word-overload c1) :by assistant :src t14))
          (add (edge (depends c2 c1)))
          (add (constraint k1 (has winnow-docs glossary) :by user :src t14))
          (add (edge (motivates c2 k1))))
          (delta :turn 15 (update c1 :status retracted))""")
        self.assertEqual(lab["k1"].label, "undermined")
        self.assertIn("(claim c1 (fails fold miscommunication))  retracted",
                      trouble.render(g))
        self.assertNotIn("(claim c1", trouble.render(g, only_unrepaired=True))

    def test_kind_filter_order_and_unseeded_kind(self):
        g = fold("""(delta :turn 2
          (add (claim c2 (fails parser odd-kind) :by user :src t2))
          (add (claim c1 (fails fold miscommunication) :by user :src t1)))""")
        out = trouble.render(g)
        self.assertLess(out.index("(claim c1"), out.index("(claim c2"))
        self.assertIn("kind odd-kind is not seeded", out)
        self.assertNotIn("(claim c2", trouble.render(g, kind="miscommunication"))

    def test_symptoms_cover_each_signal(self):
        g = fold("""(delta :turn 1
          (add (decision d1 (use a) :status abandoned :by user :src t1))
          (add (action a1 (run b) :status blocked :by user :src t1))
          (add (action a2 (run c) :status dropped :by user :src t1))
          (add (question q1 (locate old-thing) :status open :by orchestrator :src t1))
          (add (question q2 (reconcile-status c9 live corrected) :status open :by merge-tool :src t0))
          (add (claim c1 (failed deploy-script staging) :by user :src t1))
          (add (claim c2 (has x y) :by user :src t1))
          (add (claim c3 (lacks x y) :by user :src t1))
          (add (edge (contradicts c3 c2))))""")
        out = trouble.render(g)
        for text in ("abandoned", "blocked", "dropped", "honest miss, open",
                     "merge conflict, open", "failure-like relation",
                     "(claim c2 (has x y)) disputed by c3"):
            self.assertIn(text, out)

    def test_view_logs_nothing(self):
        g = fold(UPLOADS)
        before = g.snapshot()
        trouble.render(g)
        self.assertEqual(g.snapshot(), before)

    def test_cli_via_wno(self):
        r = subprocess.run([sys.executable, "wno.py", "trouble", DEMO],
                           capture_output=True, text=True, cwd=ROOT, timeout=60)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("; --- symptoms ---", r.stdout)


class TestR13(unittest.TestCase):
    def norm(self, src, text):
        return Normalizer(fold(src)).normalize(extract_forms(text))

    def test_payload_placeholders_map_including_forward_refs(self):
        ops, rej = self.norm("", """
          (add (claim x2 (causes x3 x1) :by assistant :src t1))
          (add (claim x1 (fails x3 omission) :by user :src t1))
          (add (action x3 (run tests) :status dropped :by assistant :src t1))""")
        self.assertEqual(rej, [])
        lines = [sx(o) for o in ops]
        self.assertIn("(add (claim c1 (causes a1 c2) :by assistant :src t1))", lines)
        self.assertIn("(add (claim c2 (fails a1 omission) :by user :src t1))", lines)
        self.assertIn("(add (edge (depends c1 c2)))", lines)
        self.assertIn("(add (edge (depends c1 a1)))", lines)

    def test_kind_alias_and_seeded_term_declared_once(self):
        ops, _ = self.norm("", '(add (claim x1 (fails c9 wrong-assumption) :by user :src t1))')
        self.assertEqual(ops[0][:2], ["term", "fails"])
        self.assertEqual(ops[1][:2], ["term", "false-belief"])
        self.assertEqual(sx(ops[2]), "(add (claim c1 (fails c9 false-belief) :by user :src t1))")
        g = fold("(delta :turn 1 " + " ".join(sx(o) for o in ops) + ")")
        ops2, _ = Normalizer(g).normalize(extract_forms(
            '(add (claim x1 (fails c8 stale-state) :by user :src t2))'
            '(add (claim x2 (fails c7 misunderstanding) :by user :src t2))'
            '(add (claim x3 (fails c6 false-belief) :by user :src t2))'))
        heads = [o[1] for o in ops2 if o[0] == "term"]
        self.assertEqual(heads, ["outdated-state", "miscommunication"])

    def test_failure_like_head_rewritten_only_with_a_kind(self):
        ops, _ = self.norm("", '(add (claim x1 (failed ds-call crash) :by user :src t1))'
                               '(add (claim x2 (failed deploy-script staging) :by user :src t1))')
        lines = [sx(o) for o in ops]
        self.assertIn("(add (claim c1 (fails ds-call tool-failure) :by user :src t1))", lines)
        self.assertIn("(add (claim c2 (failed deploy-script staging) :by user :src t1))", lines)

    def test_no_speakers_in_failure_payloads(self):
        src = "(delta :turn 1 (add (claim c1 (fails fold miscommunication) :by user :src t1)))"
        ops, rej = self.norm(src, '(add (claim x1 (fails assistant omission) :by user :src t2))'
                                  '(add (claim x2 (causes user c1) :by assistant :src t2))'
                                  '(add (claim x3 (causes word-overload c1) :by hermes :src t2))'
                                  '(add (claim x4 (fails hermes omission) :by user :src t2))')
        self.assertEqual(len(rej), 3)
        self.assertTrue(any("not who" in r for r in rej))
        lines = [sx(o) for o in ops]
        self.assertTrue(lines[0].startswith("(term causes"))
        self.assertEqual(lines[1], "(add (claim c2 (causes word-overload c1) :by hermes :src t2))")
        self.assertEqual(lines[2], "(add (edge (depends c2 c1)))")

    def test_fails_arity(self):
        ops, rej = self.norm("", '(add (claim x1 (fails c1) :by user :src t1))'
                                 '(add (claim x2 (fails c1 omission "x") :by user :src t1))')
        self.assertEqual((ops, len(rej)), ([], 2))
        self.assertIn('(fails c1 omission "x")', rej[1])

    def test_diagnosis_edge_not_doubled(self):
        src = "(delta :turn 1 (add (claim c1 (fails fold miscommunication) :by user :src t1)))"
        ops, _ = self.norm(src, '(add (claim x1 (causes word-overload c1) :by user :src t2))'
                                '(add (edge (depends x1 c1)))')
        self.assertEqual([sx(o) for o in ops].count("(add (edge (depends c2 c1)))"), 1)

    def test_causes_between_ordinary_nodes_untouched(self):
        ops, _ = self.norm("(delta :turn 1 (add (claim c1 (has a b) :by user :src t1)))",
                           '(add (claim x1 (causes c1 risk) :by user :src t2))')
        self.assertEqual(len(ops), 2)
        self.assertEqual(ops[0][:2], ["term", "causes"])
        self.assertEqual(sx(ops[1]), "(add (claim c2 (causes c1 risk) :by user :src t2))")

    def test_motivates_into_a_failure_rejected(self):
        src = """(delta :turn 1 (add (claim c1 (fails fold miscommunication) :by user :src t1))
                 (add (claim c2 (has docs three-meanings) :by user :src t1)))"""
        ops, rej = self.norm(src, '(add (edge (motivates c2 c1)))(add (edge (motivates c1 c2)))')
        self.assertEqual([sx(o) for o in ops], ["(add (edge (motivates c1 c2)))"])
        self.assertIn("(causes c2 c1)", rej[0])

    def test_prompts_carry_the_failure_vocabulary(self):
        self.assertIn("(fails WHAT KIND)", EXTRACTOR_SYSTEM)
        self.assertIn("R13", NORMALIZER_SYSTEM)


if __name__ == "__main__":
    unittest.main()
