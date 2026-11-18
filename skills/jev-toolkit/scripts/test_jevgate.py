import unittest

import jevgate


def _choice(choice, keys):
    return {
        "type": "choice",
        "choice": choice,
        "confidence": 1.0,
        "probabilities": {key: (1.0 if key == choice else 0.0) for key in keys},
    }


def _noul(value):
    return {"type": "noul", "noul": value}


class GatedChoices(unittest.TestCase):
    def test_one_request_per_batch(self):
        log = []

        def ask(state, questions, followup=False):
            log.append((state, questions, followup))
            answers = {}
            for name, question in questions.items():
                keys = list(question.get("criteria", {}))
                if name.endswith("__gate"):
                    answers[name] = _choice("listed", keys)
                else:
                    answers[name] = _choice(keys[0], keys)
            return {"answers": answers}

        calls = [({"text": f"text {index}"}, f"Question {index}?", ["a", "b", "c"]) for index in range(3)]
        results = jevgate.gated_choices(calls, ask=ask)
        self.assertEqual(len(log), 1)
        self.assertEqual(len(results), 3)
        self.assertTrue(all(result["kind"] == "listed" for result in results))

    def test_shuffled_order_is_mapped_back_to_the_callers_order(self):
        captured = []

        def ask(state, questions, followup=False):
            captured.append(questions)
            answers = {}
            for name, question in questions.items():
                keys = list(question.get("criteria", {}))
                if name.endswith("__gate"):
                    answers[name] = _choice("listed", keys)
                else:
                    answers[name] = _choice(keys[-1], keys)
            return {"answers": answers}

        options = ["alpha", "beta", "gamma", "delta", "epsilon"]
        result = jevgate.gated_choice({"text": "source"}, "Which option?", options, ask=ask)
        pick_question = captured[0]["i0000__pick"]
        picked = list(pick_question["criteria"])[-1]
        self.assertEqual(result["choice"], picked)
        self.assertEqual(result["index"], options.index(picked))
        self.assertEqual(list(result["gate_probs"]), list(jevgate.GATE))
        self.assertEqual(list(result["choice_probs"]), options)
        self.assertEqual(result["choice_probs"][picked], 1.0)

    def test_gate_probabilities_are_returned_in_gate_order(self):
        def ask(state, questions, followup=False):
            answers = {}
            for name, question in questions.items():
                keys = list(question.get("criteria", {}))
                if name.endswith("__gate"):
                    probabilities = {key: 0.1 for key in keys}
                    probabilities["unlisted"] = 0.7
                    answers[name] = {"choice": "unlisted", "probabilities": probabilities}
                else:
                    answers[name] = _choice(keys[0], keys)
            return {"answers": answers}

        result = jevgate.gated_choice({"text": "source"}, "Which option?", ["a", "b"], ask=ask)
        self.assertEqual(list(result["gate_probs"]), list(jevgate.GATE))
        self.assertAlmostEqual(result["gate_probs"]["unlisted"], 0.7)
        self.assertEqual(result["kind"], "unlisted")

    def test_choice_is_none_unless_the_gate_says_listed(self):
        for kind in ("unlisted", "unknown", "irrelevant"):
            def ask(state, questions, followup=False, kind=kind):
                answers = {}
                for name, question in questions.items():
                    keys = list(question.get("criteria", {}))
                    if name.endswith("__gate"):
                        answers[name] = _choice(kind, keys)
                    else:
                        answers[name] = _choice(keys[0], keys)
                return {"answers": answers}

            result = jevgate.gated_choice({"text": "source"}, "Which option?", ["a", "b"], ask=ask)
            self.assertEqual(result["kind"], kind)
            self.assertIsNone(result["choice"])
            self.assertIsNone(result["index"])

    def test_listed_choice_is_returned(self):
        def ask(state, questions, followup=False):
            answers = {}
            for name, question in questions.items():
                keys = list(question.get("criteria", {}))
                if name.endswith("__gate"):
                    answers[name] = _choice("listed", keys)
                else:
                    answers[name] = _choice(keys[0], keys)
            return {"answers": answers}

        result = jevgate.gated_choice({"text": "source"}, "Which option?", ["a", "b"], ask=ask)
        self.assertEqual(result["kind"], "listed")
        self.assertIn(result["choice"], ["a", "b"])
        self.assertEqual(result["choice"], ["a", "b"][result["index"]])

    def test_shuffle_is_deterministic_for_the_same_call(self):
        log = []

        def ask(state, questions, followup=False):
            log.append(questions)
            answers = {}
            for name, question in questions.items():
                keys = list(question.get("criteria", {}))
                if name.endswith("__gate"):
                    answers[name] = _choice("listed", keys)
                else:
                    answers[name] = _choice(keys[0], keys)
            return {"answers": answers}

        call = ({"text": "same"}, "Same question?", ["a", "b", "c"])
        jevgate.gated_choices([call], ask=ask)
        jevgate.gated_choices([call], ask=ask)
        self.assertEqual(list(log[0]["i0000__gate"]["criteria"]), list(log[1]["i0000__gate"]["criteria"]))
        self.assertEqual(list(log[0]["i0000__pick"]["criteria"]), list(log[1]["i0000__pick"]["criteria"]))


