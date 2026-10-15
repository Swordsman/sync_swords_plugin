"""tokenwatch over a synthetic session: per-agent sums, flags, notes."""
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import tokenwatch  # noqa: E402


def call(read, out, tool=None):
    content = [{"type": "tool_use", "name": "Read", "input": {"file_path": tool}}] if tool else []
    return {"type": "assistant", "timestamp": "2026-10-15T06:00:00Z",
            "message": {"usage": {"input_tokens": 2, "cache_read_input_tokens": read,
                                  "cache_creation_input_tokens": 10, "output_tokens": out},
                        "content": content}}


class TestTokenwatch(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.session = os.path.join(self.d, "s1.jsonl")
        self.write(self.session, [call(1000, 50), {"type": "user", "message": {"content":
            [{"type": "text", "text": "You've hit your session limit · resets 10:20am (UTC)"}]}}])
        wf = os.path.join(self.d, "s1", "subagents", "workflows", "wf_abc")
        os.makedirs(wf)
        for agent, n in (("a1", 50), ("a2", 3), ("a3", 3)):
            self.write(os.path.join(wf, agent + ".jsonl"),
                       [call(200000, 10, tool="/r/spec.md") for _ in range(n)])
            label = "design:x" if agent in ("a1", "a2") else "verify:y"
            json.dump({"description": label}, open(os.path.join(wf, agent + ".meta.json"), "w"))

    def write(self, path, events):
        with open(path, "w") as f:
            for e in events:
                f.write(json.dumps(e) + "\n")

    def report(self, **kw):
        ns = type("A", (), dict(max_calls=40, max_context=150000, reread_ratio=200.0,
                                big_result=20000, shared_readers=3, top=25, **kw))
        return tokenwatch.analyze(self.session, ns)

    def test_sums_flags_and_notes(self):
        rep = self.report()
        by = {}
        for a in rep["agents"]:
            by.setdefault(a["name"], []).append(a)
        a1 = max(by["design:x [wf_abc]"], key=lambda a: a["calls"])
        self.assertEqual((a1["calls"], a1["cacheRead"]), (50, 10_000_000))
        for flag in ("many-calls", "big-context", "reread-heavy", "reread-files", "repeated-work"):
            self.assertIn(flag, a1["flag"])
        self.assertNotIn("repeated-work", by["verify:y [wf_abc]"][0]["flag"])
        notes = " ".join(rep["notes"])
        self.assertIn("spec.md was read by 3 agents", notes)
        self.assertIn("design:x [wf_abc] ran 2 times", notes)
        self.assertIn("1 session-limit", notes)
        self.assertEqual(rep["totals"]["calls"], 57)

    def test_prose_about_limits_is_not_a_hit(self):
        self.write(self.session, [call(1000, 50), {"type": "assistant", "message": {"content":
            [{"type": "text", "text": "we hit the session limit earlier"}]}}])
        self.assertNotIn("session-limit", " ".join(self.report()["notes"]))


if __name__ == "__main__":
    unittest.main()
