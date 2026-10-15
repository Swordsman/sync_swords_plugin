"""Tests for littlewing's session recorder: config layering, transforms,
transcript turns, raw pieces, winnow records, the outbox, and the hook.

Run: python3 -m unittest discover -s scripts/littlewing/tests
"""
import io
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from contextlib import redirect_stdout
from pathlib import Path

LW = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(LW))

import lwconfig  # noqa: E402
import recorder  # noqa: E402
import transcript as tx  # noqa: E402
from backends.transforms import Transform  # noqa: E402
from backends.transports.claude_docs import Outbox  # noqa: E402
import littlewing_hook as hookmod  # noqa: E402

HOOK = LW / "littlewing_hook.py"
CLI = LW / "littlewing.py"
WINNOW = LW.parent / "winnow" / "winnow.py"
DOC = "https://claude.ai/code/artifact/00000000-0000-0000-0000-000000000000"


def ev(role, text, **flags):
    content = text if role == "user" else [{"type": "text", "text": text}]
    return json.dumps({"type": role, "message": {"role": role, "content": content},
                       "timestamp": "2026-10-13T00:00:00Z", **flags}) + "\n"


def tool_result():
    return json.dumps({"type": "user", "message": {"role": "user", "content": [
        {"type": "tool_result", "tool_use_id": "x", "content": "ok"}]}}) + "\n"


class Env:
    """A temp littlewing home + session transcript, and a clean environment."""

    def __init__(self, **cfg):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.home = self.root / "home"
        self.project = self.root / "proj"
        (self.project / ".git").mkdir(parents=True)
        self.session = "11111111-2222-3333-4444-555555555555"
        self.transcript = self.root / f"{self.session}.jsonl"
        self.transcript.write_text("")
        self.env = {"HOME": str(self.root), "XDG_CONFIG_HOME": str(self.root / "xdg"),
                    "LITTLEWING_HOME": str(self.home), "PATH": os.environ.get("PATH", "")}
        if cfg:
            self.env["LITTLEWING_CONFIG_JSON"] = json.dumps(cfg)

    def append(self, *lines):
        with open(self.transcript, "a") as f:
            f.writelines(lines)

    def cfg(self, **extra_env):
        return lwconfig.load(str(self.project), env=dict(self.env, **extra_env))

    def recorder(self, **extra_env):
        return recorder.Recorder(self.cfg(**extra_env), self.session,
                                 str(self.transcript), str(self.project))

    def hook(self, payload, **extra_env):
        payload = dict({"session_id": self.session, "transcript_path": str(self.transcript),
                        "cwd": str(self.project)}, **payload)
        return subprocess.run([sys.executable, str(HOOK)], input=json.dumps(payload),
                              capture_output=True, text=True,
                              env=dict(self.env, **extra_env), timeout=60)

    def close(self):
        self.tmp.cleanup()


class TestConfig(unittest.TestCase):
    def test_defaults_are_off(self):
        e = Env()
        try:
            cfg = e.cfg()
            self.assertFalse(lwconfig.any_enabled(cfg))
            self.assertEqual(cfg["sinks"]["disk"]["root"], str(e.home / "records"))
        finally:
            e.close()

    def test_layers_and_shortcuts(self):
        e = Env(triggers={"stop": {"queued_min_bytes": 5}})
        try:
            (e.project / ".littlewing.json").write_text(json.dumps(
                {"modes": {"wno": {"model": "pro"}}}))
            cfg = e.cfg(LITTLEWING_RAW="docs", LITTLEWING_DOCS=f"{DOC}, {DOC}2")
            self.assertTrue(cfg["modes"]["raw"]["enabled"])
            self.assertEqual(cfg["modes"]["raw"]["sink"], "docs")
            self.assertEqual(cfg["sinks"]["docs"]["docs"], [DOC, DOC + "2"])
            self.assertEqual(cfg["modes"]["wno"]["model"], "pro")       # project file
            self.assertEqual(cfg["triggers"]["stop"]["queued_min_bytes"], 5)  # inline JSON
            self.assertEqual(cfg["triggers"]["stop"]["direct_min_bytes"], 1)  # default kept
            self.assertFalse(e.cfg(LITTLEWING_RAW="off")["modes"]["raw"]["enabled"])
        finally:
            e.close()

    def test_store_chains(self):
        e = Env()
        try:
            cfg = e.cfg(LITTLEWING_RAW="docs", LITTLEWING_WNO="docs", LITTLEWING_DOCS=DOC)
            self.assertEqual(lwconfig.build_store(cfg, "raw").suffix, ".xz.b85")
            self.assertEqual(lwconfig.build_store(cfg, "wno").suffix, "")
            cfg = e.cfg(LITTLEWING_RAW="disk")
            self.assertEqual(lwconfig.build_store(cfg, "raw").suffix, ".xz")
            with self.assertRaises(KeyError):
                lwconfig.build_store(e.cfg(LITTLEWING_RAW="nowhere"), "raw")
        finally:
            e.close()


