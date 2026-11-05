import unittest

import merge_dropped as md


class Merge(unittest.TestCase):
    items = [{"id": "i001", "sources": ["b0001"], "text": "port 8080", "origin": "agent"},
             {"id": "i002", "sources": ["b0005"], "text": "the server port is 8080", "origin": "agent"},
             {"id": "i003", "sources": ["b0009", "b0010"], "text": "commit in French", "origin": "deepseek-on"},
             {"id": "i004", "sources": ["b0002"], "text": "port is 8080 (dev)", "origin": "agent"}]

    def test_groups_union_and_unknown_ids_fail(self):
        ids = {item["id"] for item in self.items}
        self.assertEqual(md.groups_from("i001 i002\ni002 i004\nNONE-ish i003", ids), [{"i001", "i002", "i004"}])
        with self.assertRaises(ValueError):
            md.groups_from("i001 i999", ids)

    def test_assemble_keeps_text_verbatim_and_all_sources(self):
        final = md.assemble(self.items, [{"i001", "i002", "i004"}])
        merged = next(item for item in final if len(item["members"]) == 3)
        self.assertEqual(merged["text"], "the server port is 8080")            # a member's text, unchanged
        self.assertEqual(merged["sources"], ["b0001", "b0002", "b0005"])
        self.assertEqual(len(final), 2)
        self.assertTrue({item["text"] for item in final} <= {item["text"] for item in self.items})


    def test_doubted_members_split_back_out(self):
        groups = [{"i001", "i002", "i004"}]
        probabilities = md.contained(self.items, groups, ask=lambda state, questions: {"answers": {
            name: {"noul": 0.9 if name.endswith("i001") else 0.1} for name in questions}})
        self.assertEqual(md.verified(self.items, groups, probabilities), [{"i002", "i001"}])   # i004 stands alone


if __name__ == "__main__":
    unittest.main()
