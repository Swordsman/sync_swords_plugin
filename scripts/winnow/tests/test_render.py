"""Unit tests for render.py — deterministic plain-English winnow rendering."""
import os
import subprocess
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import render  # noqa: E402
from fold import STATUSES, fold  # noqa: E402
from sexpr import parse, tokenize  # noqa: E402


def delta_forms(src):
    return [f for f in parse(tokenize(src))
            if isinstance(f, list) and f and f[0] == "delta"]


def render_all(src, speak=False):
    g = fold(src)
    return render.render_ops(delta_forms(src), g, speak=speak)


class TestFrameAndStatusTemplates(unittest.TestCase):
    def test_every_legal_status_for_every_frame_appears(self):
        ids = {
            "claim": "c1",
            "def": "f1",
            "question": "q1",
            "decision": "d1",
            "constraint": "k1",
            "action": "a1",
            "artifact": "r1",
        }
        for frame, statuses in STATUSES.items():
            for status in statuses:
                nid = ids[frame]
                if frame == "def":
                    op = (f'(add (def {nid} sample-term "a short gloss" '
                          f':status {status} :by user :src t1))')
                elif frame == "artifact":
                    op = (f'(add (artifact {nid} "artifact payload" '
                          f':status {status} :by user :src t1))')
                else:
                    op = (f'(add ({frame} {nid} (rel a b) '
                          f':status {status} :by user :src t1))')
                out = render_all(f"(delta :turn 1 {op})")
                self.assertEqual(len(out), 1, msg=f"{frame} {status}")
                self.assertIn(status, out[0], msg=f"{frame} {status}")
                self.assertIn(render.FRAME_WORD[frame], out[0],
                              msg=f"{frame} {status}")


class TestEdgeTemplates(unittest.TestCase):
    def test_every_edge_type_renders(self):
        base = ("(delta :turn 1 "
                "(add (claim c1 (a b) :by user :src t1)) "
                "(add (claim c2 (c d) :by user :src t1)))")
        edges = ["supports", "contradicts", "supersedes", "refines",
                 "answers", "motivates", "depends", "about"]
        second = ("(delta :turn 2 " +
                  " ".join(f"(add (edge ({et} c1 c2)))" for et in edges) +
                  ")")
        g = fold(base + second)
        forms = delta_forms(base + second)
        out = render.render_ops([forms[1]], g)
        self.assertEqual(len(out), len(edges))
        for et, sentence in zip(edges, out):
            self.assertIn(render.EDGE_PHRASES[et], sentence)


class TestAnnotationsAndMutations(unittest.TestCase):
    def test_by_modal_neg_and_low_conf_appear(self):
        src = ("(delta :turn 1 (add (claim c1 (a b) :conf 0.5 :by user "
               ":modal may :neg true :src t1)))")
        out = render_all(src)[0]
        self.assertIn("by user", out)
        self.assertIn("modality may", out)
        self.assertIn("negated", out)
        self.assertIn("unsure", out)

    def test_conf_above_threshold_is_not_unsure(self):
        src = ("(delta :turn 1 (add (claim c1 (a b) :conf 0.9 "
               ":by user :src t1)))")
        out = render_all(src)[0]
        self.assertNotIn("unsure", out)

    def test_update_supersede_merge_del_render(self):
        src = """
(delta :turn 1
  (add (claim c1 (a b) :by user :src t1))
  (add (claim c2 (c d) :by user :src t1)))
(delta :turn 2 (update c1 :status corrected :conf 0.4))
(delta :turn 3 (supersede c2 c1 :conf 0.7))
(delta :turn 4 (merge c1 c2))
(delta :turn 5 (del c2))
"""
        out = render_all(src)
        self.assertIn("is now corrected", out[2])
        self.assertIn("unsure", out[2])
        self.assertIn("supersedes", out[3])
        self.assertNotIn("unsure", out[3])
        self.assertIn("is merged into", out[4])
        self.assertIn("a b", out[4])
        self.assertIn("c1", out[4])
        self.assertIn("is deleted", out[5])
        self.assertIn("c2", out[5])


class TestUnknownForms(unittest.TestCase):
    def test_unknown_op_is_unreadable(self):
        src = "(delta :turn 1 (mystery op x))"
        out = render_all(src)
        self.assertEqual(out[0], "Unreadable op: (mystery op x)")


class TestSpeakMode(unittest.TestCase):
    def test_speak_contains_no_parentheses_brackets_or_ids(self):
        src = """
(delta :turn 1
  (term single-file-fs :gloss "entire filesystem serialized into one container file")
  (add (claim c1 (causes single-file-fs total-loss-risk) :conf 0.5 :by user :src t1))
  (add (constraint k1 (has target-fs per-node-storage) :strength hard :by user :src t1))
  (add (edge (motivates c1 k1))))
(delta :turn 2 (update c1 :status corrected :neg true))
"""
        g = fold(src)
        text = render.render_deltas(delta_forms(src), g, speak=True)
        for ch in ("(", ")", "[", "]"):
            self.assertNotIn(ch, text)
        self.assertNotIn("c1", text)

    def test_speak_flag_via_cli(self):
        r = subprocess.run(
            [sys.executable, "render.py",
             os.path.join(ROOT, "demo-deltas.wno"), "--speak"],
            capture_output=True, text=True, cwd=ROOT, timeout=60)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertNotIn("(", r.stdout)
        self.assertNotIn("[", r.stdout)


class TestDemo(unittest.TestCase):
    def test_demo_log_renders_without_unreadable(self):
        path = os.path.join(ROOT, "demo-deltas.wno")
        with open(path) as f:
            text = f.read()
        g = fold(text)
        forms = delta_forms(text)
        out = render.render_ops(forms, g)
        self.assertGreater(len(out), 0)
        self.assertFalse(any("Unreadable" in line for line in out))
        view = render.render_deltas(forms, g)
        for turn in ("2", "4", "6", "7", "8"):
            self.assertIn(f"Turn {turn}", view)


class TestFrontierView(unittest.TestCase):
    def test_frontier_view_groups_four_headings(self):
        src = """
(delta :turn 1
  (add (question q1 (design target-fs) :status open :by user :src t1))
  (add (decision d1 (implement target-fs fuse-vfs) :status proposed :by assistant :src t1))
  (add (constraint k1 (has target-fs json-semantics) :strength hard :by user :src t1))
  (add (action a1 (build fuse-vfs) :status todo :by assistant :src t1)))
"""
        text = render.render_frontier_text(fold(src))
        for heading in ("Open questions", "Proposed decisions",
                        "Live constraints", "Actions"):
            self.assertIn(heading, text)
        self.assertIn("is open", text)
        self.assertIn("is proposed", text)
        self.assertIn("is live", text)
        self.assertIn("is todo", text)


if __name__ == "__main__":
    unittest.main()