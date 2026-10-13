"""Unit tests for winnow.py — transcript parsing, form extraction, and the
procedural normalizer (id assignment, remapping, dedup, rejection), plus a
full replay-mode run of the orchestrator loop."""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from fold import Graph, parse, tokenize, sx  # noqa: E402
from winnow import (Normalizer, extract_forms, parse_transcript,  # noqa: E402
                    render_delta, replay_client, run)


def graph_from(src):
    g = Graph()
    for form in parse(tokenize(src)):
        g.apply(form)
    return g


class TestTranscript(unittest.TestCase):
    def test_parse_blocks(self):
        turns = parse_transcript(
            "[t1 user]\nhello\nworld\n\n[t2 assistant]\nreply\n")
        self.assertEqual(turns, [(1, "user", "hello\nworld"),
                                 (2, "assistant", "reply")])

    def test_ignores_preamble(self):
        turns = parse_transcript("junk before\n[t1 user]\nbody")
        self.assertEqual(len(turns), 1)


class TestExtractForms(unittest.TestCase):
    def test_pulls_ops_from_prose(self):
        text = ('Here are my notes:\n'
                '(add (claim x1 (has a b) :by user :src t1))\n'
                'and also\n(term foo :gloss "bar (baz)")\nDone!')
        forms = extract_forms(text)
        self.assertEqual([f[0] for f in forms], ["add", "term"])

    def test_unwraps_delta_wrapper(self):
        text = '(delta :turn 3 (add (claim x1 (has a b))) (del c9))'
        forms = extract_forms(text)
        self.assertEqual([f[0] for f in forms], ["add", "del"])

    def test_drops_unknown_heads_and_garbage(self):
        forms = extract_forms("(hello world) (add (claim x1 (p q))) (broken")
        self.assertEqual(len(forms), 1)


class TestNormalizer(unittest.TestCase):
    def test_serial_ids_continue_from_graph(self):
        g = graph_from("(delta :turn 1 "
                       "(add (claim c4 (has a b) :by user :src t1)))")
        ops, rejects = Normalizer(g).normalize(
            extract_forms('(add (claim x1 (has c d) :by user :src t2))'))
        self.assertEqual(ops[0][1][1], "c5")
        self.assertEqual(rejects, [])

    def test_placeholder_remap_in_edges(self):
        g = Graph()
        ops, rejects = Normalizer(g).normalize(extract_forms(
            '(add (claim x1 (has a b) :by user :src t1))'
            '(add (question x2 (is c d) :by user :src t1))'
            '(add (edge (answers x1 x2)))'))
        self.assertEqual(sx(ops[2]), "(add (edge (answers c1 q1)))")

    def test_r11_dedup_identical_payload(self):
        g = graph_from("(delta :turn 1 "
                       "(add (claim c1 (has a b) :by user :src t1)))")
        ops, _ = Normalizer(g).normalize(
            extract_forms('(add (claim x1 (has a b) :by user :src t3))'))
        self.assertEqual(ops, [])

    def test_r11_status_change_becomes_update(self):
        g = graph_from("(delta :turn 1 "
                       "(add (question q1 (is a b) :by user :src t1)))")
        ops, _ = Normalizer(g).normalize(extract_forms(
            '(add (question x1 (is a b) :status answered :by user :src t2))'))
        self.assertEqual(sx(ops[0]), "(update q1 :status answered)")

    def test_dedup_then_edge_targets_existing_node(self):
        g = graph_from("(delta :turn 1 "
                       "(add (claim c1 (has a b) :by user :src t1))"
                       "(add (question q1 (is c d) :by user :src t1)))")
        ops, _ = Normalizer(g).normalize(extract_forms(
            '(add (claim x9 (has a b) :by user :src t2))'
            '(add (edge (answers x9 q1)))'))
        self.assertEqual(sx(ops[0]), "(add (edge (answers c1 q1)))")

    def test_reject_unknown_refs(self):
        ops, rejects = Normalizer(Graph()).normalize(
            extract_forms('(update zz :status live)'
                          '(add (edge (supports aa bb)))'))
        self.assertEqual(ops, [])
        self.assertEqual(len(rejects), 2)

    def test_about_targets_term_accepted(self):
        g = graph_from(
            '(delta :turn 1 (term alpha :gloss "a")'
            '(add (question q1 (is x y) :by user :src t1)))')
        ops, rejects = Normalizer(g).normalize(
            extract_forms('(add (edge (about q1 alpha)))'))
        self.assertEqual(rejects, [])
        self.assertEqual(sx(ops[0]), "(add (edge (about q1 alpha)))")

    def test_about_targets_new_term_in_same_batch(self):
        g = graph_from(
            '(delta :turn 1 (add (question q1 (is x y) :by user :src t1)))')
        ops, rejects = Normalizer(g).normalize(
            extract_forms('(term beta :gloss "b")'
                          '(add (edge (about q1 beta)))'))
        self.assertEqual(rejects, [])

    def test_non_about_edge_to_term_rejected(self):
        g = graph_from(
            '(delta :turn 1 (term alpha :gloss "a")'
            '(add (question q1 (is x y) :by user :src t1)))')
        ops, rejects = Normalizer(g).normalize(
            extract_forms('(add (edge (supports q1 alpha)))'))
        self.assertEqual(len(rejects), 1)
        self.assertIn("dangling", rejects[0])

    def test_annotation_order_enforced(self):
        ops, _ = Normalizer(Graph()).normalize(extract_forms(
            '(add (claim x1 (has a b) :src t1 :by user :conf 0.7))'))
        self.assertEqual(
            sx(ops[0]),
            "(add (claim c1 (has a b) :conf 0.7 :by user :src t1))")

    def test_term_dedup_against_registry(self):
        g = graph_from('(delta :turn 1 (term foo :gloss "x"))')
        ops, _ = Normalizer(g).normalize(extract_forms(
            '(term foo :gloss "x")(term bar :gloss "y")'))
        self.assertEqual([op[1] for op in ops], ["bar"])

    def test_term_canon_passthrough(self):
        g = Graph()
        ops, _ = Normalizer(g).normalize(extract_forms(
            '(term dbc :gloss "design by contract" :canon "Design_by_contract")'))
        self.assertEqual(ops[0][0], "term")
        self.assertEqual(ops[0][1], "dbc")
        from fold import anns as _anns
        ta = _anns(ops[0][2:])
        self.assertEqual(ta["canon"], "Design_by_contract")
        self.assertEqual(ta["gloss"], "design by contract")

    def test_term_canon_folds_into_graph(self):
        g = Graph()
        g.apply(parse(tokenize(
            '(delta :turn 1 '
            '(term dbc :gloss "design by contract" :canon "Design_by_contract")'
            '(add (claim c1 (uses project dbc) :by user :src t1)))'))[0])
        ta = dict(zip(g.terms["dbc"][::2], g.terms["dbc"][1::2]))
        # fold.py stores raw tail; anns() extracts it
        from fold import anns as _anns
        parsed = _anns(list(g.terms["dbc"]))
        self.assertEqual(parsed["canon"], "Design_by_contract")

    def test_edge_dedup(self):
        g = graph_from("(delta :turn 1 "
                       "(add (claim c1 (has a b) :by user :src t1))"
                       "(add (claim c2 (has c d) :by user :src t1))"
                       "(add (edge (supports c1 c2))))")
        ops, _ = Normalizer(g).normalize(
            extract_forms('(add (edge (supports c1 c2)))'))
        self.assertEqual(ops, [])