class TestTransforms(unittest.TestCase):
    def test_armor_roundtrip_and_header(self):
        data = os.urandom(3000)
        xz, b85 = Transform.get("xz")(), Transform.get("base85")()
        b85.label = "raw/r/s/p0001_0-3000.jsonl.xz.b85"
        armored = b85.encode(xz.encode(data))
        armored.decode("ascii")                                   # pure text
        self.assertEqual(b85.header_fields(armored)["key"], b85.label)
        self.assertEqual(xz.decode(b85.decode(armored)), data)
        i = len(armored) - 10                                     # one body byte
        swap = b"!" if armored[i:i + 1] != b"!" else b"#"
        with self.assertRaises(ValueError):
            b85.decode(armored[:i] + swap + armored[i + 1:])
        with self.assertRaises(ValueError):                       # header damaged
            b85.decode(armored.replace(b"sha256=", b"sha2X6=", 1))


class TestTranscript(unittest.TestCase):
    def test_turns_merge_and_filter(self):
        lines = [ev("user", "hi"), ev("user", "skill text", isMeta=True),
                 ev("assistant", "one"), tool_result(), ev("assistant", "two"),
                 ev("assistant", "side", isSidechain=True), ev("user", "next")]
        turns = tx.number_turns(tx.events_from_lines(lines))
        self.assertEqual(turns, [(1, "user", "hi"), (2, "assistant", "one\n\ntwo"),
                                 (3, "user", "next")])
        self.assertIn("[t2 assistant]\none", tx.render_winnow(turns))

    def test_only_the_person_speaks_as_user(self):
        # seen 2026-10-13: a background-task notification, XML ids and paths,
        # rendered as a user turn and was attributed to the user
        note = "<task-notification>\n<task-id>b5i4</task-id>\n</task-notification>"
        lines = [ev("user", "hi", origin={"kind": "human"}), ev("assistant", "one"),
                 ev("user", note, origin={"kind": "task-notification"}),
                 ev("assistant", "two"), ev("user", "older log, no origin")]
        turns = tx.number_turns(tx.events_from_lines(lines))
        self.assertEqual(turns, [(1, "user", "hi"), (2, "assistant", "one\n\ntwo"),
                                 (3, "user", "older log, no origin")])

    def test_closed_turns(self):
        t = [(1, "user", "q"), (2, "assistant", "a b"), (3, "user", "q2"),
             (4, "assistant", "partial")]
        self.assertEqual([x[0] for x in tx.closed_turns(t)], [1, 2])
        self.assertEqual([x[0] for x in tx.closed_turns(t, "partial")], [1, 2, 3, 4])
        self.assertEqual([x[0] for x in tx.closed_turns(t, "other")], [1, 2])
        self.assertEqual([x[0] for x in tx.closed_turns(t, final=True)], [1, 2, 3, 4])
        self.assertEqual(tx.closed_turns(t[:3], final=True), t[:2])   # never ends on a question


class TestClassify(unittest.TestCase):
    def post(self, tool, **ti):
        return hookmod.classify({"hook_event_name": "PostToolUse", "tool_name": tool,
                                 "tool_input": ti})

    def test_triggers(self):
        self.assertEqual(self.post("Bash", command="git push -u origin br"), "push")
        self.assertEqual(self.post("Bash", command="cd x && git -C repo push"), "push")
        self.assertEqual(self.post("Bash", command="git --no-pager push"), "push")
        self.assertIsNone(self.post("Bash", command="git stash push -m wip"))
        self.assertIsNone(self.post("Bash", command="git status"))
        self.assertEqual(self.post("Bash", command="gh pr create --fill"), "pr")
        self.assertEqual(self.post("mcp__github__create_pull_request"), "pr")
        self.assertIsNone(self.post("Read"))
        for event, trig in [("Stop", "stop"), ("PreCompact", "compact"),
                            ("SessionEnd", "session_end"), ("SessionStart", "session_start")]:
            self.assertEqual(hookmod.classify({"hook_event_name": event}), trig)
        self.assertIsNone(hookmod.classify({}))


