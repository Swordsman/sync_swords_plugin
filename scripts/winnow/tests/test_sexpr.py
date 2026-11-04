"""Unit tests for sexpr.py — the shared s-expression reader and printer."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from sexpr import Lit, anns, parse, sx, tokenize  # noqa: E402


class TestParse(unittest.TestCase):
    def test_roundtrip(self):
        forms = parse(tokenize('(a (b "c d") 1.0 :key val)'))
        self.assertEqual(sx(forms[0]), '(a (b "c d") 1.0 :key val)')

    def test_comments_stripped(self):
        forms = parse(tokenize("; comment\n(a b) ; tail\n(c)"))
        self.assertEqual(len(forms), 2)

    def test_string_literals_keep_spaces_and_parens_matter(self):
        forms = parse(tokenize('(x "a (b) ; c")'))
        self.assertIsInstance(forms[0][1], Lit)
        self.assertEqual(str(forms[0][1]), "a (b) ; c")

    def test_anns_collects_keyword_pairs(self):
        tail = parse(tokenize('(x :status open :by user stray "lit")'))[0][1:]
        self.assertEqual(anns(tail), {"status": "open", "by": "user"})

    def test_fold_reexports_the_reader(self):
        import fold
        self.assertIs(fold.parse, parse)
        self.assertIs(fold.Lit, Lit)


if __name__ == "__main__":
    unittest.main()
