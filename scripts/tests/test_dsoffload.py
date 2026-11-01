import json
import os
import pathlib
import sys
import tempfile
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

import scripts.dsoffload as dsoffload


def _write(path: str, text: str) -> None:
    p = pathlib.Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


def _read(path: str) -> str:
    return pathlib.Path(path).read_text(encoding="utf-8")


def _out_with_edits(edits_text: str) -> str:
    return "===EDITS===\n" + edits_text + "\n===DIGEST===\ndone\n"


class BundleTest(unittest.TestCase):
    def test_numbering_and_missing_files(self):
        with tempfile.TemporaryDirectory() as td:
            jobdir = os.path.join(td, "job")
            root = os.path.join(td, "root")
            os.makedirs(root)

            taskfile = os.path.join(td, "task.txt")
            _write(taskfile, "TASK TEXT\n")

            present = os.path.join(root, "present.txt")
            _write(present, "alpha\nbeta\n")
            missing = os.path.join(root, "missing.txt")

            dsoffload.cmd_bundle(jobdir, taskfile, [present, missing])

            bundle = _read(os.path.join(jobdir, "bundle.txt"))
            self.assertIn("TASK TEXT", bundle)
            self.assertIn(f"#### FILE {present} (2 lines)", bundle)
            self.assertIn("1: alpha\n", bundle)
            self.assertIn("2: beta\n", bundle)
            self.assertIn(f"#### FILE {missing} (does not exist)", bundle)
            self.assertIn("===RESPONSE FORMAT===", bundle)


