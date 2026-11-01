"""Unit tests for typed relation signatures (:sig)."""
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import merge  # noqa: E402
from fold import (Lit, anns, arg_sort, fold, parse_sig, sig_misfit,
                  sx)  # noqa: E402
from winnow import Normalizer, extract_forms  # noqa: E402


def norm(src, text):
    return Normalizer(fold(src)).normalize(extract_forms(text))


def lines(ops):
    return [sx(o) for o in ops]


class TestSigParse(unittest.TestCase):
    def test_valid_sigs(self):
        self.assertEqual(parse_sig(["CAUSE", "EFFECT"]),
                         [("CAUSE", None), ("EFFECT", None)])
        self.assertEqual(parse_sig(["THING", "KIND:termid"]),
                         [("THING", None),
                          ("KIND", frozenset({"termid"}))])
        self.assertEqual(parse_sig(["OWNER:id|termid",
                                    "PAYLOAD:string|number"]),
                         [("OWNER", frozenset({"id", "termid"})),
                          ("PAYLOAD", frozenset({"string", "number"}))])

    def test_malformed_sigs(self):
        for value in (["cause"], ["A:node"], ["A", "A"], [],
                      [Lit("CAUSE")], ["A", ["B"]]):
            with self.assertRaises(ValueError, msg=value):
                parse_sig(value)

    def test_arg_sort(self):
        self.assertEqual(arg_sort(Lit("70km")), "string")
        self.assertEqual(arg_sort("3"), "number")
        self.assertEqual(arg_sort(3), "number")
        self.assertEqual(arg_sort("c12"), "id")
        self.assertEqual(arg_sort("x3", provisional=True), "id")
        self.assertEqual(arg_sort("fuse-vfs"), "termid")
        self.assertIsNone(arg_sort(["nested"]))

    def test_misfit_reason_names_slot(self):
        slots = parse_sig(["THING", "KIND:termid"])
        why = sig_misfit("fails", ["r1", Lit("timed out")], slots)
        self.assertIn("slot 2 KIND", why)
        self.assertIn("termid", why)


class TestFoldValidation(unittest.TestCase):
    def test_log_without_sig_unchanged(self):
        g = fold("(delta :turn 1 (add (claim c1 (has a b) :by user :src t1)))")
        self.assertEqual(g.validate(), [])
        self.assertFalse(any("sig" in w for w in g.warnings))

    def test_misfit_warns_never_errors(self):
        g = fold("""(delta :turn 1
          (term causes :gloss "g" :sig (CAUSE EFFECT))
          (add (claim c1 (causes a b c) :by user :src t1)))""")
        self.assertEqual(g.validate(), [])
        self.assertIn("c1", g.nodes)
        self.assertTrue(any(w.startswith("sig mismatch c1:")
                            for w in g.warnings))

    def test_sig_checked_against_final_registry(self):
        g = fold("""(delta :turn 1
          (term causes :gloss "g")
          (add (claim c1 (causes a b c) :by user :src t1)))
          (delta :turn 2
            (term causes :gloss "g" :sig (CAUSE EFFECT)))""")
        g.validate()
        self.assertTrue(any(w.startswith("sig mismatch c1:")
                            for w in g.warnings))

    def test_malformed_sig_warns_and_untyped(self):
        g = fold("""(delta :turn 1
          (term r :gloss "g" :sig (cause))
          (add (claim c1 (r a b) :by user :src t1)))""")
        g.validate()
        self.assertTrue(any(w.startswith("malformed :sig on term r")
                            for w in g.warnings))
        self.assertFalse(any("sig mismatch" in w for w in g.warnings))

    def test_validate_twice_no_duplicates(self):
        g = fold("""(delta :turn 1
          (term causes :gloss "g" :sig (CAUSE EFFECT))
          (add (claim c1 (causes a b c) :by user :src t1)))""")
        g.validate()
        g.validate()
        self.assertEqual(sum(w.startswith("sig mismatch c1:")
                             for w in g.warnings), 1)

    def test_other_semantic_rep_skips(self):
        g = fold("""(meta :semantic-rep "other-mode")
          (delta :turn 1
            (term causes :gloss "g" :sig (CAUSE EFFECT))
            (add (claim c1 (causes a b c) :by user :src t1)))""")
        g.validate()
        self.assertFalse(any("sig" in w for w in g.warnings))

    def test_snapshot_keeps_sig(self):
        src = ("(delta :turn 1 "
               "(term fails :gloss \"bad thing\" "
               ":sig (THING KIND:termid)))")
        g = fold(src)
        self.assertEqual(
            g.snapshot(),
            '(term fails :gloss "bad thing" :sig (THING KIND:termid))')