FIXTURE = """\
(add (claim x1 (causes thing risk) :by user :src t1))
(add (question x2 (design system) :by user :src t1))
%%%
(term thing :gloss "the thing under discussion")
(add (claim x1 (causes thing risk) :by user :src t1))
(add (question x2 (design system) :by user :src t1))
%%%
(add (decision y1 (implement system approach) :by assistant :src t2))
(add (edge (answers y1 q1)))
(update q1 :status answered)
(add (claim x1 (causes thing risk) :by user :src t1))
%%%
(add (decision y1 (implement system approach) :by assistant :src t2))
(add (edge (answers y1 q1)))
(update q1 :status answered)
(add (claim x1 (causes thing risk) :by user :src t1))
"""

TRANSCRIPT = """\
[t1 user]
The thing causes risk. How should we design the system?

[t2 assistant]
I'd implement the system with this approach. Also, the thing causes risk.
"""


class TestOrchestratorReplay(unittest.TestCase):
    def test_full_loop(self):
        with tempfile.TemporaryDirectory() as d:
            tp = os.path.join(d, "t.txt")
            fp = os.path.join(d, "f.txt")
            op = os.path.join(d, "out.wno")
            open(tp, "w").write(TRANSCRIPT)
            open(fp, "w").write(FIXTURE)
            g = run(tp, op, replay_client(fp), llm_normalize=True,
                    per_turn=True, verbose=False)
            # t1: c1 + q1; t2: d1 + answers edge + q1 update;
            # restated claim deduped both times
            self.assertEqual(set(g.nodes), {"c1", "q1", "d1"})
            self.assertEqual(g.nodes["q1"]["status"], "answered")
            self.assertIn(("answers", "d1", "q1"), g.edges)
            self.assertEqual(g.validate(), [])
            # log itself must re-fold to the same graph
            g2 = Graph()
            for form in parse(tokenize(open(op).read())):
                if form[0] == "meta":
                    g2.set_meta(form)
                else:
                    g2.apply(form)
            self.assertEqual(set(g2.nodes), set(g.nodes))
            self.assertEqual(sorted(g2.edges), sorted(g.edges))


class TestRenderDelta(unittest.TestCase):
    def test_render_parses_back(self):
        ops = [["term", "foo", ":gloss", "x"],
               ["add", ["claim", "c1", ["has", "a", "b"],
                        ":by", "user", ":src", "t1"]]]
        text = render_delta(4, ops)
        form = parse(tokenize(text))[0]
        self.assertEqual(form[0], "delta")
        self.assertEqual(form[2], "4")


if __name__ == "__main__":
    unittest.main()
