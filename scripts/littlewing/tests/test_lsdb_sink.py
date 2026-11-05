"""Tests for littlewing's lsdb backend, against a fake lsdb module. Run: python3 -m unittest discover -s scripts/littlewing/tests"""
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_recorder import Env, ev  # noqa: E402

import lsdb  # noqa: E402
import lsdb_sink  # noqa: E402

URL = "https://claude.ai/artifact/5BYbd8nH9PUvdUkDqbxLpS"


class TestLsdbSink(unittest.TestCase):
    def setUp(self):
        self.e = Env()
        self.e.append(ev("user", "Plan the migration\nplease"), ev("assistant", "ok"))
        self.calls = []
        record = lambda name: lambda *a, **k: self.calls.append((name, a)) or {}  # noqa: E731
        patches = [mock.patch.object(lsdb, n, record(n)) for n in ("put_blob", "set_doc", "register")]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

    def tearDown(self):
        self.e.close()

    def names(self):
        return [name for name, _ in self.calls]

    def test_off_without_url(self):
        self.e.recorder().run("manual")
        self.assertEqual(self.calls, [])

    def test_session_doc_and_throttle(self):
        rec = self.e.recorder(LITTLEWING_LSDB=URL)
        rec.run("manual")
        self.assertEqual(self.names(), ["set_doc", "register"])
        doc = self.calls[0][1][2]
        self.assertEqual((doc["title"], doc["id"]), ("Plan the migration please", self.e.session))
        self.calls.clear()
        rec.run("stop")                       # within stop_interval: nothing
        self.assertEqual(self.calls, [])

    def test_record_blob_only_when_changed_and_raw_opt_in(self):
        rec = self.e.recorder(LITTLEWING_LSDB=URL, LITTLEWING_CONFIG_JSON='{"lsdb": {"raw": true}}')
        work = rec.state_dir / "wno.disk"
        work.mkdir(parents=True)
        (work / "record.wno").write_text("(delta)\n")
        rec.run("manual")
        self.assertEqual(self.names().count("put_blob"), 2)       # wno + raw
        self.calls.clear()
        rec.run("manual")
        self.assertEqual(self.names(), ["set_doc"])               # unchanged: no re-upload

    def test_compaction_rewrite_keeps_old_raw_blob(self):
        rec = self.e.recorder(LITTLEWING_LSDB=URL, LITTLEWING_CONFIG_JSON='{"lsdb": {"raw": true}}')
        rec.run("manual")
        self.e.transcript.write_text(ev("user", "after compaction"))
        rec.run("manual")
        keys = [a[1] for n, a in self.calls if n == "put_blob"]
        self.assertEqual(keys, [f"raw-{self.e.session}", f"raw-{self.e.session}-g2"])

    def test_failures_are_logged_not_raised(self):
        with mock.patch.object(lsdb, "set_doc", side_effect=lsdb.LsdbEnvError("no session")):
            rec = self.e.recorder(LITTLEWING_LSDB=URL)
            rec.run("manual")
        self.assertEqual(rec.results[-1]["event"], "error")

    def test_over_budget_is_abandoned(self):
        import time
        with mock.patch.object(lsdb, "set_doc", side_effect=lambda *a, **k: time.sleep(2)):
            rec = self.e.recorder(LITTLEWING_LSDB=URL, LITTLEWING_CONFIG_JSON='{"lsdb": {"budget": 0.2}}')
            rec.run("manual")
        self.assertIn("over budget", rec.results[-1]["error"])


if __name__ == "__main__":
    unittest.main()
