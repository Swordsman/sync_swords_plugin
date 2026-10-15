"""Unit tests for basis.py — premise chains, labels and blast radius."""
import os
import subprocess
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import basis  # noqa: E402
from fold import fold  # noqa: E402

# c3 <- c2 <- c1: c1 needs c2, c2 needs c3 ("assuming c3, infer c2, ...")
CHAIN = """
(delta :turn 1
  (add (claim c3 (has disk space) :by user :src t1))
  (add (claim c2 (fits archive disk) :by assistant :src t1))
  (add (claim c1 (can keep raw-logs) :by assistant :src t1))
  (add (edge (depends c2 c3)))
  (add (edge (depends c1 c2))))
"""


def labels(src):
    g = fold(src)
    return {nid: b.label for nid, b in basis.analyze(g).items()}, g


class TestLabels(unittest.TestCase):
    def test_chain_holds_and_lists_what_it_rests_on(self):
        lab, g = labels(CHAIN)
        self.assertEqual(lab, {"c1": "holds", "c2": "holds", "c3": "holds"})
        self.assertEqual(basis.analyze(g)["c1"].rests_on, {"c3"})

    def test_correcting_a_premise_cascades_with_the_chain(self):
        lab, g = labels(CHAIN + "(delta :turn 2 (update c3 :status corrected))")
        self.assertEqual(lab["c1"], "undermined")
        path, _, why = basis.analyze(g)["c1"].causes["c3"]
        self.assertEqual(path, ("c1", "c2", "c3"))
        self.assertIn("corrected (last changed t2)", why)
        self.assertNotIn("corrected", g.nodes["c1"]["status"])   # the log is untouched

    def test_hedged_premise_is_pending(self):
        lab, _ = labels(CHAIN.replace("(has disk space) :by", "(has disk space) :modal may :by"))
        self.assertEqual(lab["c1"], "pending")

    def test_unsettled_premises_are_pending(self):
        src = """
        (delta :turn 1
          (add (decision d1 (use xz) :by user :src t1))
          (add (question q1 (is xz fast) :by user :src t1))
          (add (claim c1 (stays small archive) :by user :src t1))
          (add (claim c2 (answers-fast xz) :by user :src t1))
          (add (edge (depends c1 d1)))
          (add (edge (depends c2 q1))))
        """
        lab, _ = labels(src)
        self.assertEqual((lab["c1"], lab["c2"]), ("pending", "pending"))
        lab, _ = labels(src + "(delta :turn 2 (update d1 :status frozen) (update q1 :status answered))")
        self.assertEqual((lab["c1"], lab["c2"]), ("holds", "holds"))

    def test_superseded_premise_names_its_replacement(self):
        lab, g = labels(CHAIN + """
        (delta :turn 2
          (add (claim c4 (lacks disk space) :by user :src t2))
          (supersede c4 c3))""")
        self.assertEqual(lab["c1"], "undermined")
        self.assertIn("replaced by c4", basis.analyze(g)["c1"].causes["c3"][2])

    def test_live_contradiction_makes_dependents_pending(self):
        disputed = CHAIN + """
        (delta :turn 2
          (add (claim c5 (lacks disk space) :by user :src t2))
          (add (edge (contradicts c5 c3))))"""
        lab, _ = labels(disputed)
        self.assertEqual(lab["c1"], "pending")
        lab, _ = labels(disputed + "(delta :turn 3 (update c5 :status retracted))")
        self.assertEqual(lab["c1"], "holds")             # the challenge fell

    def test_evidence_does_not_cascade(self):
        lab, _ = labels("""
        (delta :turn 1
          (add (claim c1 (a b) :by user :src t1))
          (add (claim c2 (c d) :by user :src t1))
          (add (edge (supports c1 c2))))
        (delta :turn 2 (update c1 :status retracted))""")
        self.assertEqual(lab["c2"], "holds")

    def test_one_surviving_reason_is_enough(self):
        src = """
        (delta :turn 1
          (add (claim c1 (a b) :by user :src t1))
          (add (claim c2 (c d) :by user :src t1))
          (add (decision d1 (do e) :status frozen :by user :src t1))
          (add (edge (motivates c1 d1)))
          (add (edge (motivates c2 d1))))
        """
        lab, _ = labels(src + "(delta :turn 2 (update c1 :status retracted))")
        self.assertEqual(lab["d1"], "holds")             # c2 still a reason
        lab, _ = labels(src + "(delta :turn 2 (update c1 :status retracted)"
                              " (update c2 :status retracted))")
        self.assertEqual(lab["d1"], "undermined")        # no reason left

    def test_every_premise_is_needed(self):
        lab, _ = labels("""
        (delta :turn 1
          (add (claim c1 (a b) :by user :src t1))
          (add (claim c2 (c d) :by user :src t1))
          (add (claim c3 (e f) :by user :src t1))
          (add (edge (depends c3 c1)))
          (add (edge (depends c3 c2))))
        (delta :turn 2 (update c2 :status corrected))""")
        self.assertEqual(lab["c3"], "undermined")

    def test_cycle_terminates_as_pending(self):
        lab, _ = labels("""
        (delta :turn 1
          (add (claim c1 (a b) :by user :src t1))
          (add (claim c2 (c d) :by user :src t1))
          (add (edge (depends c1 c2)))
          (add (edge (depends c2 c1))))""")
        self.assertEqual((lab["c1"], lab["c2"]), ("pending", "pending"))

    def test_diamond_stays_fast(self):
        # 30 layers of two nodes, each needing both below: exponential without memo
        lines = ["(delta :turn 1", "(add (claim c0 (base x) :by user :src t1))"]
        prev = ["c0"]
        n = 1
        for _ in range(30):
            cur = [f"c{n}", f"c{n + 1}"]
            n += 2
            for c in cur:
                lines.append(f"(add (claim {c} (layer {c}) :by user :src t1))")
                lines += [f"(add (edge (depends {c} {p})))" for p in prev]
            prev = cur
        g = fold("\n".join(lines) + ")")
        self.assertEqual(basis.analyze(g)[prev[0]].rests_on, {"c0"})


class TestViews(unittest.TestCase):
    def test_rests_on_is_the_blast_radius(self):
        g = fold(CHAIN + """
        (delta :turn 2
          (add (decision d1 (keep raw-logs) :by user :src t2))
          (add (edge (motivates c1 d1))))""")
        self.assertEqual(basis.rests_on_closure(g, "c3"), {"c2", "c1", "d1"})
        self.assertEqual(basis.rests_on_closure(g, "d1"), set())

    def test_render_counts_and_undermined_filter(self):
        g = fold(CHAIN + "(delta :turn 2 (update c3 :status corrected))")
        out = basis.render(g)
        self.assertIn("2 nodes with grounds: 0 hold, 0 pending, 2 undermined", out)
        self.assertIn("; c1 -> c2 -> c3: corrected", out)
        self.assertNotIn("(claim c3", basis.render(g, only="undermined"))

    def test_cli_via_wno(self):
        r = subprocess.run([sys.executable, "wno.py", "basis",
                            os.path.join(ROOT, "demo-deltas.wno"), "--node", "d2"],
                           capture_output=True, text=True, cwd=ROOT, timeout=60)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("undermined", r.stdout)
        self.assertIn("replaced by d3", r.stdout)


if __name__ == "__main__":
    unittest.main()