class TestRaw(unittest.TestCase):
    def test_pieces_are_contiguous_and_restore(self):
        e = Env()
        try:
            e.append(ev("user", "hello"), ev("assistant", "world"))
            e.recorder(LITTLEWING_RAW="disk").run("manual")
            e.append(ev("user", "more"))
            with open(e.transcript, "a") as f:
                f.write('{"type": "user", "partial')               # incomplete line
            r = e.recorder(LITTLEWING_RAW="disk")
            r.run("push")
            pieces = sorted((e.home / "records").rglob("p*.jsonl.xz"))
            self.assertEqual(len(pieces), 2)
            self.assertRegex(pieces[0].name, r"^p0001_0-\d+\.jsonl\.xz$")
            out = e.root / "restored.jsonl"
            res = subprocess.run([sys.executable, str(CLI), "restore",
                                  str(e.home / "records"), "-o", str(out)],
                                 capture_output=True, text=True, env=e.env)
            self.assertEqual(res.returncode, 0, res.stderr)
            whole = e.transcript.read_bytes()
            self.assertEqual(out.read_bytes(), whole[:whole.rfind(b"\n") + 1])
            r.run("push")                                         # nothing new: no piece
            self.assertEqual(len(sorted((e.home / "records").rglob("p*.jsonl.xz"))), 2)
        finally:
            e.close()

    def test_cap_splits_pieces(self):
        e = Env(modes={"raw": {"max_piece_bytes": 300}})
        try:
            e.append(*[ev("user", "x" * 100) for _ in range(6)])
            e.recorder(LITTLEWING_RAW="disk").run("manual")
            pieces = sorted((e.home / "records").rglob("p*.jsonl.xz"))
            self.assertGreater(len(pieces), 2)
        finally:
            e.close()

    def test_stop_threshold_for_queued_sink(self):
        e = Env(triggers={"stop": {"queued_min_bytes": 10_000}})
        try:
            e.append(ev("user", "small"), ev("assistant", "reply"))
            env = dict(LITTLEWING_RAW="docs", LITTLEWING_DOCS=DOC)
            e.recorder(**env).run("stop")
            self.assertEqual(Outbox(str(e.home)).pending(), [])   # under threshold
            e.recorder(**env).run("push")                         # push ignores it
            pend = Outbox(str(e.home)).pending()
            self.assertEqual(len(pend), 1)
            self.assertTrue(pend[0]["id"].endswith(".jsonl.xz.b85.txt"))
            self.assertEqual(pend[0]["docs"], [DOC])
        finally:
            e.close()