class DoubtProbes(unittest.TestCase):
    @staticmethod
    def _ask(noul, scale_choice, log=None):
        def ask(state, questions, followup=False):
            if log is not None:
                log.append((state, questions, followup))
            answers = {}
            for name, question in questions.items():
                keys = list(question.get("criteria", {}))
                if name.endswith("__noul"):
                    answers[name] = _noul(noul)
                else:
                    answers[name] = _choice(scale_choice, keys)
            return {"answers": answers}
        return ask

    def test_one_request_per_batch(self):
        log = []
        ask = self._ask(0.5, "maybe", log)
        calls = [({"text": f"text {index}"}, f"Question {index}?") for index in range(4)]
        results = jevgate.doubt_probes(calls, ask=ask)
        self.assertEqual(len(log), 1)
        self.assertEqual(len(results), 4)

    def test_scale_probabilities_are_returned_in_scale_order(self):
        def ask(state, questions, followup=False):
            answers = {}
            for name, question in questions.items():
                keys = list(question.get("criteria", {}))
                if name.endswith("__noul"):
                    answers[name] = _noul(0.8)
                else:
                    probabilities = {key: 0.0 for key in keys}
                    probabilities["probably"] = 0.6
                    probabilities["yes"] = 0.4
                    answers[name] = {"choice": "probably", "probabilities": probabilities}
            return {"answers": answers}

        result = jevgate.doubt_probe({"text": "source"}, "Is it valid?", ask=ask)
        self.assertEqual(list(result["scale_probs"]), list(jevgate.SCALE))
        self.assertAlmostEqual(result["scale_probs"]["probably"], 0.6)
        self.assertAlmostEqual(result["scale_probs"]["yes"], 0.4)
        self.assertEqual(result["scale"], "probably")
        self.assertEqual(result["scale_value"], 0.75)

    def test_each_flag(self):
        cases = [
            (0.5, "probably", "reword"),
            (0.5, "maybe", "uncertain"),
            (0.9, "no", "conflict"),
            (0.9, "yes", "ok"),
            (0.1, "probably not", "ok"),
        ]
        for noul, scale, expected in cases:
            result = jevgate.doubt_probe({"text": "source"}, "Question?", ask=self._ask(noul, scale))
            self.assertEqual(result["flag"], expected, (noul, scale))

    def test_shuffle_is_deterministic_for_the_same_call(self):
        log = []
        ask = self._ask(0.5, "maybe", log)
        call = ({"text": "same"}, "Same question?")
        jevgate.doubt_probes([call], ask=ask)
        jevgate.doubt_probes([call], ask=ask)
        first, second = log[0][1], log[1][1]  # the log holds (state, questions, followup)
        scale_key = next(key for key in first if key.endswith("__scale"))
        self.assertEqual(list(first[scale_key]["criteria"]), list(second[scale_key]["criteria"]))


if __name__ == "__main__":
    unittest.main()