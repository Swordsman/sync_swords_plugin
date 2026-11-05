import io
import json
import os
import unittest
from unittest import mock

import jevbatch
import scout


def recording_ask(log):
    def ask(state, questions, followup=False):
        log.append((state, questions, followup))
        return {"answers": {name: {"type": "noul", "noul": 0.5, "seen": question["instructions"]} for name, question in questions.items()}}
    return ask


class BatchAsk(unittest.TestCase):
    def test_per_item_loop_becomes_one_call_with_shared_state_sent_once(self):
        log = []
        library = {"T0": "alpha", "T1": "beta"}
        calls = [({"source": {"text": f"q{index}"}, "library": library},
                  {"in": scout.noul("Does `library` contain what `source.text` asks?")}) for index in range(50)]
        results = jevbatch.batch_ask(calls, ask=recording_ask(log))
        self.assertEqual(len(log), 1)
        state, questions, _ = log[0]
        self.assertEqual(state["library"], library)
        self.assertEqual(len(state["source"]), 50)
        self.assertEqual(len(questions), 50)
        self.assertEqual(len(results), 50)
        self.assertIn("`source.i0007.text`", results[7]["in"]["seen"])
        self.assertIn("`library`", results[7]["in"]["seen"])  # shared paths untouched

    def test_rewrite_covers_bare_dotted_and_indexed_paths_but_not_prefixes(self):
        text = "`goal` `goal.x` `goal[0]` `goals` `goal_text`"
        self.assertEqual(jevbatch.rewrite_paths(text, "goal", "i0001"),
                         "`goal.i0001` `goal.i0001.x` `goal.i0001[0]` `goals` `goal_text`")

    def test_rewrites_criteria_too(self):
        question = scout.noul("Is `page` relevant?", true="`page` answers it", false="`page` does not")
        rewritten = jevbatch.rewrite_paths(question, "page", "i0002")
        self.assertEqual(rewritten["criteria"]["true"], "`page.i0002` answers it")

    def test_splits_only_at_the_budget_and_keeps_order(self):
        log = []
        calls = [({"item": f"{index} " + "x" * 400}, {"q": scout.noul(f"Is `item` number {index}?")}) for index in range(30)]
        results = jevbatch.batch_ask(calls, ask=recording_ask(log), budget=1500)
        self.assertGreater(len(log), 1)
        self.assertEqual(sum(len(questions) for _, questions, _ in log), 30)
        self.assertTrue(all(jevbatch.estimate_tokens(state) <= 1500 for state, _, _ in log))
        self.assertIn(f"number {29}", results[29]["q"]["seen"])

    def test_single_call_passes_through_unchanged(self):
        log = []
        jevbatch.batch_ask([({"goal": "g"}, {"q": scout.noul("Is `goal` clear?")})], ask=recording_ask(log))
        self.assertEqual(log[0][0], {"goal": "g"})
        self.assertEqual(log[0][1]["i0000__q"]["instructions"], "Is `goal` clear?")

    def test_identical_state_split_by_size_is_sent_as_marked_overflow(self):
        log = []
        calls = [({"library": "same"}, {f"q{index}": scout.noul("Is `library` " + "long " * 60 + f"{index}?")}) for index in range(20)]
        jevbatch.batch_ask(calls, ask=recording_ask(log), budget=800)
        self.assertGreater(len(log), 1)
        self.assertEqual([followup for _, _, followup in log], [False] + [True] * (len(log) - 1))

    def test_overflow_halves_and_retries_until_it_fits(self):
        log = []

        def ask(state, questions, followup=False):
            if len(questions) > 4:
                raise scout.ContextOverflow("max_tokens_exceeded")
            return recording_ask(log)(state, questions, followup)

        calls = [({"item": f"{index}"}, {"q": scout.noul(f"Is `item` number {index}?")}) for index in range(16)]
        results = jevbatch.batch_ask(calls, ask=ask)
        self.assertEqual(len(log), 4)
        self.assertEqual(len(results), 16)
        self.assertIn("number 15", results[15]["q"]["seen"])


class RepeatedStateGuard(unittest.TestCase):
    def setUp(self):
        os.environ["TYPESAFE_API_KEY"] = "test-key"
        scout.SENT_STATES.clear()

    def tearDown(self):
        os.environ.pop("TYPESAFE_API_KEY", None)
        scout.SENT_STATES.clear()

    @staticmethod
    def ok(*_, **__):
        return io.BytesIO(json.dumps({"answers": {}, "usage": {"input_tokens": 1}, "model": "jev-x"}).encode())

    def test_second_send_of_same_state_is_refused_unless_marked_followup(self):
        with mock.patch("urllib.request.urlopen", side_effect=self.ok) as urlopen:
            scout.ask_jev({"library": [1, 2]}, {"a": scout.noul("?")})
            with self.assertRaises(scout.RepeatedState):
                scout.ask_jev({"library": [1, 2]}, {"b": scout.noul("?")})
            scout.ask_jev({"library": [1, 2]}, {"c": scout.noul("?")}, followup=True)
            scout.ask_jev({"library": [1, 2, 3]}, {"d": scout.noul("?")})
        self.assertEqual(urlopen.call_count, 3)


if __name__ == "__main__":
    unittest.main()