class TestOutboxAndHook(unittest.TestCase):
    def test_hook_wakes_once_then_done(self):
        e = Env()
        try:
            env = dict(LITTLEWING_RAW="docs", LITTLEWING_DOCS=DOC)
            e.append(ev("user", "hello"), ev("assistant", "world"))
            push = {"hook_event_name": "PostToolUse", "tool_name": "Bash",
                    "tool_input": {"command": "git push"}}
            r = e.hook(push, **env)
            self.assertEqual(r.returncode, 2, r.stderr)
            self.assertIn("littlewing: 1 session record(s) queued", r.stderr)
            self.assertIn(DOC, r.stderr)
            r = e.hook({"hook_event_name": "Stop", "stop_hook_active": False}, **env)
            self.assertEqual(r.returncode, 0, r.stderr)           # already announced
            start = e.hook({"hook_event_name": "SessionStart"}, **env)
            self.assertIn("queued", start.stdout)                 # startup always lists
            fid = Outbox(str(e.home)).pending()[0]["id"]
            done = subprocess.run([sys.executable, str(CLI), "outbox", "done", fid[:30],
                                   "--asset", "abc123"], capture_output=True, text=True,
                                  env=dict(e.env, **env))
            self.assertEqual(done.returncode, 0, done.stderr)
            self.assertEqual(Outbox(str(e.home)).pending(), [])
            self.assertEqual(Outbox(str(e.home)).sent()[0]["asset"], "abc123")
        finally:
            e.close()

    def test_renotify_after_interval(self):
        e = Env(triggers={"renotify_minutes": 0})
        try:
            cfg = e.cfg(LITTLEWING_RAW="docs", LITTLEWING_DOCS=DOC)
            e.append(ev("user", "a"), ev("assistant", "b"))
            recorder.Recorder(cfg, e.session, str(e.transcript), str(e.project)).run("push")
            text, ids = recorder.notice(cfg)
            Outbox(str(e.home)).mark_announced(ids)
            self.assertIsNotNone(recorder.notice(cfg)[0])          # 0 minutes: due again
        finally:
            e.close()

    def test_off_means_silent(self):
        e = Env()
        try:
            e.append(ev("user", "a"), ev("assistant", "b"))
            r = e.hook({"hook_event_name": "Stop"})
            self.assertEqual((r.returncode, r.stdout, r.stderr), (0, "", ""))
            self.assertFalse(e.home.exists())
        finally:
            e.close()

    def test_compact_never_exits_2(self):
        e = Env()
        try:
            e.append(ev("user", "a"), ev("assistant", "b"))
            r = e.hook({"hook_event_name": "PreCompact"},
                       LITTLEWING_RAW="docs", LITTLEWING_DOCS=DOC)
            self.assertEqual(r.returncode, 0)
            self.assertEqual(len(Outbox(str(e.home)).pending()), 1)
        finally:
            e.close()

    def test_garbage_stdin(self):
        r = subprocess.run([sys.executable, str(HOOK)], input="not json{",
                           capture_output=True, text=True, timeout=30)
        self.assertEqual(r.returncode, 0)


@unittest.skipUnless(WINNOW.is_file(), "winnow not in the plugin")
class TestWno(unittest.TestCase):
    """Real winnow.py in --replay mode: incremental runs ship only new deltas."""

    def test_incremental_parts_join_to_full_record(self):
        e = Env()
        try:
            fixture = e.root / "fixture.txt"
            env = {"LITTLEWING_WNO": "disk", "LITTLEWING_CONFIG_JSON": json.dumps(
                {"modes": {"wno": {"args": ["--replay", str(fixture), "--no-llm-normalizer"]}}})}
            e.append(ev("user", "The thing causes risk."), ev("assistant", "Noted."),
                     ev("user", "Should we use plan alpha?"))
            fixture.write_text("(add (claim x1 (causes thing risk) :by user :src t1))\n")
            e.recorder(**env).run("push")
            e.append(ev("assistant", "Yes, use plan alpha."), ev("user", "thanks"))
            fixture.write_text("(add (decision y1 (use plan alpha) :by assistant :src t4))\n")
            e.recorder(**env).run("push")
            parts = sorted((e.home / "records").rglob("p*.wno"))
            self.assertEqual([p.name for p in parts], ["p0001_t1-t2.wno", "p0002_t3-t4.wno"])
            self.assertTrue(parts[0].read_text().startswith("(meta"))
            self.assertTrue(parts[1].read_text().startswith("(delta :turn 4"))
            log = [json.loads(l) for l in (e.home / "littlewing.log").read_text().splitlines()]
            self.assertEqual([l.get("kind") for l in log if l.get("event") == "shipped"],
                             ["full", "delta"])
            res = subprocess.run([sys.executable, str(CLI), "restore", *map(str, parts)],
                                 capture_output=True, text=True, env=e.env)
            record = (e.home / "state" / e.session / "wno.disk" / "record.wno").read_text()
            sx = recorder._sexpr(WINNOW)
            forms = lambda t: [sx.sx(f) for f in sx.parse(sx.tokenize(t))]  # noqa: E731
            self.assertEqual(forms(res.stdout), forms(record))   # same log, form by form
        finally:
            e.close()