class ApplyTest(unittest.TestCase):
    def test_replace_delete_insert_new(self):
        with tempfile.TemporaryDirectory() as td:
            repo = os.path.join(td, "repo")
            os.makedirs(repo)

            a = os.path.join(repo, "a.txt")
            _write(a, "one\ntwo\n")

            b = os.path.join(repo, "b.txt")
            _write(b, "B1\nB2\n")

            c = os.path.join(repo, "c.txt")
            _write(c, "one\ntwo\nthree\n")

            jobdir = os.path.join(td, "job")
            os.makedirs(jobdir)

            out = _out_with_edits(
                """
<<<EDIT a.txt lines 1-1
<<<FIRST
one
>>>NEW
ONE
>>>END
<<<EDIT a.txt lines 2-2
<<<FIRST
two
>>>NEW
>>>END
<<<EDIT b.txt insert-after 0
<<<FIRST

>>>NEW
TOP
>>>END
<<<EDIT c.txt insert-after 2
<<<FIRST
two
>>>NEW
TWO.5
>>>END
<<<EDIT new.txt new
>>>NEW
hello
world
>>>END
"""
            )
            _write(os.path.join(jobdir, "out.txt"), out)

            rc = dsoffload.cmd_apply(jobdir, repo, dry_run=False)

            self.assertEqual(rc, 0)
            self.assertEqual(_read(a), "ONE\n")
            self.assertEqual(_read(b), "TOP\nB1\nB2\n")
            self.assertEqual(_read(c), "one\ntwo\nTWO.5\nthree\n")
            self.assertEqual(_read(os.path.join(repo, "new.txt")), "hello\nworld")

    def test_first_mismatch_is_refused(self):
        with tempfile.TemporaryDirectory() as td:
            repo = os.path.join(td, "repo")
            os.makedirs(repo)
            target = os.path.join(repo, "file.txt")
            _write(target, "alpha\nbeta\n")

            jobdir = os.path.join(td, "job")
            os.makedirs(jobdir)
            _write(
                os.path.join(jobdir, "out.txt"),
                _out_with_edits(
                    """
<<<EDIT file.txt lines 1-1
<<<FIRST
wrong
>>>NEW
RIGHT
>>>END
"""
                ),
            )

            rc = dsoffload.cmd_apply(jobdir, repo, dry_run=False)

            self.assertEqual(rc, 2)
            self.assertEqual(_read(target), "alpha\nbeta\n")
            report = _read(os.path.join(jobdir, "apply_report.txt"))
            self.assertIn("FIRST does not match line 1", report)

    def test_overlapping_edits_are_refused(self):
        with tempfile.TemporaryDirectory() as td:
            repo = os.path.join(td, "repo")
            os.makedirs(repo)
            target = os.path.join(repo, "file.txt")
            _write(target, "A\nB\nC\n")

            jobdir = os.path.join(td, "job")
            os.makedirs(jobdir)
            _write(
                os.path.join(jobdir, "out.txt"),
                _out_with_edits(
                    """
<<<EDIT file.txt lines 1-2
<<<FIRST
A
>>>NEW
X
>>>END
<<<EDIT file.txt lines 2-3
<<<FIRST
B
>>>NEW
Y
>>>END
"""
                ),
            )

            rc = dsoffload.cmd_apply(jobdir, repo, dry_run=False)

            self.assertEqual(rc, 2)
            self.assertEqual(_read(target), "A\nB\nC\n")
            report = _read(os.path.join(jobdir, "apply_report.txt"))
            self.assertIn("overlaps another edit", report)

    def test_bottom_up_with_two_edits_in_one_file(self):
        with tempfile.TemporaryDirectory() as td:
            repo = os.path.join(td, "repo")
            os.makedirs(repo)
            target = os.path.join(repo, "file.txt")
            _write(target, "A\nB\nC\nD\n")

            jobdir = os.path.join(td, "job")
            os.makedirs(jobdir)
            _write(
                os.path.join(jobdir, "out.txt"),
                _out_with_edits(
                    """
<<<EDIT file.txt lines 2-3
<<<FIRST
B
>>>NEW
X
>>>END
<<<EDIT file.txt insert-after 4
<<<FIRST
D
>>>NEW
END
>>>END
"""
                ),
            )

            rc = dsoffload.cmd_apply(jobdir, repo, dry_run=False)

            self.assertEqual(rc, 0)
            self.assertEqual(_read(target), "A\nX\nD\nEND\n")

    def test_path_escape_is_refused(self):
        with tempfile.TemporaryDirectory() as td:
            repo = os.path.join(td, "repo")
            os.makedirs(repo)
            target = os.path.join(repo, "file.txt")
            _write(target, "A\n")

            jobdir = os.path.join(td, "job")
            os.makedirs(jobdir)
            _write(
                os.path.join(jobdir, "out.txt"),
                _out_with_edits(
                    """
<<<EDIT ../escape.txt lines 1-1
<<<FIRST
A
>>>NEW
B
>>>END
"""
                ),
            )

            rc = dsoffload.cmd_apply(jobdir, repo, dry_run=False)

            self.assertEqual(rc, 2)
            self.assertFalse(os.path.exists(os.path.join(td, "escape.txt")))
            report = _read(os.path.join(jobdir, "apply_report.txt"))
            self.assertIn("path escapes repository", report)

    def test_dry_run_does_not_modify_repo_files(self):
        with tempfile.TemporaryDirectory() as td:
            repo = os.path.join(td, "repo")
            os.makedirs(repo)
            target = os.path.join(repo, "existing.txt")
            _write(target, "before\n")

            jobdir = os.path.join(td, "job")
            os.makedirs(jobdir)
            _write(
                os.path.join(jobdir, "out.txt"),
                _out_with_edits(
                    """
<<<EDIT existing.txt lines 1-1
<<<FIRST
before
>>>NEW
after
>>>END
<<<EDIT new-dry.txt new
>>>NEW
nope
>>>END
"""
                ),
            )

            rc = dsoffload.cmd_apply(jobdir, repo, dry_run=True)

            self.assertEqual(rc, 0)
            self.assertEqual(_read(target), "before\n")
            self.assertFalse(os.path.exists(os.path.join(repo, "new-dry.txt")))
            report = _read(os.path.join(jobdir, "apply_report.txt"))
            self.assertIn("Dry run: yes", report)


class RequestBodyTest(unittest.TestCase):
    def test_request_body_shape_and_hard_rules(self):
        body = dsoffload.build_request_body("hello")

        self.assertEqual(body["model"], dsoffload.DEFAULT_MODEL)
        self.assertTrue(body["stream"])
        self.assertEqual(body["thinking"], {"type": "enabled"})
        self.assertEqual(body["reasoning_effort"], "max")

        self.assertEqual(len(body["messages"]), 1)
        message = body["messages"][0]
        self.assertEqual(message, {"role": "user", "content": "hello"})
        self.assertNotIn("system", message)

        self.assertNotIn("max_tokens", body)
        self.assertNotIn("temperature", body)
        self.assertNotIn("top_p", body)
        self.assertNotIn("system", body)

        json.dumps(body)


if __name__ == "__main__":
    unittest.main()
