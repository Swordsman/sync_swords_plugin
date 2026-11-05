import contextlib
import io
import pathlib
import tempfile
import threading
import unittest
from unittest import mock

import agent_check
import dsx
import msgagents


class Agents(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.dir = pathlib.Path(folder.name)
        home = self.dir / ".dsx"
        self.sent, self.lock = [], threading.Lock()
        for name, value in (("HOME", home), ("LOG", home / "io.jsonl"), ("DB", home / "dsx.db"),
                            ("stream", self.fake_stream)):
            patch = mock.patch.object(dsx, name, value)
            patch.start()
            self.addCleanup(patch.stop)
        quiet = contextlib.redirect_stderr(io.StringIO())
        quiet.__enter__()
        self.addCleanup(quiet.__exit__, None, None, None)
        self.db = msgagents.open_db()
        self.addCleanup(self.db.close)

    def fake_stream(self, body):
        with self.lock:
            self.sent.append(body["messages"])
        tokens = len(dsx.flatten(body["messages"])) // 4
        return "SCORE: 2\nLOST: the port", "", {"prompt_tokens": tokens, "completion_tokens": 3}, "stop"

    def spawn(self, payload=None):
        with self.db:
            under = msgagents.context(self.db, payload)
            first = msgagents.spawn(self.db, under, "m0001", "user", "use port 8080", [])
            second = msgagents.spawn(self.db, under, "m0002", "assistant", "ok", ["use port 8080"], parent_agent=first)
        return first, second

    def test_context_shape(self):
        first, _ = self.spawn("SUMMARY TEXT")
        roles = [role for _, role, _ in dsx.chain(self.db, first)]
        self.assertEqual(roles, ["system", "user", "assistant", "user", "assistant"])
        self.assertEqual(dsx.chain(self.db, first)[1][2], "SUMMARY TEXT")   # shared payload precedes the message

    def test_questions_fork_and_trunk_never_grows(self):
        first, _ = self.spawn()
        msgagents.ask(first, "Q1", self.dir / "a.md")
        msgagents.ask(first, "Q2", self.dir / "b.md")
        self.assertEqual(len(self.sent[0]), len(self.sent[1]))            # same depth for the 2nd question
        self.assertEqual(self.sent[1][-1], {"role": "user", "content": "Q2"})
        self.assertNotIn("Q1", dsx.flatten(self.sent[1]))

    def test_agent_table_relations_and_supersede(self):
        first, second = self.spawn()
        self.assertEqual(self.db.execute("SELECT parent_agent FROM agent WHERE id = ?", (second,)).fetchone()[0], first)
        with self.db:
            msgagents.supersede(self.db, first, second)
        self.assertEqual(self.db.execute("SELECT status, superseded_by FROM agent WHERE id = ?", (first,)).fetchone(),
                         ("superseded", second))

    def test_broadcast_answers_everyone_in_parallel(self):
        agents = dict(zip(("a", "b"), self.spawn("P")))
        with self.db:
            under = msgagents.context(self.db, "P")
            agents |= {f"x{n}": msgagents.spawn(self.db, under, f"x{n}", "user", f"msg {n}") for n in range(10)}
        results = msgagents.broadcast(agents, "Q", self.dir / "answers", workers=4)
        self.assertEqual(set(results), set(agents))
        self.assertEqual(len(dsx.LOG.read_text().splitlines()), 12)      # one intact log line per call

    def test_broadcast_reports_failures_without_losing_answers(self):
        agents = dict(zip(("a", "b"), self.spawn()))
        with self.db:
            under = msgagents.context(self.db)
            agents["bad"] = msgagents.spawn(self.db, under, "bad", "user", "explode")
        good = self.fake_stream

        def flaky(body):
            if "explode" in dsx.flatten(body["messages"]):
                raise dsx.StreamError("boom")
            return good(body)

        with mock.patch.object(dsx, "stream", flaky), self.assertRaises(msgagents.BroadcastError) as caught:
            msgagents.broadcast(agents, "Q", self.dir / "answers", workers=2, warm=0)
        self.assertEqual((set(caught.exception.results), set(caught.exception.failures)), ({"a", "b"}, {"bad"}))


class Parse(unittest.TestCase):
    def test_formats(self):
        self.assertEqual(agent_check.parse("SCORE: 3\nLOST: commit in French"), (3, "commit in French"))
        self.assertEqual(agent_check.parse("**SCORE:** 0\n**LOST:** NONE"), (0, ""))
        self.assertEqual(agent_check.parse("SCORE: UNKNOWN\nLOST: NONE"), (None, ""))
        self.assertEqual(agent_check.parse("garbage"), (None, ""))


if __name__ == "__main__":
    unittest.main()
