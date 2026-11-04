"""timecheck blocks a typed 'now' ahead of the clock, and nothing else."""
import datetime as dt
import json
import os
import subprocess
import sys
import unittest

SCRIPT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "timecheck.py")


def run(tool, tool_input):
    r = subprocess.run([sys.executable, SCRIPT], input=json.dumps({"tool_name": tool, "tool_input": tool_input}),
                       capture_output=True, text=True)
    return r.returncode, r.stderr


def stamp(minutes):
    t = dt.datetime.now(dt.timezone.utc) + dt.timedelta(minutes=minutes)
    return t.strftime("%Y-%m-%dT%H:%M:%SZ")


class TestTimecheck(unittest.TestCase):
    def test_blocks_a_typed_time_ahead_of_the_clock(self):
        code, err = run("ArtifactData", {"data": {"ts": stamp(16)}})
        self.assertEqual(code, 2)
        self.assertIn("ahead of the clock", err)
        self.assertIn("The clock reads", err)

    def test_minute_stamps_and_utc_suffix(self):
        t = dt.datetime.now(dt.timezone.utc) + dt.timedelta(minutes=10)
        self.assertEqual(run("Write", {"content": "- claimed: " + t.strftime("%Y-%m-%dT%H:%MZ")})[0], 2)
        self.assertEqual(run("Bash", {"command": "echo " + t.strftime("%Y-%m-%d %H:%M:%S UTC")})[0], 2)

    def test_allows_now_past_and_far_future(self):
        for minutes in (0, -30, -600, 60 * 24 * 30):
            self.assertEqual(run("Write", {"content": stamp(minutes)})[0], 0, minutes)

    def test_schedulers_and_marker_pass(self):
        self.assertEqual(run("mcp__claude-code-remote__send_later", {"at": stamp(30)})[0], 0)
        self.assertEqual(run("Write", {"content": stamp(30) + " timecheck:ok"})[0], 0)

    def test_bad_input_never_blocks(self):
        r = subprocess.run([sys.executable, SCRIPT], input="not json", capture_output=True, text=True)
        self.assertEqual(r.returncode, 0)


if __name__ == "__main__":
    unittest.main()
