"""ds harness: internal self-calls keep prompts out of argv."""
import importlib.machinery
import importlib.util
import os
import subprocess
import sys
import unittest

DS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "ds")


def load_ds():
    loader = importlib.machinery.SourceFileLoader("ds_under_test", DS)
    spec = importlib.util.spec_from_loader("ds_under_test", loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


class TestCallSelf(unittest.TestCase):
    """--help-me-out sends ds its own ~90 KB source; one argument over
    128 KiB fails exec (E2BIG), and argv shows in ps."""

    def test_prompts_go_in_files(self):
        ds = load_ds()
        seen = {}

        def fake_run(cmd, **kw):
            a = cmd[cmd.index("--task-file") + 1]
            s = cmd[cmd.index("--system-file") + 1]
            seen.update(cmd=cmd, kw=kw, task=open(a).read(), system=open(s).read())
            return subprocess.CompletedProcess(cmd, 0, "ok", "")

        real = subprocess.run
        subprocess.run = fake_run
        try:
            big = "x" * 300000
            self.assertEqual(ds._quick_inference(big, "SYSTEM PROMPT"), "ok")
        finally:
            subprocess.run = real
        cmd = seen["cmd"]
        self.assertEqual((seen["task"], seen["system"]), (big, "SYSTEM PROMPT"))
        self.assertFalse(any("xxxx" in a or "SYSTEM PROMPT" in a for a in cmd))
        self.assertEqual(seen["kw"].get("stdin"), subprocess.DEVNULL)
        # this same ds file, not whatever `ds` is on PATH
        self.assertEqual(cmd[:2], [sys.executable, os.path.realpath(DS)])


if __name__ == "__main__":
    unittest.main()
