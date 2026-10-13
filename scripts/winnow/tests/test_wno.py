"""Unit tests for wno.py, the front door, and for fold.py's forwarded view
flags (kept one release)."""
import os
import subprocess
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEMO = os.path.join(ROOT, "demo-deltas.wno")


def run(*args):
    return subprocess.run([sys.executable, *args], capture_output=True,
                          text=True, cwd=ROOT, timeout=60)


class TestWno(unittest.TestCase):
    def test_help_lists_every_command(self):
        r = run("wno.py", "--help")
        self.assertEqual(r.returncode, 0)
        for cmd in ("fold", "frontier", "digest", "query", "extract",
                    "merge", "split", "mega-fold", "term-table"):
            self.assertIn(f"wno.py {cmd}", r.stdout)

    def test_unknown_command(self):
        r = run("wno.py", "frobnicate")
        self.assertEqual(r.returncode, 2)
        self.assertIn("unknown command", r.stderr)

    def test_dispatch_matches_the_script(self):
        for cmd, script, extra in (("frontier", "frontier.py", ["--upto", "4"]),
                                   ("digest", "digest.py", []),
                                   ("fold", "fold.py", ["--snapshot"]),
                                   ("query", "query.py", ["frame=constraint"])):
            via = run("wno.py", cmd, DEMO, *extra)
            direct = run(script, DEMO, *extra)
            self.assertEqual(via.returncode, 0, via.stderr)
            self.assertEqual(via.stdout, direct.stdout, cmd)


class TestForwardedFlags(unittest.TestCase):
    def test_old_flags_still_answer_with_a_note(self):
        for flag, script in (("--frontier", "frontier.py"), ("--digest", "digest.py")):
            old = run("fold.py", DEMO, "--upto", "3", flag)
            new = run(script, DEMO, "--upto", "3")
            self.assertEqual(old.stdout, new.stdout, flag)
            self.assertIn("deprecated", old.stderr)

    def test_old_query_flags(self):
        self.assertEqual(run("fold.py", DEMO, "--query", "frame=claim").stdout,
                         run("query.py", DEMO, "frame=claim").stdout)
        self.assertEqual(run("fold.py", DEMO, "--stale", "2").stdout,
                         run("query.py", DEMO, "--stale", "2").stdout)


if __name__ == "__main__":
    unittest.main()
