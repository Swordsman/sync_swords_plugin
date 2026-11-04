import io
import json
import os
import pathlib
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from unittest import mock

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

import scripts.drone_uav as drone_uav


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

            drone_uav.cmd_bundle(jobdir, taskfile, [present, missing])

            bundle = _read(os.path.join(jobdir, "bundle.txt"))
            self.assertIn("TASK TEXT", bundle)
            self.assertIn(f"#### FILE {present} (2 lines)", bundle)
            self.assertIn("1: alpha\n", bundle)
            self.assertIn("2: beta\n", bundle)
            self.assertIn(f"#### FILE {missing} (does not exist)", bundle)
            self.assertIn("===RESPONSE FORMAT===", bundle)
            self.assertEqual(bundle.count("===RESPONSE FORMAT==="), 2)
            self.assertLess(
                bundle.index("===RESPONSE FORMAT==="), bundle.index("TASK TEXT")
            )
            self.assertEqual(_read(os.path.join(jobdir, "token.txt")), "")


class BundleTokenTest(unittest.TestCase):
    def _make_bundle(
        self,
        td,
        task_text,
        file_name,
        file_text,
        token_on_collision="grow",
        max_tries=50,
    ):
        jobdir = os.path.join(td, "job")
        taskfile = os.path.join(td, "task.txt")
        file_path = os.path.join(td, file_name)
        _write(taskfile, task_text)
        _write(file_path, file_text)
        drone_uav.cmd_bundle(
            jobdir,
            taskfile,
            [file_path],
            token_on_collision=token_on_collision,
            max_tries=max_tries,
        )
        return jobdir, file_path

    def test_plain_markers_chosen_when_files_are_clean(self):
        with tempfile.TemporaryDirectory() as td:
            jobdir, _ = self._make_bundle(td, "TASK\n", "clean.txt", "hello\n")
            self.assertEqual(_read(os.path.join(jobdir, "token.txt")).strip(), "")
            bundle = _read(os.path.join(jobdir, "bundle.txt"))
            self.assertEqual(bundle.count("===RESPONSE FORMAT==="), 2)
            self.assertEqual(bundle.count("===EDITS==="), 2)

    def test_token_chosen_when_file_contains_plain_markers(self):
        file_text = "===EDITS===\n<<<EDIT foo.txt lines 1-1\n"
        with tempfile.TemporaryDirectory() as td:
            jobdir, file_path = self._make_bundle(
                td, "TASK\n", "collide.txt", file_text
            )
            token = _read(os.path.join(jobdir, "token.txt")).strip()
            self.assertNotEqual(token, "")
            bundle = _read(os.path.join(jobdir, "bundle.txt"))
            self.assertIn(f"===EDITS-{token}===", bundle)
            self.assertIn(f"<<<EDIT-{token}", bundle)

    def test_token_never_appears_in_original_bundled_files(self):
        task_text = "TASK\n"
        file_text = "===EDITS===\nhello\n"
        with tempfile.TemporaryDirectory() as td:
            jobdir, _ = self._make_bundle(
                td, task_text, "collide.txt", file_text
            )
            token = _read(os.path.join(jobdir, "token.txt")).strip()
            self.assertNotEqual(token, "")
            self.assertNotIn(token, task_text)
            self.assertNotIn(token, file_text)

    def test_token_on_collision_fail_raises(self):
        with tempfile.TemporaryDirectory() as td:
            jobdir = os.path.join(td, "job")
            taskfile = os.path.join(td, "task.txt")
            file_path = os.path.join(td, "collide.txt")
            _write(taskfile, "TASK\n")
            _write(file_path, "===EDITS===\n")

            with self.assertRaises(drone_uav.MarkerCollisionError) as cm:
                drone_uav.cmd_bundle(
                    jobdir,
                    taskfile,
                    [file_path],
                    token_on_collision="fail",
                )
            self.assertIn(file_path, str(cm.exception))

    def test_growth_after_max_tries_with_patched_generator(self):
        file_text = "===EDITS===\n===EDITS-always===\n"
        seen_lengths = []

        def fake_generate(length=8):
            seen_lengths.append(length)
            if length == 8:
                return "always"
            return "safe-token"

        with tempfile.TemporaryDirectory() as td:
            jobdir = os.path.join(td, "job")
            taskfile = os.path.join(td, "task.txt")
            file_path = os.path.join(td, "collide.txt")
            _write(taskfile, "TASK\n")
            _write(file_path, file_text)

            with mock.patch.object(drone_uav, "_generate_token", fake_generate):
                drone_uav.cmd_bundle(
                    jobdir,
                    taskfile,
                    [file_path],
                    token_on_collision="grow",
                    max_tries=2,
                )

            self.assertEqual(seen_lengths, [8, 8, 9])
            self.assertEqual(
                _read(os.path.join(jobdir, "token.txt")).strip(), "safe-token"
            )