FAKE_WINNOW = r'''
import json, os, re, sys
args = sys.argv[1:]
if os.environ.get("FAKE_ARGV"):
    json.dump(args, open(os.environ["FAKE_ARGV"], "w"))
out = args[args.index("--out") + 1]
log = (open(args[args.index("--seed") + 1]).read().rstrip("\n") if "--seed" in args
       else '(meta :winnow-version "0.2")')
parts = [log]
replies = re.findall(r"^\[t(\d+) assistant\]", open(args[0]).read(), re.M)
for i, t in enumerate(replies):
    parts.append(f"(delta :turn {t} (add (claim c{t} (said t{t}) :by user :src t{t})))")
    open(out, "w").write("\n\n".join(parts) + "\n")       # a valid prefix every batch
    if os.environ.get("FAKE_FAIL") and i == 0:
        sys.exit(1)
'''


class TestRewrittenLog(unittest.TestCase):
    """A container restart makes Claude Code rewrite the session log (seen
    2026-10-13: every line's cwd changed). Offsets stop meaning anything."""

    def raw_pieces(self, e):
        return sorted(str(p.relative_to(e.home / "records"))
                      for p in (e.home / "records").rglob("p*.jsonl.xz"))

    def restore(self, e, *extra):
        out = e.root / "restored.jsonl"
        r = subprocess.run([sys.executable, str(CLI), "restore", str(e.home / "records"),
                            "-o", str(out), *extra], capture_output=True, text=True, env=e.env)
        self.assertEqual(r.returncode, 0, r.stderr)
        return out.read_bytes()

    def test_rewrite_starts_a_new_generation(self):
        e = Env()
        try:
            e.append(ev("user", "hello", cwd="/a"), ev("assistant", "world", cwd="/a"))
            e.recorder(LITTLEWING_RAW="disk").run("manual")
            first = e.transcript.read_bytes()
            # same conversation, every line rewritten, plus a new turn
            e.transcript.write_text(first.decode().replace('"/a"', '"/b"'))
            e.append(ev("user", "again", cwd="/b"))
            r = e.recorder(LITTLEWING_RAW="disk")
            r.run("manual")
            self.assertIn("rewritten", [x["event"] for x in r.results])
            pieces = self.raw_pieces(e)
            self.assertEqual(len(pieces), 2)
            self.assertTrue(pieces[0].split("/")[-2] == "g1" and pieces[1].split("/")[-2] == "g2")
            self.assertEqual(self.restore(e), e.transcript.read_bytes())          # newest
            self.assertEqual(self.restore(e, "--generation", "1"), first)
        finally:
            e.close()

    def test_shrunken_log_is_a_rewrite(self):
        e = Env()
        try:
            e.append(ev("user", "a" * 200), ev("assistant", "b"))
            e.recorder(LITTLEWING_RAW="disk").run("manual")
            e.transcript.write_text(ev("user", "short"))
            r = e.recorder(LITTLEWING_RAW="disk")
            r.run("manual")
            self.assertIn("rewritten", [x["event"] for x in r.results])
        finally:
            e.close()

    def test_growth_alone_stays_in_one_generation(self):
        e = Env()
        try:
            e.append(*[ev("user", "x" * 3000) for _ in range(3)])   # past the 4 KB fingerprint
            e.recorder(LITTLEWING_RAW="disk").run("manual")
            e.append(ev("assistant", "more"))
            r = e.recorder(LITTLEWING_RAW="disk")
            r.run("manual")
            self.assertNotIn("rewritten", [x["event"] for x in r.results])
            self.assertTrue(all("/g1/" in p for p in self.raw_pieces(e)))
        finally:
            e.close()

    def test_wno_continues_when_only_bytes_changed(self):
        e = Env()
        try:
            fake = e.root / "fake_winnow.py"
            fake.write_text(FAKE_WINNOW)
            env = {"LITTLEWING_WNO": "disk", "LITTLEWING_CONFIG_JSON": json.dumps(
                {"modes": {"wno": {"winnow": str(fake)}}})}
            e.append(ev("user", "a", cwd="/a"), ev("assistant", "b", cwd="/a"),
                     ev("user", "c", cwd="/a"))
            e.recorder(**env).run("push")
            e.transcript.write_text(e.transcript.read_text().replace('"/a"', '"/b"'))
            e.append(ev("assistant", "d", cwd="/b"), ev("user", "e", cwd="/b"))
            r = e.recorder(**env)
            r.run("push")
            self.assertNotIn("rewritten", [x["event"] for x in r.results])
            parts = sorted(p.name for p in (e.home / "records").rglob("p*.wno"))
            self.assertEqual(parts, ["p0001_t1-t2.wno", "p0002_t3-t4.wno"])
        finally:
            e.close()

    def test_wno_restarts_when_turns_changed(self):
        e = Env()
        try:
            fake = e.root / "fake_winnow.py"
            fake.write_text(FAKE_WINNOW)
            env = {"LITTLEWING_WNO": "disk", "LITTLEWING_CONFIG_JSON": json.dumps(
                {"modes": {"wno": {"winnow": str(fake)}}})}
            e.append(ev("user", "a"), ev("assistant", "b"), ev("user", "c"))
            e.recorder(**env).run("push")
            e.transcript.write_text("")
            e.append(ev("user", "a"), ev("assistant", "B, edited"), ev("user", "c"),
                     ev("assistant", "d"), ev("user", "e"))
            r = e.recorder(**env)
            r.run("push")
            self.assertIn("rewritten", [x["event"] for x in r.results])
            g2 = sorted(p.name for p in (e.home / "records").rglob("g2/p*.wno"))
            self.assertEqual(g2, ["p0001_t1-t4.wno"])                       # fresh record
        finally:
            e.close()


