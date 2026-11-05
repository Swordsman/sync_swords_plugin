import datetime as dt
import unittest

import dsx

SPEC = "".join(f"spec line {n}\n" for n in range(3000))
DOC = "".join(f"doc line {n}\n" for n in range(3000))


class Cost(unittest.TestCase):
    def test_measured_pro_call(self):   # run 3: balance moved $0.04 for this usage
        usage = {"prompt_cache_hit_tokens": 28160, "prompt_cache_miss_tokens": 27, "completion_tokens": 18075}
        sunday = dt.datetime(2026, 11, 1, 0, 50, tzinfo=dt.timezone.utc)
        self.assertAlmostEqual(dsx.cost(usage, "deepseek-v4-pro", sunday), 0.0364, places=4)

    def test_peak_only_on_weekdays(self):
        self.assertTrue(dsx.is_peak(dt.datetime(2026, 11, 2, 2)))       # Monday 02:00
        self.assertFalse(dsx.is_peak(dt.datetime(2026, 11, 2, 5)))
        self.assertFalse(dsx.is_peak(dt.datetime(2026, 11, 1, 2)))      # Sunday


class CacheChecks(unittest.TestCase):
    def test_shared_content_first_passes(self):
        checks = dsx.precheck(SPEC + DOC + "task B", [{"prompt": SPEC + DOC + "task A"}])
        self.assertGreater(checks["common_prefix_chars"], len(SPEC))

    def test_expected_hit_follows_persisted_units(self):   # 2026-11-01: s2 Pro got 5376 of ~12k on first reuse
        first_reuse = dsx.precheck(SPEC + "seg two", [{"prompt": SPEC + "seg one"}])
        self.assertEqual(first_reuse["expected_prefix_chars"], 0)              # spec not yet its own unit
        after_two = dsx.precheck(SPEC + "seg three", [{"prompt": SPEC + "seg one"}, {"prompt": SPEC + "seg two"}])
        self.assertGreaterEqual(after_two["expected_prefix_chars"], len(SPEC))  # shared by two requests: persisted
        boundary = dsx.precheck(SPEC + DOC + "task", [{"prompt": SPEC + DOC}])
        self.assertEqual(boundary["expected_prefix_chars"], len(SPEC + DOC))   # whole earlier prompt: persisted

    def test_shared_content_after_instructions_raises(self):   # the mistake made on 2026-11-01
        with self.assertRaises(dsx.MissedCacheError):
            dsx.precheck("task B\n" + DOC, [{"prompt": "task A\n" + DOC}])

    def test_stated_reason_overrides_miss(self):
        dsx.precheck("task B\n" + DOC, [{"prompt": "task A\n" + DOC}], accept_miss="priced: cheaper than reordering")

    def test_unrelated_prompt_passes(self):
        dsx.precheck(DOC, [{"prompt": SPEC}])

    def test_realized_hit_passes_and_missed_hit_raises(self):
        prompt = SPEC + DOC
        dsx.postcheck(prompt, {"prompt_tokens": 20000, "prompt_cache_hit_tokens": 9800}, len(SPEC) + len(DOC) // 2)
        with self.assertRaises(dsx.MissedCacheError):
            dsx.postcheck(prompt, {"prompt_tokens": 20000, "prompt_cache_hit_tokens": 0}, len(SPEC) + len(DOC) // 2)

    def test_common_prefix(self):
        self.assertEqual(dsx.common_prefix("abcdef", "abcxyz"), 3)
        self.assertEqual(dsx.common_prefix("abc", "abc"), 3)

    def test_internal_duplicates_counted(self):
        self.assertGreaterEqual(dsx.duplicate_chars_within(DOC + DOC), dsx.MIN_SHARED)

    def test_shifted_shared_content_still_detected(self):   # instructions of different lengths before the shared doc
        with self.assertRaises(dsx.MissedCacheError):
            dsx.precheck("a much longer task description B\n" + DOC, [{"prompt": "task A\n" + DOC}])


class Body(unittest.TestCase):
    def test_no_max_tokens_no_system(self):
        body = dsx.body_for("x", "deepseek-v4-pro", "max")
        self.assertNotIn("max_tokens", body)
        self.assertEqual([m["role"] for m in body["messages"]], ["user"])
        self.assertEqual(body["reasoning_effort"], "max")


if __name__ == "__main__":
    unittest.main()