class WaitTest(unittest.TestCase):
    def test_wait_prints_digest_section(self):
        with tempfile.TemporaryDirectory() as td:
            jobdir = os.path.join(td, "job")
            os.makedirs(jobdir)
            with open(os.path.join(jobdir, "DONE"), "w", encoding="utf-8") as f:
                f.write("")
            with open(os.path.join(jobdir, "finish.txt"), "w", encoding="utf-8") as f:
                f.write("stop")
            _write(
                os.path.join(jobdir, "out.txt"),
                "junk\n===DIGEST===\ndigest text\n",
            )

            buf = io.StringIO()
            with redirect_stdout(buf):
                rc = drone_uav.cmd_wait(jobdir, poll=0.1, timeout=1)

            self.assertEqual(rc, 0)
            self.assertIn("digest text", buf.getvalue())

    def test_wait_missing_digest_prints_first_1500_chars(self):
        with tempfile.TemporaryDirectory() as td:
            jobdir = os.path.join(td, "job")
            os.makedirs(jobdir)
            with open(os.path.join(jobdir, "DONE"), "w", encoding="utf-8") as f:
                f.write("")
            _write(os.path.join(jobdir, "out.txt"), "x" * 2000)

            buf = io.StringIO()
            with redirect_stdout(buf):
                rc = drone_uav.cmd_wait(jobdir, poll=0.1, timeout=1)

            self.assertEqual(rc, 0)
            output = buf.getvalue()
            self.assertIn(
                "(no DIGEST section found; showing first 1500 characters of output)",
                output,
            )
            self.assertIn("x" * 1500, output)


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

            rc = drone_uav.cmd_apply(jobdir, repo, dry_run=False)

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

            rc = drone_uav.cmd_apply(jobdir, repo, dry_run=False)

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

            rc = drone_uav.cmd_apply(jobdir, repo, dry_run=False)

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

            rc = drone_uav.cmd_apply(jobdir, repo, dry_run=False)

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

            rc = drone_uav.cmd_apply(jobdir, repo, dry_run=False)

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

            rc = drone_uav.cmd_apply(jobdir, repo, dry_run=True)

            self.assertEqual(rc, 0)
            self.assertEqual(_read(target), "before\n")
            self.assertFalse(os.path.exists(os.path.join(repo, "new-dry.txt")))
            report = _read(os.path.join(jobdir, "apply_report.txt"))
            self.assertIn("Dry run: yes", report)

    def test_no_edits_section_fails_and_writes_nothing(self):
        with tempfile.TemporaryDirectory() as td:
            repo = os.path.join(td, "repo")
            os.makedirs(repo)
            target = os.path.join(repo, "a.txt")
            _write(target, "A\n")

            jobdir = os.path.join(td, "job")
            _write(
                os.path.join(jobdir, "out.txt"),
                """<<<EDIT a.txt lines 1-1
<<<FIRST
A
>>>NEW
B
>>>END
""",
            )

            with mock.patch.dict(os.environ):
                os.environ.pop("DRONE_UAV_APPLY_MODE", None)
                rc = drone_uav.cmd_apply(jobdir, repo, dry_run=False)

            self.assertEqual(rc, 2)
            self.assertEqual(_read(target), "A\n")
            report = _read(os.path.join(jobdir, "apply_report.txt"))
            self.assertIn("No ===EDITS=== section found", report)

    def test_markers_outside_edits_section_ignored(self):
        with tempfile.TemporaryDirectory() as td:
            repo = os.path.join(td, "repo")
            os.makedirs(repo)
            target = os.path.join(repo, "a.txt")
            _write(target, "A\n")

            jobdir = os.path.join(td, "job")
            _write(
                os.path.join(jobdir, "out.txt"),
                """<<<EDIT outside.txt lines 1-1
<<<FIRST
OUT
>>>NEW
CHANGED
>>>END
===EDITS===
<<<EDIT a.txt lines 1-1
<<<FIRST
A
>>>NEW
B
>>>END
===DIGEST===
done
""",
            )

            rc = drone_uav.cmd_apply(jobdir, repo, dry_run=False)

            self.assertEqual(rc, 0)
            self.assertEqual(_read(target), "B\n")
            self.assertFalse(os.path.exists(os.path.join(repo, "outside.txt")))

    def test_apply_honors_token_txt(self):
        with tempfile.TemporaryDirectory() as td:
            repo = os.path.join(td, "repo")
            os.makedirs(repo)
            target = os.path.join(repo, "a.txt")
            _write(target, "A\n")

            jobdir = os.path.join(td, "job")
            token = "tok123"
            _write(
                os.path.join(jobdir, "out.txt"),
                f"""===EDITS-{token}===
<<<EDIT-{token} a.txt lines 1-1
<<<FIRST-{token}
A
>>>NEW-{token}
B
>>>END-{token}
===DIGEST-{token}===
done
""",
            )
            _write(os.path.join(jobdir, "token.txt"), token)

            rc = drone_uav.cmd_apply(jobdir, repo, dry_run=False)

            self.assertEqual(rc, 0)
            self.assertEqual(_read(target), "B\n")