class TestWnoBackend(unittest.TestCase):
    def test_backend_model_and_checker_reach_winnow(self):
        e = Env()
        try:
            fake, seen = e.root / "fake_winnow.py", e.root / "argv.json"
            fake.write_text(FAKE_WINNOW)
            e.append(ev("user", "a"), ev("assistant", "b"), ev("user", "c"))
            e.recorder(LITTLEWING_WNO="disk", LITTLEWING_CONFIG_JSON=json.dumps(
                {"modes": {"wno": {"winnow": str(fake), "backend": "claude-code",
                                   "model": "haiku", "checker": "sonnet",
                                   "env": {"FAKE_ARGV": str(seen)}}}})).run("push")
            argv = json.loads(seen.read_text())
            for flag, value in (("--backend", "claude-code"), ("--model", "haiku"),
                                ("--checker", "sonnet"), ("--think", "max")):
                self.assertEqual(argv[argv.index(flag) + 1], value)
        finally:
            e.close()


class TestWnoSalvage(unittest.TestCase):
    """winnow failing mid-run: keep the batches it finished, retry the rest."""

    def test_partial_run_ships_what_finished(self):
        e = Env()
        try:
            fake = e.root / "fake_winnow.py"
            fake.write_text(FAKE_WINNOW)

            def env(fail):
                return {"LITTLEWING_WNO": "disk", "LITTLEWING_CONFIG_JSON": json.dumps(
                    {"modes": {"wno": {"winnow": str(fake),
                                       "env": {"FAKE_FAIL": "1"} if fail else {}}}})}
            e.append(ev("user", "a"), ev("assistant", "b"), ev("user", "c"),
                     ev("assistant", "d"), ev("user", "e"))
            r = e.recorder(**env(True))
            r.run("push")
            events = [x["event"] for x in r.results]
            self.assertEqual(events, ["error", "salvaged", "shipped"])
            parts = sorted(p.name for p in (e.home / "records").rglob("p*.wno"))
            self.assertEqual(parts, ["p0001_t1-t2.wno"])
            r = e.recorder(**env(False))                          # next trigger
            r.run("push")
            parts = sorted(p.name for p in (e.home / "records").rglob("p*.wno"))
            self.assertEqual(parts, ["p0001_t1-t2.wno", "p0002_t3-t4.wno"])
            second = (e.home / "records").rglob("p0002*.wno").__next__().read_text()
            self.assertEqual(second.strip(),
                             "(delta :turn 4 (add (claim c4 (said t4) :by user :src t4)))")
        finally:
            e.close()

    def test_nothing_finished_ships_nothing(self):
        e = Env()
        try:
            broken = e.root / "broken_winnow.py"
            broken.write_text("import sys; sys.exit(3)\n")
            e.append(ev("user", "a"), ev("assistant", "b"), ev("user", "c"))
            r = e.recorder(LITTLEWING_WNO="disk", LITTLEWING_CONFIG_JSON=json.dumps(
                {"modes": {"wno": {"winnow": str(broken)}}}))
            r.run("push")
            self.assertEqual([x["event"] for x in r.results], ["error"])
            self.assertEqual(list((e.home / "records").rglob("p*.wno")), [])
        finally:
            e.close()


if __name__ == "__main__":
    unittest.main()
