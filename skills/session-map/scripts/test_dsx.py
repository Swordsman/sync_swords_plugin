import contextlib
import datetime as dt
import io
import json
import pathlib
import tempfile
import unittest
from unittest import mock

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
    def test_resumed_conversation_extends_first_prompt(self):
        first = SPEC + DOC
        resumed = [{"role": "user", "content": first}, {"role": "assistant", "content": "log"},
                   {"role": "user", "content": "did you get everything?"}]
        checks = dsx.precheck(dsx.flatten(resumed), [{"prompt": first}])
        self.assertEqual(checks["expected_prefix_chars"], len(first))
        self.assertEqual(dsx.body_for(resumed, "deepseek-v4-pro", "max")["messages"], resumed)

    def test_no_max_tokens_no_system(self):
        body = dsx.body_for("x", "deepseek-v4-pro", "max")
        self.assertNotIn("max_tokens", body)
        self.assertEqual([m["role"] for m in body["messages"]], ["user"])
        self.assertEqual(body["reasoning_effort"], "max")


UTC = dt.timezone.utc
NOW = dt.datetime(2026, 11, 2, 12, tzinfo=UTC)


class TreeStore(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        home = pathlib.Path(folder.name) / ".dsx"
        self.out = pathlib.Path(folder.name) / "out.md"
        self.sent, self.hit_share = [], 1.0
        patches = [mock.patch.object(dsx, name, value) for name, value in
                   (("HOME", home), ("LOG", home / "io.jsonl"), ("DB", home / "dsx.db"), ("stream", self.fake_stream))]
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)
        quiet = contextlib.redirect_stderr(io.StringIO())
        quiet.__enter__()
        self.addCleanup(quiet.__exit__, None, None, None)
        self.db = dsx.open_db()
        self.addCleanup(self.db.close)

    def fake_stream(self, body):
        self.sent.append(body["messages"])
        reply = f"reply to {body['messages'][-1]['content'][:20]}"
        tokens = len(dsx.flatten(body["messages"])) // 4
        hit = int(tokens * self.hit_share)
        usage = {"prompt_tokens": tokens, "prompt_cache_hit_tokens": hit, "prompt_cache_miss_tokens": tokens - hit,
                 "completion_tokens": 5}
        return reply, "thinking text", usage, "stop"

    def count(self, table):
        return self.db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]

    def test_identical_histories_share_nodes(self):
        first = dsx.send(None, "P", self.out)
        self.assertEqual(dsx.send(None, "P", self.out), first)
        self.assertEqual((self.count("node"), self.count("call")), (2, 2))
        left, right = dsx.send(first, "A", self.out), dsx.send(first, "B", self.out)
        self.assertNotEqual(left, right)
        self.assertEqual(self.count("node"), 6)         # P, reply, then A and B each with a reply
        parents = {parent for (parent,) in self.db.execute("SELECT parent FROM node WHERE role = 'user' AND content IN ('A', 'B')")}
        self.assertEqual(parents, {first})

    def test_continue_and_fork_message_lists(self):
        user = lambda text: {"role": "user", "content": text}
        reply = lambda text: {"role": "assistant", "content": f"reply to {text}"}
        first = dsx.send(None, "P", self.out)
        second = dsx.send(first, "A", self.out)
        dsx.send(first, "B", self.out)                  # fork from the first reply
        dsx.send(second, "C", self.out)                 # continue
        self.assertEqual(self.sent, [[user("P")],
                                     [user("P"), reply("P"), user("A")],
                                     [user("P"), reply("P"), user("B")],
                                     [user("P"), reply("P"), user("A"), reply("A"), user("C")]])

    def test_stored_reply_extended_is_byte_identical(self):
        odd = " \u00e9\n\n tail \r\n"
        with mock.patch.object(dsx, "stream", lambda body: (odd, "", {"prompt_tokens": 10}, "stop")):
            reply = dsx.send(None, "P", self.out)
        dsx.send(reply, "next", self.out)
        self.assertEqual(self.sent[-1], [{"role": "user", "content": "P"}, {"role": "assistant", "content": odd},
                                         {"role": "user", "content": "next"}])

    def test_truncated_reply_is_logged_then_raises(self):   # 2026-11-03: a cut-off reply passed as complete
        cut = lambda body: ("partial", "", {"prompt_tokens": 10, "completion_tokens": 8192}, "length")
        with mock.patch.object(dsx, "stream", cut), self.assertRaisesRegex(dsx.TruncatedError, "8192"):
            dsx.call("P", self.out)
        record = json.loads(dsx.LOG.read_text().splitlines()[-1])
        self.assertEqual((record["finish_reason"], self.out.read_text()), ("length", "partial"))

    def test_missing_out_folder_is_created_and_the_call_logged(self):   # 2026-11-05: a paid reply was lost
        out = self.out.parent / "new" / "deeper" / "reply.md"
        dsx.call("P", out)
        self.assertTrue(out.exists())
        self.assertEqual(json.loads(dsx.LOG.read_text().splitlines()[-1])["out"], str(out))

    def test_call_records_root_and_reply(self):
        record = dsx.call("P", self.out)
        self.assertEqual(self.count("node"), 2)
        self.assertEqual(record["response_node"], dsx.send(None, "P", self.out))
        self.assertEqual(self.db.execute("SELECT reasoning FROM call").fetchone()[0], "thinking text")
        resumed = [{"role": "user", "content": "P"}, {"role": "assistant", "content": "reply to P"},
                   {"role": "user", "content": "more"}]
        dsx.call(resumed, self.out)
        self.assertEqual(self.sent[-1], resumed)

    def test_cached_ancestor_respects_window_model_and_thinking(self):
        ids = [identity for identity, _, _ in dsx.chain(self.db, dsx.add_messages(self.db, [
            {"role": "user", "content": "P"}, {"role": "assistant", "content": "A1"}, {"role": "user", "content": "Q"},
            {"role": "assistant", "content": "A2"}, {"role": "user", "content": "R"}], NOW.isoformat()))]

        def earlier(request, response, hours_ago, model="m", thinking="auto"):
            dsx.store_call(self.db, request_node=request, response_node=response, model=model, thinking=thinking,
                           usage={}, usd=0, reasoning="", seconds=0, accept_miss=None,
                           created_at=(NOW - dt.timedelta(hours=hours_ago)).isoformat())

        depth = lambda count: sum(len(c) for c in ("P", "A1", "Q", "A2", "R")[:count]) + count - 1
        lookup = lambda model="m", thinking="auto": dsx.cached_prefix_chars(self.db, ids[4], model, thinking, NOW)
        self.assertEqual(lookup(), 0)
        earlier(ids[0], ids[1], hours_ago=1)
        self.assertEqual(lookup(), depth(2))            # a reply counts
        earlier(ids[2], ids[3], hours_ago=30)
        self.assertEqual(lookup(), depth(2))            # older than 24h: ignored
        self.assertEqual((lookup("other"), lookup(thinking="max")), (0, 0))
        other_reply = dsx.add_node(self.db, ids[2], "assistant", "elsewhere", NOW.isoformat())
        earlier(ids[2], other_reply, hours_ago=2)
        self.assertEqual(lookup(), depth(3))            # a request's own last node counts, even with another reply

    def test_missed_hit_on_extended_chain_raises_after_storing(self):
        reply = dsx.send(None, SPEC, self.out)
        self.hit_share = 0
        with self.assertRaises(dsx.MissedCacheError):
            dsx.send(reply, "more", self.out)
        self.assertEqual(self.count("call"), 2)
        self.hit_share = 0.95
        dsx.send(reply, "even more", self.out)


    def sent_chains(self, chains, hours_ago=1):
        """Store each message chain as an earlier request in the last `hours_ago` hours; returns the stored chains' node ids."""
        stored = []
        for messages in chains:
            request = dsx.add_messages(self.db, messages, NOW.isoformat())
            reply = dsx.add_node(self.db, request, "assistant", "ok", NOW.isoformat())
            dsx.store_call(self.db, request_node=request, response_node=reply, model="m", thinking="auto", usage={}, usd=0,
                           reasoning="", seconds=0, accept_miss=None, created_at=(NOW - dt.timedelta(hours=hours_ago)).isoformat())
            stored.append(request)
        return stored

    def expected_for(self, messages):
        return dsx.cached_prefix_chars(self.db, dsx.add_messages(self.db, messages, NOW.isoformat()), "m", "auto", NOW)

    def test_shared_leading_stretch_of_sibling_messages(self):   # Y1 Z2 Y3a, Y1 Z2 Y3b, then Y1 Z2 Y3c
        user, assistant = (lambda text: {"role": "user", "content": text}), (lambda text: {"role": "assistant", "content": text})
        stretch = "shared leading document " * 40
        head = [user("Y1 spec"), assistant("Z2 got it")]
        self.sent_chains([head + [user(stretch + "alpha")], head + [user(stretch + "bravo")]])
        self.assertEqual(self.expected_for(head + [user(stretch + "charlie")]),
                         len("Y1 spec") + 1 + len("Z2 got it") + 1 + len(stretch))
        self.assertEqual(self.expected_for(head + [user("unrelated")]), len("Y1 spec") + 1 + len("Z2 got it"))   # Z2 shared by both

    def test_shared_leading_document_between_roots(self):
        user = lambda text: {"role": "user", "content": text}
        document = "document line\n" * 300
        self.sent_chains([[user(document + "alpha")], [user(document + "bravo")]])
        self.assertEqual(self.expected_for([user(document + "charlie")]), len(document))
        self.assertEqual(self.expected_for([user("other")]), 0)

    def test_one_earlier_sibling_gets_no_partial_credit(self):
        user = lambda text: {"role": "user", "content": text}
        document = "document line\n" * 300
        self.sent_chains([[user(document + "alpha")]])
        self.assertEqual(self.expected_for([user(document + "charlie")]), 0)

    def test_sibling_credit_respects_window(self):
        user = lambda text: {"role": "user", "content": text}
        document = "document line\n" * 300
        self.sent_chains([[user(document + "alpha")], [user(document + "bravo")]], hours_ago=30)
        self.assertEqual(self.expected_for([user(document + "charlie")]), 0)

    def test_prefilled_assistant_node(self):
        first = dsx.add_node(self.db, None, "user", "Y1 spec", NOW.isoformat())
        self.db.commit()
        prefilled = dsx.prefill(first, "got it")
        self.assertEqual(self.db.execute("SELECT origin FROM node WHERE id = ?", (prefilled,)).fetchone()[0], "authored")
        self.assertEqual(self.count("call"), 0)
        dsx.send(prefilled, "Y3", self.out)
        self.assertEqual(self.sent, [[{"role": "user", "content": "Y1 spec"}, {"role": "assistant", "content": "got it"},
                                      {"role": "user", "content": "Y3"}]])
        with self.assertRaises(ValueError):
            dsx.prefill(prefilled, "assistant after assistant")

    def test_store_without_origin_column_is_migrated(self):
        self.db.close()
        dsx.DB.unlink()
        old = dsx.sqlite3.connect(dsx.DB)
        old.executescript(dsx.SCHEMA.replace(", origin TEXT NOT NULL DEFAULT 'generated' CHECK (origin IN ('generated', 'authored'))", ""))
        old.close()
        self.db = dsx.open_db()
        self.addCleanup(self.db.close)
        self.assertEqual(dsx.add_node(self.db, None, "user", "x", NOW.isoformat()), dsx.node_id(None, "user", "x"))

    def test_import_skips_responseless_and_is_idempotent(self):
        usage = {"prompt_cache_hit_tokens": 30, "prompt_cache_miss_tokens": 10, "completion_tokens": 1}
        base = {"at": NOW.isoformat(), "model": "deepseek-v4-pro", "thinking": "max", "seconds": 1.0, "usage": usage, "usd": 0.1}
        records = [base | {"prompt": "old"},
                   base | {"prompt": "P", "response": "R"},
                   base | {"prompt": "P\nR\nQ", "response": "S", "at": (NOW + dt.timedelta(minutes=1)).isoformat(),
                           "messages": [{"role": "user", "content": "P"}, {"role": "assistant", "content": "R"},
                                        {"role": "user", "content": "Q"}]}]
        dsx.LOG.parent.mkdir(exist_ok=True)
        dsx.LOG.write_text("\n".join(map(json.dumps, records)) + "\n")
        self.assertEqual(dsx.import_log(self.db, dsx.LOG), {"imported": 2, "already_imported": 0, "skipped_no_response": 1})
        self.assertEqual(dsx.import_log(self.db, dsx.LOG), {"imported": 0, "already_imported": 2, "skipped_no_response": 1})
        self.assertEqual((self.count("node"), self.count("call")), (4, 2))   # P, R, then Q and S continue the same chain
        self.assertEqual(dsx.tree_report(self.db), "1 roots, 4 nodes, 2 calls, 75% of input tokens cache hits")

    def test_show_prints_role_and_first_80_chars(self):
        reply = dsx.send(None, "line one\n" + "x" * 200, self.out)
        lines = dsx.describe(self.db, reply)
        self.assertEqual(len(lines), 2)
        self.assertTrue(lines[0].split(" ", 1)[1].startswith("user: line one x"))
        self.assertEqual(len(lines[0].split("user: ", 1)[1]), 80)
        self.assertEqual(dsx.resolve(self.db, reply[:10]), reply)


