import datetime as dt
import json
import sqlite3
import unittest

import dsx
import dsxgraph
import dsxrules
import dsxtree

NOW = dt.datetime.now(dt.timezone.utc).isoformat()
SUNDAY = "2026-11-01T00:50:00+00:00"   # off-peak
USAGE = {"prompt_tokens": 1000, "completion_tokens": 100, "prompt_cache_hit_tokens": 900, "prompt_cache_miss_tokens": 100,
         "completion_tokens_details": {"reasoning_tokens": 40}}


def store() -> sqlite3.Connection:
    """system -> shared ack -> two questions (a fork). Each question is a call: request, response."""
    db = sqlite3.connect(":memory:")
    db.executescript(dsx.SCHEMA)
    system = dsx.add_node(db, None, "system", "You are an agent.\nSecond line", NOW)
    ack = dsx.add_node(db, system, "assistant", "Understood.", NOW, origin="authored")
    for n in (1, 2):
        question = dsx.add_node(db, ack, "user", f"Question {n}:\nabout cache\n", NOW)
        answer = dsx.add_node(db, question, "assistant", f"Answer {n}", NOW)
        dsx.store_call(db, request_node=question, response_node=answer, model="deepseek-flash", thinking="auto", usage=USAGE,
                       usd=0.0001, reasoning="",
                       seconds=2.5, accept_miss=None, created_at=SUNDAY)
    return db


class Mapping(unittest.TestCase):
    def setUp(self):
        self.g = dsxtree.graph(store())
        self.by = {n["text"]: n for n in self.g["nodes"]}

    def test_every_message_is_a_node_and_every_extension_a_link(self):
        self.assertEqual(len(self.g["nodes"]), 6)
        self.assertEqual(len(self.g["links"]), 5)

    def test_a_fork_is_marked_where_calls_diverge(self):
        ack = self.by["Understood."]
        self.assertTrue(ack["fork"])
        self.assertEqual(ack["branches"], 2)

    def test_requests_and_responses_are_told_apart(self):
        self.assertEqual(self.by["Question 1: about cache"]["style"], "request")
        self.assertEqual(self.by["Answer 1"]["style"], "response")
        self.assertEqual(self.by["Understood."]["style"], "authored")
        self.assertEqual({l["kind"] for l in self.g["links"] if l["target"] == self.by["Answer 1"]["id"]}, {"call"})

    def test_label_is_the_first_line_and_joins_a_trailing_colon(self):
        self.assertIn("You are an agent.", self.by)
        self.assertIn("Question 1: about cache", self.by)

    def test_request_holds_the_prompt_side_and_response_the_output_side(self):
        request, response = self.by["Question 1: about cache"], self.by["Answer 1"]
        self.assertEqual((request["tokens"], request["hit"], request["hitrate"]), (1000, 900, 0.9))
        self.assertEqual((response["tokens"], response["think"], response["seconds"]), (100, 40, 2.5))
        self.assertAlmostEqual(request["cost"] + response["cost"], 0.0001, places=8)

    def test_branch_totals_roll_up_to_the_fork_and_the_root(self):
        self.assertAlmostEqual(self.by["Understood."]["spent"], 0.0002, places=8)
        self.assertEqual(self.by["Understood."]["calls"], 2)
        self.assertEqual(self.g["stats"]["spent"], 0.0002)
        self.assertEqual(self.g["nodes"][0]["depth"], 0)

    def test_priority_is_zero_for_no_spend_and_a_fifth_each_otherwise(self):
        self.assertEqual(self.by["Answer 1"]["priority"], 0)
        nodes = [{"spent": s} for s in (1, 2, 3, 4, 5)] + [{}]
        dsxtree.rank(nodes)
        self.assertEqual([n["priority"] for n in nodes], [1, 2, 3, 4, 5, 0])


class Trimming(unittest.TestCase):
    def test_costliest_branches_stay_and_the_rest_fold_into_one_rollup_per_fork(self):
        db = store()
        root = dsxtree.resolve(db, dsxtree.read(db)[0], None)
        ack = next(i for i, in db.execute("SELECT id FROM node WHERE role = 'assistant' AND origin = 'authored'"))
        g = dsxtree.graph(db, root, budget=4)   # system, ack, one question, its answer
        rollups = [n for n in g["nodes"] if n["kind"] == "rollup"]
        self.assertEqual(len(rollups), 1)
        self.assertEqual(rollups[0]["text"], "+1 more branches, 2 nodes")
        self.assertEqual(rollups[0]["calls"], 1)
        self.assertEqual({l["kind"] for l in g["links"] if l["target"] == rollups[0]["id"]}, {"rollup"})
        self.assertEqual(g["stats"]["total"], 6)
        self.assertEqual(ack[:10], next(n["id"] for n in g["nodes"] if n["text"] == "Understood."))

    def test_a_call_keeps_its_response_with_its_request(self):
        g = dsxtree.graph(store(), None, budget=4)
        styles = {n["style"] for n in g["nodes"]}
        self.assertIn("request", styles)
        self.assertIn("response", styles)

    def test_resolve_takes_a_prefix_a_tag_or_the_largest_root(self):
        db = store()
        rows = dsxtree.read(db)[0]
        top = dsxtree.resolve(db, rows, None)
        self.assertEqual(dsxtree.resolve(db, rows, top[:8]), top)
        with self.assertRaises(ValueError):
            dsxtree.resolve(db, rows, "zzzz")


class Doc(unittest.TestCase):
    def test_doc_carries_data_rulesets_and_modes_and_fits_one_lsdb_doc(self):
        doc = dsxgraph.build(store(), None, 400, "dsx-test", None, "dsx")
        self.assertEqual((doc["kind"], doc["slug"], doc["modes"]), ("graph", "dsx-test", ["nodes", "cards"]))
        self.assertEqual(set(doc["presets"]), {"cards", "nodes"})
        self.assertEqual(doc["stats"]["nodes"], 6)
        self.assertLess(len(json.dumps(doc)), 250 * 1024)

    def test_rulesets_only_name_behaviors_and_fields_the_engine_and_nodes_have(self):
        behaviors = {"shape", "size", "style", "template", "column", "stack", "relax", "repel", "gravity", "spring"}
        for preset in dsxrules.presets(3).values():
            for rule in preset["rules"]:
                self.assertTrue({name for name, _ in rule["do"]} <= behaviors, rule["id"])


if __name__ == "__main__":
    unittest.main()
