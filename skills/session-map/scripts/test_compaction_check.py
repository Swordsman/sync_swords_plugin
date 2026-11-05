import json
import pathlib
import tempfile
import unittest

import compaction_check as cc


def jsonl(rows) -> pathlib.Path:
    path = pathlib.Path(tempfile.mkdtemp()) / "log.jsonl"
    path.write_text("".join(json.dumps(row) + "\n" for row in rows))
    return path


def row(kind, content, uuid, **extra):
    return {"type": kind, "uuid": uuid, "message": {"content": content}, **extra}


class Identifiers(unittest.TestCase):
    def test_kinds(self):
        text = ("see /home/claude/x.py and skills/jev/SKILL.md at https://a.b/c, cost $0.036 (12%), "
                "commit f3bdede, `ds --usage-out`, ratio 0.05")
        found = cc.identifiers(text)
        for token in ("/home/claude/x.py", "skills/jev/SKILL.md", "https://a.b/c", "$0.036", "12%", "f3bdede",
                      "ds --usage-out", "0.05"):
            self.assertIn(token, found)

    def test_slash_lists_are_not_paths(self):
        self.assertEqual(cc.identifiers("a decision/instruction/preference/etc and on/off"), [])

    def test_absent_is_case_insensitive_substring(self):
        message = cc.Message("m0001", "user", "use /home/claude/A.py and /tmp/b.txt")
        self.assertEqual(cc.absent_identifiers(message, "mentions /home/claude/a.py only"), ["/tmp/b.txt"])


class Loading(unittest.TestCase):
    def test_turns_merge_and_noise_drops(self):
        path = jsonl([
            row("user", "hello <system-reminder>noise</system-reminder>there", "u1"),
            row("assistant", [{"type": "text", "text": "ok"},
                              {"type": "tool_use", "name": "Bash", "input": {"command": "ls", "description": "List"}}],
                "a1"),
            row("user", [{"type": "tool_result", "content": "big output"}], "u2"),
            row("assistant", [{"type": "thinking", "thinking": "x"}, {"type": "text", "text": "done"}], "a2"),
            row("user", "summary text", "u3", isCompactSummary=True),
            row("user", "<task-notification>x</task-notification>", "u4"),
            row("user", "kept verbatim", "u5"),
        ])
        messages = cc.messages_from_jsonl(path, exclude=frozenset({"u5"}))
        self.assertEqual([(m.tag, m.speaker, m.text) for m in messages],
                         [("m0001", "user", "hello there"), ("m0002", "assistant", "ok\n[tool: Bash: List]\ndone")])
        self.assertEqual(messages[1].uuids, {"a1", "a2"})

    def test_summary_and_preserved_from_jsonl(self):
        path = jsonl([{"type": "system", "subtype": "compact_boundary",
                       "compactMetadata": {"preservedMessages": {"allUuids": ["p1", "p2"]}}},
                      row("user", "the summary", "s1", isCompactSummary=True)])
        self.assertEqual(cc.summary_from(path), ("the summary", frozenset({"p1", "p2"})))

    def test_text_blocks(self):
        path = pathlib.Path(tempfile.mkdtemp()) / "paste.txt"
        path.write_text("[Context: note]\n\nfirst block\nline two\n\n\nsecond\n")
        self.assertEqual([(m.tag, m.text) for m in cc.messages_from_text(path)],
                         [("b0001", "first block\nline two"), ("b0002", "second")])

    def test_tool_only(self):
        self.assertTrue(cc.is_tool_only(cc.Message("m1", "assistant", "[tool: Bash: x]\nRan a command\nRead 3 files")))
        self.assertFalse(cc.is_tool_only(cc.Message("m1", "assistant", "[tool: Bash: x]\nFound the bug.")))


class LittlewingPieces(unittest.TestCase):
    def test_contiguous_pieces_join_in_order(self):
        self.assertEqual(cc.contiguous([(2, 3, 5, b"de"), (1, 0, 3, b"abc")]), b"abcde")

    def test_gap_or_bad_length_is_loud(self):
        with self.assertRaises(ValueError):
            cc.contiguous([(1, 0, 3, b"abc"), (2, 4, 6, b"ef")])
        with self.assertRaises(ValueError):
            cc.contiguous([(1, 0, 3, b"ab")])


class JevPass(unittest.TestCase):
    def test_scores_controls_and_batching(self):
        summary = "- **Decision:** " + "the plan is to keep the whole thing in one script for now " * 2
        messages = [cc.Message(f"m{i:04d}", "user", f"message {i}") for i in range(1, 6)]
        sent = []

        def fake_ask(state, questions):
            sent.append(state)
            answers = {}
            for tag in questions:
                text = state["messages"][tag]["text"]
                answers[tag] = {"score": 3.0 if "French" in text or text == "message 2" else 0.2}
            return {"answers": answers}

        scores, reports = cc.jev_scores(messages, summary, limit=2, ask=fake_ask)
        self.assertEqual(len(sent), 3)  # 5 messages, 2 per request
        self.assertTrue(all("m9903" in state["messages"] for state in sent))  # controls ride on every request
        self.assertEqual(set(scores), {m.tag for m in messages})
        self.assertTrue(all(report["ok"] for report in reports))
        self.assertEqual(cc.flags(scores), {"m0002": 3})

    def test_failing_control_is_reported(self):
        summary = "x" * 100
        report = cc.jev_scores([cc.Message("m0001", "user", "hi")], summary, 20,
                               ask=lambda state, questions: {"answers": {t: {"score": 0.0} for t in questions}})[1]
        self.assertFalse(report[0]["ok"])

    def test_flag_rounding(self):
        self.assertEqual(cc.flags({"a": 1.4, "b": 1.6, "c": 2.4, "d": 2.6}), {"b": 2, "c": 2, "d": 3})


class DeepSeekPass(unittest.TestCase):
    def test_prompt_order_and_re2(self):
        prompt = cc.user_prompt([cc.Message("m0001", "user", "hi")], "SUM", {"m0001": 3})
        heads = [prompt.index(head) for head in ("## INTRO", "## DEFINITIONS", "## LOG", "## SUMMARY", "## FLAGS",
                                                 "## TASK", "Read the task again:")]
        self.assertEqual(heads, sorted(heads))
        self.assertIn("[m0001] user: hi", prompt)
        self.assertIn("<m0001 3>", prompt)
        self.assertEqual(prompt.count(cc.TASK), 2)

    def test_sections_and_compare(self):
        reply = ("**DROPPED**\n[m0002] lost the port\nm0005 lost a rule\n\n## WRONG:\n(m0007) summary says x\n"
                 "FLAGGED BUT COVERED\nm0003 \"phrase\"\n")
        parsed = cc.sections(reply)
        self.assertEqual(cc.tags_in(parsed["DROPPED"]), {"m0002", "m0005"})
        self.assertEqual(cc.tags_in(parsed["WRONG"]), {"m0007"})
        report = cc.compare({"m0002": 2, "m0003": 3}, {"off": reply, "on": "DROPPED\nm0002 x\n"})
        self.assertIn("Jev missed (DeepSeek found, Jev didn't flag): ['m0005', 'm0007']", report)
        self.assertIn("Jev over-fired (flagged, DeepSeek says covered): ['m0003']", report)
        self.assertIn("only with thinking off: ['m0005', 'm0007']", report)


if __name__ == "__main__":
    unittest.main()