class PersistedPrefix(unittest.TestCase):
    @staticmethod
    def brute(prompt, prior):   # the pairwise definition the linear version replaced (2026-11-04)
        boundary = max((len(c["prompt"]) for c in prior if prompt.startswith(c["prompt"])), default=0)
        shared = 0
        for index, first in enumerate(prior):
            for second in prior[index + 1:]:
                pair = dsx.common_prefix(first["prompt"], second["prompt"])
                if pair > shared and prompt.startswith(first["prompt"][:pair]):
                    shared = pair
        return max(boundary, shared)

    def test_matches_pairwise_definition(self):
        import random
        rng = random.Random(4)
        for _ in range(3000):
            prompt = "".join(rng.choice("ab") for _ in range(rng.randint(0, 8)))
            prior = [{"prompt": "".join(rng.choice("ab") for _ in range(rng.randint(0, 8)))}
                     for _ in range(rng.randint(0, 5))]
            self.assertEqual(dsx.persisted_prefix(prompt, prior), self.brute(prompt, prior), (prompt, prior))


class StreamParsing(unittest.TestCase):
    TOKEN = 'data: {"choices":[{"delta":{"content":"hi"}}]}'
    USAGE = 'data: {"choices":[],"usage":{"prompt_tokens":5,"completion_tokens":1}}'

    def run_lines(self, timed_lines):
        """timed_lines: (seconds since start, line). The clock returns each line's time as it is read."""
        times = iter([0] + [moment for moment, _ in timed_lines])
        return dsx.parse_stream((line for _, line in timed_lines), lambda: next(times))

    def test_normal_stream(self):
        content, _, usage, finish = self.run_lines([(1, self.TOKEN), (2, self.USAGE), (2, "data: [DONE]")])
        self.assertEqual((content, usage["completion_tokens"], finish), ("hi", 1, None))

    def test_finish_reason_length_is_reported(self):   # 2026-11-03: a non-thinking reply silently stopped at 8192
        cut = 'data: {"choices":[{"delta":{"content":"x"},"finish_reason":"length"}]}'
        self.assertEqual(self.run_lines([(1, cut), (2, self.USAGE), (2, "data: [DONE]")])[3], "length")

    def test_thinking_off_requests_the_maximum_output(self):
        self.assertEqual(dsx.body_for("p", "deepseek-flash", "off")["max_tokens"], dsx.MAX_OUTPUT_TOKENS)
        self.assertNotIn("max_tokens", dsx.body_for("p", "deepseek-flash", "auto"))

    def test_keep_alives_do_not_count_as_progress(self):   # 2026-11-03: a Pro call sat queued 25+ minutes
        queued = [(minute * 60, ": keep-alive") for minute in range(1, 26)]
        with self.assertRaisesRegex(dsx.StreamError, "no first token"):
            self.run_lines(queued + [(1600, self.TOKEN)])

    def test_stall_after_output_started(self):
        with self.assertRaisesRegex(dsx.StreamError, "no new token"):
            self.run_lines([(1, self.TOKEN), (60, ": keep-alive"), (200, ": keep-alive"), (201, self.TOKEN)])

    def test_stream_without_usage_raises(self):   # 2026-11-03: left an empty $0 record in the log
        with self.assertRaisesRegex(dsx.StreamError, "without usage"):
            self.run_lines([(1, self.TOKEN), (2, "data: [DONE]")])


if __name__ == "__main__":
    unittest.main()
