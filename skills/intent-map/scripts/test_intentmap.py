import json
import re
import unittest

import intentmap as im

MAP = '''(intent-map "t"
  ; a comment
  (goal G "the goal")
  (need N1 "a \\"quoted\\" need" :serves G)
  (need N2 "unmet need" :serves G)
  (solution S1 "meets N1" :meets N1 :status built)
  (test T1 "checks S1" :tests (S1)))'''


class Read(unittest.TestCase):
    def test_reads_forms_strings_and_lists(self):
        title, nodes = im.read(MAP)
        self.assertEqual(title, "t")
        self.assertEqual([(n.kind, n.id) for n in nodes],
                         [("goal", "G"), ("need", "N1"), ("need", "N2"), ("solution", "S1"), ("test", "T1")])
        self.assertEqual(nodes[1].text, 'a "quoted" need')
        self.assertEqual(nodes[4].links, ("S1",))

    def test_bad_structure_is_loud(self):
        for bad in ('(intent-map "t" (goal G "x")', '(other "t")', '(intent-map "t" (need N "x" :bogus G))',
                    '(intent-map "t" (goal G "unterminated))'):
            with self.assertRaises(ValueError, msg=bad):
                im.read(bad)


class Contract(unittest.TestCase):
    def test_unmet_need_is_reported_not_fatal(self):
        warnings = im.check(im.read(MAP)[1])
        self.assertEqual(len(warnings), 1)
        self.assertIn("N2", warnings[0])

    def test_hard_errors(self):
        for bad in ('(intent-map "t" (goal G "g") (goal G "dup"))',
                    '(intent-map "t" (goal G "g") (need N "n" :serves X))',
                    '(intent-map "t" (goal G "g") (need N "n" :serves G) (solution S "s" :meets N))',
                    '(intent-map "t" (goal G "g") (need N "n"))'):
            with self.assertRaises(ValueError, msg=bad):
                im.check(im.read(bad)[1])


class Render(unittest.TestCase):
    def test_mermaid_columns_edges_and_status(self):
        text = im.mermaid(*im.read(MAP))
        self.assertIn("G --> N1", text)
        self.assertIn("N1 --> S1", text)
        self.assertIn("S1 ~~~ T1", text)
        self.assertIn("class N2 unmet", text)
        self.assertIn("BUILT; tested by T1", text)
        self.assertNotIn('"quoted"', text)   # quotes escaped inside labels

    def test_page_embeds_data_safely(self):
        title, nodes = im.read(MAP.replace("the goal", "</script><b>"))
        page = im.force_page(title, nodes, im.check(nodes))
        self.assertEqual(page.count("</script>"), 1)
        data = json.loads(re.search(r"const DATA = (.*);\n", page).group(1).replace("<\\/", "</"))
        self.assertEqual(len(data["nodes"]), 5)
        self.assertEqual(len(data["links"]), 4)


if __name__ == "__main__":
    unittest.main()
