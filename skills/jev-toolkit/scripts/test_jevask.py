import unittest
from unittest import mock

import jevask
import scout


class Pieces(unittest.TestCase):
    def test_numbering_is_one_based_and_skips_blank_lines_but_keeps_their_numbers(self):
        self.assertEqual(jevask.number_lines("a\n\nb"), {"L1": "a", "L3": "b"})

    def test_references_expand_to_quoted_line_text(self):
        lines = {"L44": "does", "L77": "a ball"}
        self.assertEqual(jevask.expand("[44] [77] [9]?", lines), '"does" (line 44) "a ball" (line 77) [9]?')

    def test_rounds_follow_dependencies_and_survive_cycles(self):
        self.assertEqual(jevask.rounds({"N1": set(), "N2": {"N1"}, "N3": {"N2"}}), [["N1"], ["N2"], ["N3"]])
        self.assertEqual(jevask.rounds({"N1": {"N2"}, "N2": {"N1"}}), [["N1", "N2"]])

    def test_blocks_cover_every_line(self):
        lines = {f"L{n}": "x" for n in range(1, 26)}
        self.assertEqual(jevask.blocks(lines), {"B1": "lines 1-10", "B2": "lines 11-20", "B3": "lines 21-25"})


class Flow(unittest.TestCase):
    def fake(self, kinds, deps=()):
        calls = []

        def ask_jev(state, questions, **_):
            calls.append((state, questions))
            answers = {}
            for name, question in questions.items():
                if name.startswith("type_"):
                    answers[name] = {"choice": kinds[name[5:]], "confidence": 1.0}
                elif name.startswith("dep_"):
                    answers[name] = {"noul": 1.0 if tuple(name[4:].split("_")) in deps else 0.0}
                elif question["type"] == "choice":
                    first = next(iter(question["criteria"]))
                    answers[name] = {"choice": first, "confidence": 0.9}
                elif question["type"] == "score":
                    answers[name] = {"score": 3.2, "confidence": 0.8}
                else:
                    answers[name] = {"noul": 0.55}
            return {"answers": answers}
        return calls, ask_jev

    def test_independent_needs_share_one_answer_call_after_one_planning_call(self):
        calls, fake = self.fake({"N1": "noul", "N2": "score", "N3": "choice"})
        with mock.patch.object(scout, "ask_jev", fake):
            results = jevask.ask(["Is it red?", "How round is it?", "Which line names it?"], text="ball\nred")
        self.assertEqual(len(calls), 2)
        self.assertTrue(results["Is it red?"]["doubtful"])
        self.assertEqual(results["How round is it?"]["answer"], "mostly (3.2 of 4)")
        self.assertEqual(results["Which line names it?"]["answer"], "line 1: ball")

    def test_dependent_need_runs_later_and_sees_the_earlier_answer(self):
        calls, fake = self.fake({"N1": "choice", "N2": "noul"}, deps={("N2", "N1")})
        with mock.patch.object(scout, "ask_jev", fake):
            results = jevask.ask(["Which line names it?", "Is that thing round?"], text="ball")
        self.assertEqual(len(calls), 3)
        self.assertIn("Which line names it?", calls[2][0]["earlier_answers"])
        self.assertEqual(results["Is that thing round?"]["round"], 2)

    def test_long_documents_narrow_to_a_block_then_a_line(self):
        calls, fake = self.fake({"N1": "choice"})
        text = "\n".join(f"line {n}" for n in range(1, 301))
        with mock.patch.object(scout, "ask_jev", fake):
            results = jevask.ask(["Which line says 5?"], text=text)
        self.assertEqual(len(calls), 3)
        self.assertTrue(set(calls[2][1]["N1"]["criteria"]) <= {f"L{n}" for n in range(1, 301)})
        self.assertLessEqual(len(calls[2][1]["N1"]["criteria"]), jevask.BLOCK)
        self.assertTrue(results["Which line says 5?"]["answer"].startswith("line "))


if __name__ == "__main__":
    unittest.main()