class ApplyModeTest(unittest.TestCase):
    def _make_repo_with_good_and_bad(self, td):
        repo = os.path.join(td, "repo")
        os.makedirs(repo)
        good = os.path.join(repo, "good.txt")
        bad = os.path.join(repo, "bad.txt")
        _write(good, "GOOD\n")
        _write(bad, "BAD\n")

        jobdir = os.path.join(td, "job")
        out = _out_with_edits(
            """
<<<EDIT good.txt lines 1-1
<<<FIRST
GOOD
>>>NEW
CHANGED
>>>END
<<<EDIT bad.txt lines 1-1
<<<FIRST
WRONG
>>>NEW
CHANGED
>>>END
"""
        )
        _write(os.path.join(jobdir, "out.txt"), out)

        return repo, jobdir, good, bad

    def test_all_or_nothing_default_writes_nothing_when_one_edit_is_bad(self):
        with tempfile.TemporaryDirectory() as td:
            repo, jobdir, good, bad = self._make_repo_with_good_and_bad(td)

            with mock.patch.dict(os.environ):
                os.environ.pop("DRONE_UAV_APPLY_MODE", None)
                rc = drone_uav.cmd_apply(jobdir, repo, dry_run=False)

            self.assertEqual(rc, 2)
            self.assertEqual(_read(good), "GOOD\n")
            self.assertEqual(_read(bad), "BAD\n")

            report = _read(os.path.join(jobdir, "apply_report.txt"))
            self.assertIn("Mode: all-or-nothing", report)
            self.assertIn("All-or-nothing mode: no files were modified", report)

    def test_partial_applies_good_edit_when_one_bad(self):
        with tempfile.TemporaryDirectory() as td:
            repo, jobdir, good, bad = self._make_repo_with_good_and_bad(td)

            with mock.patch.dict(os.environ, {"DRONE_UAV_APPLY_MODE": "partial"}):
                rc = drone_uav.cmd_apply(jobdir, repo, dry_run=False)

            self.assertEqual(rc, 2)
            self.assertEqual(_read(good), "CHANGED\n")
            self.assertEqual(_read(bad), "BAD\n")

            report = _read(os.path.join(jobdir, "apply_report.txt"))
            self.assertIn("Mode: partial", report)
            self.assertIn("Partial mode: accepted edits were applied", report)

    def test_flag_overrides_env(self):
        with tempfile.TemporaryDirectory() as td:
            repo, jobdir, good, bad = self._make_repo_with_good_and_bad(td)

            with mock.patch.dict(os.environ, {"DRONE_UAV_APPLY_MODE": "partial"}):
                rc = drone_uav.cmd_apply(
                    jobdir, repo, dry_run=False, mode="all-or-nothing"
                )

            self.assertEqual(rc, 2)
            self.assertEqual(_read(good), "GOOD\n")
            self.assertEqual(_read(bad), "BAD\n")

            report = _read(os.path.join(jobdir, "apply_report.txt"))
            self.assertIn("Mode: all-or-nothing", report)

    def test_unknown_mode_env_errors(self):
        with tempfile.TemporaryDirectory() as td:
            jobdir = os.path.join(td, "job")
            repo = os.path.join(td, "repo")
            os.makedirs(repo)

            with mock.patch.dict(os.environ, {"DRONE_UAV_APPLY_MODE": "sometimes"}):
                rc = drone_uav.cmd_apply(jobdir, repo, dry_run=False)

            self.assertEqual(rc, 2)
            report = _read(os.path.join(jobdir, "apply_report.txt"))
            self.assertIn("DRONE_UAV_APPLY_MODE", report)
            self.assertIn("sometimes", report)

    def test_dry_run_partial_with_bad_edit(self):
        with tempfile.TemporaryDirectory() as td:
            repo, jobdir, good, bad = self._make_repo_with_good_and_bad(td)

            with mock.patch.dict(os.environ, {"DRONE_UAV_APPLY_MODE": "partial"}):
                rc = drone_uav.cmd_apply(jobdir, repo, dry_run=True)

            self.assertEqual(rc, 2)
            self.assertEqual(_read(good), "GOOD\n")
            self.assertEqual(_read(bad), "BAD\n")

            report = _read(os.path.join(jobdir, "apply_report.txt"))
            self.assertIn("Dry run: yes", report)
            self.assertIn("Mode: partial", report)
            self.assertIn("Applied: 1", report)


class RequestBodyTest(unittest.TestCase):
    def test_request_body_shape_and_hard_rules(self):
        body = drone_uav.build_request_body("hello")

        self.assertEqual(body["model"], drone_uav.DEFAULT_MODEL)
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