class TestNormalizerSig(unittest.TestCase):
    CAUSES = "(delta :turn 0 (term causes :gloss \"g\" :sig (CAUSE EFFECT)))"
    FAILS = "(delta :turn 0 (term fails :gloss \"f\" :sig (THING KIND:termid)))"

    def test_rejects_arity(self):
        ops, rej = norm(self.CAUSES,
                        "(add (claim x1 (causes a b c) :by user :src t1))")
        self.assertEqual(ops, [])
        self.assertTrue(any(r.startswith("sig mismatch") for r in rej))

    def test_rejects_sort_no_swap(self):
        ops, rej = norm(self.FAILS,
                        '(add (claim x1 (fails r1 "timed out") '
                        ':by user :src t1))')
        self.assertEqual(ops, [])
        self.assertTrue(any(r.startswith("sig mismatch") for r in rej))

    def test_swaps_binary_when_only_swap_fits(self):
        n = Normalizer(fold(self.FAILS))
        ops, rej = n.normalize(extract_forms(
            "(add (claim x1 (fails timeout r1) :by user :src t1))"))
        self.assertEqual(rej, [])
        self.assertEqual(lines(ops),
                         ["(add (claim c1 (fails r1 timeout) "
                          ":by user :src t1))"])
        self.assertEqual(len(n.coercions), 1)

    def test_swap_then_dedup(self):
        src = self.FAILS[:-1] + \
            " (add (claim c1 (fails r1 timeout) :by user :src t0)))"
        ops, rej = norm(src,
                        "(add (claim x1 (fails timeout r1) "
                        ":by user :src t1))")
        self.assertEqual((ops, rej), ([], []))

    def test_no_swap_when_original_fits(self):
        n = Normalizer(fold(self.CAUSES))
        ops, rej = n.normalize(extract_forms(
            "(add (claim x1 (causes b a) :by user :src t1))"))
        self.assertEqual(rej, [])
        self.assertEqual(sx(ops[0]),
                         "(add (claim c1 (causes b a) :by user :src t1))")
        self.assertEqual(n.coercions, [])

    def test_untyped_relation_unchanged(self):
        ops, rej = norm("",
                        "(add (claim x1 (r a) :by user :src t1))"
                        "(add (claim x2 (r a b) :by user :src t1))"
                        '(add (claim x3 (r a "b") :by user :src t1))')
        self.assertEqual(rej, [])
        self.assertEqual(len(ops), 3)

    def test_term_redecl_adds_sig(self):
        src = '(delta :turn 0 (term widget-of :gloss "g" :aka ("saved to")))'
        ops, rej = norm(src, "(term widget-of :sig (THING STORE))")
        self.assertEqual(rej, [])
        self.assertEqual(sx(ops[0]),
                         '(term widget-of :gloss "g" :aka ("saved to") '
                         ":sig (THING STORE))")

    def test_term_redecl_conflict_rejected(self):
        src = "(delta :turn 0 (term widget-of :gloss \"g\" :sig (CAUSE EFFECT)))"
        ops, rej = norm(src, "(term widget-of :sig (EFFECT CAUSE))")
        self.assertEqual(ops, [])
        self.assertTrue(any(r.startswith("sig conflict for widget-of")
                            for r in rej))

    def test_malformed_sig_on_new_term(self):
        ops, rej = norm("",
                        '(term widget-of :gloss "g" :sig (part whole))')
        self.assertEqual(sx(ops[0]), '(term widget-of :gloss "g")')
        self.assertTrue(any(r.startswith("malformed :sig on term widget-of")
                            for r in rej))

    def test_seed_sig_first_use(self):
        ops, rej = norm("",
                        "(add (claim x1 (fails r1 timeout) "
                        ":by user :src t1))")
        self.assertEqual(rej, [])
        self.assertTrue(sx(ops[0]).startswith("(term fails"))
        self.assertIn(":sig (THING KIND:termid)", sx(ops[0]))


class TestMergeSig(unittest.TestCase):
    def test_adopt_sig(self):
        a = fold("(delta :turn 0 (term causes :gloss \"g\"))")
        b = fold("(delta :turn 0 (term causes :gloss \"g\" :sig (CAUSE EFFECT)))")
        terms, _, _, _ = merge.merge([a, b])
        self.assertEqual(parse_sig(anns(list(terms["causes"]))["sig"]),
                         parse_sig(["CAUSE", "EFFECT"]))
        self.assertNotIn("sig", anns(list(a.terms["causes"])))

    def test_conflict_first_wins(self):
        a = fold("(delta :turn 0 (term causes :gloss \"g\" :sig (CAUSE EFFECT)))")
        b = fold("(delta :turn 0 (term causes :gloss \"g\" :sig (EFFECT CAUSE)))")
        conflicts = []
        terms, _, _, _ = merge.merge([a, b], conflicts)
        self.assertEqual(parse_sig(anns(list(terms["causes"]))["sig"]),
                         parse_sig(["CAUSE", "EFFECT"]))
        self.assertEqual(len(conflicts), 1)
        self.assertEqual(conflicts[0][0], "causes")

    def test_canon_join_conflict(self):
        a = fold("(delta :turn 0 (term tid-a :canon \"X\" :sig (CAUSE EFFECT)))")
        b = fold("(delta :turn 0 (term tid-b :canon \"X\" :sig (EFFECT CAUSE)))")
        conflicts = []
        terms, _, _, _ = merge.merge([a, b], conflicts)
        self.assertIn("tid-a", terms)
        self.assertTrue(any(t == "tid-a" for t, _, _, _ in conflicts))


if __name__ == "__main__":
    unittest.main()
