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


    @unittest.skipUnless(__import__("shutil").which("node"), "node not installed")
    def test_page_script_parses(self):   # 2026-11-05: a "\\n" in the Python template became a raw newline in JS
        import subprocess, tempfile
        title, nodes = im.read(MAP)
        script = re.search(r"<script>(.*)</script>", im.force_page(title, nodes, []), re.S).group(1)
        with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False) as handle:
            handle.write(script)
        result = subprocess.run(["node", "--check", handle.name], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)


class Meta(unittest.TestCase):
    WITH_META = MAP.replace('(goal G', '(project "demo")\n  (ref other-map "builds on it")\n  (ref plain)\n  (goal G', 1)

    def test_project_and_refs_are_read(self):
        parsed = im.read_map(self.WITH_META)
        self.assertEqual(parsed.project, "demo")
        self.assertEqual([(r.slug, r.why) for r in parsed.refs], [("other-map", "builds on it"), ("plain", "")])
        self.assertEqual(len(parsed.nodes), 5)

    def test_maps_without_them_still_read(self):
        parsed = im.read_map(MAP)
        self.assertEqual((parsed.project, parsed.refs), (None, ()))
        self.assertEqual(im.read(self.WITH_META)[1], im.read(MAP)[1])

    def test_bad_meta_is_loud(self):
        for bad in ('(project "a") (project "b")', '(project a)', '(ref "quoted" "x")', '(ref bad_slug "x")', '(ref)',
                    '(ref a "x" "y")'):
            with self.assertRaises(ValueError, msg=bad):
                im.read_map(f'(intent-map "t" {bad} (goal G "g"))')
        with self.assertRaises(ValueError):
            parsed = im.read_map('(intent-map "t" (ref a) (ref a "again") (goal G "g"))')
            im.check(parsed.nodes, parsed.refs)


class Store(unittest.TestCase):
    def test_payload_holds_what_the_viewer_needs(self):
        doc = im.payload("demo-map", Meta.WITH_META)
        self.assertEqual((doc["slug"], doc["title"], doc["project"], doc["goal"]), ("demo-map", "t", "demo", "the goal"))
        self.assertEqual(doc["sexpr"], Meta.WITH_META)
        self.assertEqual(doc["refs"], [{"slug": "other-map", "why": "builds on it"}, {"slug": "plain", "why": ""}])
        self.assertEqual(doc["counts"], {"built": 1, "unmet": 1})
        self.assertEqual(doc["data"], im.page_data(im.read(MAP)[1], im.check(im.read(MAP)[1])))
        self.assertRegex(doc["updatedAt"], r"^\d{4}-\d\d-\d\dT")

    def test_bad_slug_and_self_ref_raise(self):
        for slug in ("has space", "under_score", "a/b", ""):
            with self.assertRaises(ValueError, msg=slug):
                im.payload(slug, MAP)
        with self.assertRaises(ValueError):
            im.payload("me", MAP.replace("(goal", '(ref me "x")\n  (goal', 1))

    def test_store_writes_one_doc_and_registers_the_collection(self):
        calls = []

        class FakeLsdb:
            set_doc = staticmethod(lambda url, path, data: calls.append(("set", url, path, data["slug"])))
            register = staticmethod(lambda url, name, description: calls.append(("register", url, name)))

        import imstore
        original, imstore.load_lsdb = imstore.load_lsdb, lambda: FakeLsdb
        try:
            im.store("https://claude.ai/artifact/X", "demo-map", MAP)
        finally:
            imstore.load_lsdb = original
        self.assertEqual(calls, [("set", "https://claude.ai/artifact/X", "maps/demo-map", "demo-map"),
                                 ("register", "https://claude.ai/artifact/X", "maps")])

    def test_real_lsdb_is_found(self):
        import imstore
        self.assertTrue(hasattr(imstore.load_lsdb(), "set_doc"))


if __name__ == "__main__":
    unittest.main()
