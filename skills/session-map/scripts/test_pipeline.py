import unittest

from pipeline import repair


class Repair(unittest.TestCase):
    def test_missing_closer_before_next_delta(self):
        fixed, report = repair("(delta :turn 1\n  (add (claim c1 (x) :by user :src t1))\n(delta :turn 2)\n")
        self.assertEqual(fixed.count("(delta"), 2)
        self.assertEqual(report["closed"], 1)
        self.assertEqual(fixed.count("("), fixed.count(")"))

    def test_stray_closer_dropped(self):   # 2026-11-02: an extra ')' ended a delta early in the one-shot fix output
        fixed, report = repair("(delta :turn 1\n  (add (claim c1 (x) :by user :src t1))))\n(delta :turn 2)\n")
        self.assertEqual(report["dropped"], 1)
        self.assertEqual(fixed.count("("), fixed.count(")"))

    def test_wraps_bare_frames_only_inside_delta(self):
        fixed, report = repair("(delta :turn 1\n  (claim c1 (x) :by user :src t1)\n  (add (claim c2 (y) :by user :src t1)))\n")
        self.assertEqual(report["wrapped"], 1)
        self.assertNotIn("(add (add", fixed)

    def test_strings_and_comments_untouched(self):
        text = '(delta :turn 1 ; a ) comment\n  (add (claim c1 (x "a ) b") :by user :src t1)))\n'
        fixed, report = repair(text)
        self.assertEqual(fixed, text)
        self.assertEqual(report, {"closed": 0, "dropped": 0, "wrapped": 0})


if __name__ == "__main__":
    unittest.main()
