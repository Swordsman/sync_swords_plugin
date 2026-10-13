"""Unit tests for winnow.py — transcript parsing, form extraction, and the
procedural normalizer (id assignment, remapping, dedup, rejection), plus a
full replay-mode run of the orchestrator loop."""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from fold import Graph, parse, tokenize, sx  # noqa: E402
from winnow import (Normalizer, extract_forms, parse_transcript,  # noqa: E402
                    render_delta, replay_client, run)


def graph_from(src):
    g = Graph()
    for form in parse(tokenize(src)):
        g.apply(form)
    return g


class TestTranscript(unittest.TestCase):
    def test_parse_blocks(self):
        turns = parse_transcript(
            "[t1 user]\nhello\nworld\n\n[t2 assistant]\nreply\n")
        self.assertEqual(turns, [(1, "user", "hello\nworld"),
                                 (2, "assistant", "reply")])

    def test_ignores_preamble(self):
        turns = parse_transcript("junk before\n[t1 user]\nbody")
        self.assertEqual(len(turns), 1)


class TestExtractForms(unittest.TestCase):
    def test_pulls_ops_from_prose(self):
        text = ('Here are my notes:\n'
                '(add (claim x1 (has a b) :by user :src t1))\n'
                'and also\n(term foo :gloss "bar (baz)")\nDone!')
        forms = extract_forms(text)
        self.assertEqual([f[0] for f in forms], ["add", "term"])

    def test_unwraps_delta_wrapper(self):
        text = '(delta :turn 3 (add (claim x1 (has a b))) (del c9))'
        forms = extract_forms(text)
        self.assertEqual([f[0] for f in forms], ["add", "del"])

    def test_drops_unknown_heads_and_garbage(self):
        forms = extract_forms("(hello world) (add (claim x1 (p q))) (broken")
        self.assertEqual(len(forms), 1)


class TestNormalizer(unittest.TestCase):
    def test_serial_ids_continue_from_graph(self):
        g = graph_from("(delta :turn 1 "
                       "(add (claim c4 (has a b) :by user :src t1)))")
        ops, rejects = Normalizer(g).normalize(
            extract_forms('(add (claim x1 (has c d) :by user :src t2))'))
        self.assertEqual(ops[0][1][1], "c5")
        self.assertEqual(rejects, [])

    def test_placeholder_remap_in_edges(self):
        g = Graph()
        ops, rejects = Normalizer(g).normalize(extract_forms(
            '(add (claim x1 (has a b) :by user :src t1))'
            '(add (question x2 (is c d) :by user :src t1))'
            '(add (edge (answers x1 x2)))'))
        self.assertEqual(sx(ops[2]), "(add (edge (answers c1 q1)))")

    def test_r11_dedup_identical_payload(self):
        g = graph_from("(delta :turn 1 "
                       "(add (claim c1 (has a b) :by user :src t1)))")
        ops, _ = Normalizer(g).normalize(
            extract_forms('(add (claim x1 (has a b) :by user :src t3))'))
        self.assertEqual(ops, [])

    def test_r11_status_change_becomes_update(self):
        g = graph_from("(delta :turn 1 "
                       "(add (question q1 (is a b) :by user :src t1)))")
        ops, _ = Normalizer(g).normalize(extract_forms(
            '(add (question x1 (is a b) :status answered :by user :src t2))'))
        self.assertEqual(sx(ops[0]), "(update q1 :status answered)")

    def test_dedup_then_edge_targets_existing_node(self):
        g = graph_from("(delta :turn 1 "
                       "(add (claim c1 (has a b) :by user :src t1))"
                       "(add (question q1 (is c d) :by user :src t1)))")
        ops, _ = Normalizer(g).normalize(extract_forms(
            '(add (claim x9 (has a b) :by user :src t2))'
            '(add (edge (answers x9 q1)))'))
        self.assertEqual(sx(ops[0]), "(add (edge (answers c1 q1)))")

    def test_reject_unknown_refs(self):
        ops, rejects = Normalizer(Graph()).normalize(
            extract_forms('(update zz :status live)'
                          '(add (edge (supports aa bb)))'))
        self.assertEqual(ops, [])
        self.assertEqual(len(rejects), 2)

    def test_about_targets_term_accepted(self):
        g = graph_from(
            '(delta :turn 1 (term alpha :gloss "a")'
            '(add (question q1 (is x y) :by user :src t1)))')
        ops, rejects = Normalizer(g).normalize(
            extract_forms('(add (edge (about q1 alpha)))'))
        self.assertEqual(rejects, [])
        self.assertEqual(sx(ops[0]), "(add (edge (about q1 alpha)))")

    def test_about_targets_new_term_in_same_batch(self):
        g = graph_from(
            '(delta :turn 1 (add (question q1 (is x y) :by user :src t1)))')
        ops, rejects = Normalizer(g).normalize(
            extract_forms('(term beta :gloss "b")'
                          '(add (edge (about q1 beta)))'))
        self.assertEqual(rejects, [])

    def test_non_about_edge_to_term_rejected(self):
        g = graph_from(
            '(delta :turn 1 (term alpha :gloss "a")'
            '(add (question q1 (is x y) :by user :src t1)))')
        ops, rejects = Normalizer(g).normalize(
            extract_forms('(add (edge (supports q1 alpha)))'))
        self.assertEqual(len(rejects), 1)
        self.assertIn("dangling", rejects[0])

    def test_annotation_order_enforced(self):
        ops, _ = Normalizer(Graph()).normalize(extract_forms(
            '(add (claim x1 (has a b) :src t1 :by user :conf 0.7))'))
        self.assertEqual(
            sx(ops[0]),
            "(add (claim c1 (has a b) :conf 0.7 :by user :src t1))")

    def test_term_dedup_against_registry(self):
        g = graph_from('(delta :turn 1 (term foo :gloss "x"))')
        ops, _ = Normalizer(g).normalize(extract_forms(
            '(term foo :gloss "x")(term bar :gloss "y")'))
        self.assertEqual([op[1] for op in ops], ["bar"])

    def test_term_canon_passthrough(self):
        g = Graph()
        ops, _ = Normalizer(g).normalize(extract_forms(
            '(term dbc :gloss "design by contract" :canon "Design_by_contract")'))
        self.assertEqual(ops[0][0], "term")
        self.assertEqual(ops[0][1], "dbc")
        from fold import anns as _anns
        ta = _anns(ops[0][2:])
        self.assertEqual(ta["canon"], "Design_by_contract")
        self.assertEqual(ta["gloss"], "design by contract")

    def test_term_canon_folds_into_graph(self):
        g = Graph()
        g.apply(parse(tokenize(
            '(delta :turn 1 '
            '(term dbc :gloss "design by contract" :canon "Design_by_contract")'
            '(add (claim c1 (uses project dbc) :by user :src t1)))'))[0])
        ta = dict(zip(g.terms["dbc"][::2], g.terms["dbc"][1::2]))
        # fold.py stores raw tail; anns() extracts it
        from fold import anns as _anns
        parsed = _anns(list(g.terms["dbc"]))
        self.assertEqual(parsed["canon"], "Design_by_contract")

    def test_edge_dedup(self):
        g = graph_from("(delta :turn 1 "
                       "(add (claim c1 (has a b) :by user :src t1))"
                       "(add (claim c2 (has c d) :by user :src t1))"
                       "(add (edge (supports c1 c2))))")
        ops, _ = Normalizer(g).normalize(
            extract_forms('(add (edge (supports c1 c2)))'))
        self.assertEqual(ops, [])

    def test_dangling_key_rejected_not_fatal(self):
        # seen live (DeepSeek flash, 2026-10-13): a key with no value after
        # it used to crash the whole run inside anns()
        ops, rejects = Normalizer(Graph()).normalize(extract_forms(
            '(add (claim x1 (has a b) :by))\n'
            '(add (claim x2 (has c d) :by user :src t1))'))
        self.assertEqual([op[1][1] for op in ops], ["c1"])
        self.assertTrue(any("without a value" in r for r in rejects))


FIXTURE = """\
(add (claim x1 (causes thing risk) :by user :src t1))
(add (question x2 (design system) :by user :src t1))
%%%
(term thing :gloss "the thing under discussion")
(add (claim x1 (causes thing risk) :by user :src t1))
(add (question x2 (design system) :by user :src t1))
%%%
(add (decision y1 (implement system approach) :by assistant :src t2))
(add (edge (answers y1 q1)))
(update q1 :status answered)
(add (claim x1 (causes thing risk) :by user :src t1))
%%%
(add (decision y1 (implement system approach) :by assistant :src t2))
(add (edge (answers y1 q1)))
(update q1 :status answered)
(add (claim x1 (causes thing risk) :by user :src t1))
"""

TRANSCRIPT = """\
[t1 user]
The thing causes risk. How should we design the system?

[t2 assistant]
I'd implement the system with this approach. Also, the thing causes risk.
"""


class TestSdkClientRequest(unittest.TestCase):
    """The anthropic-SDK backends: max effort, full output capacity, no cap
    (Joe, 2026-10-13). A stand-in `anthropic` module records the request."""

    def request_for(self, **kw):
        import types
        from winnow import anthropic_client
        seen = {}

        class Stream:
            def __init__(self, **req):
                seen.update(req)

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def get_final_message(self):
                return types.SimpleNamespace(content=[types.SimpleNamespace(type="text", text="ok")])

        fake = types.ModuleType("anthropic")
        fake.Anthropic = lambda **_: types.SimpleNamespace(
            messages=types.SimpleNamespace(stream=Stream))
        saved = sys.modules.get("anthropic")
        sys.modules["anthropic"] = fake
        try:
            self.assertEqual(anthropic_client("m", **kw)("sys", "hi"), "ok")
        finally:
            if saved is None:
                sys.modules.pop("anthropic")
            else:
                sys.modules["anthropic"] = saved
        return seen

    def test_claude_gets_max_effort_and_full_capacity(self):
        req = self.request_for()
        self.assertEqual(req["output_config"], {"effort": "max"})
        self.assertEqual(req["max_tokens"], 128000)

    def test_deepseek_gets_its_full_capacity(self):
        from winnow import MAX_OUTPUT_TOKENS
        req = self.request_for(max_tokens=MAX_OUTPUT_TOKENS["deepseek"])
        self.assertEqual(req["max_tokens"], 393216)


class TestDeepseekEffort(unittest.TestCase):
    """winnow runs think at max unless told otherwise (Joe, 2026-10-13)."""

    def argv_for(self, **kw):
        from winnow import deepseek_client
        with tempfile.TemporaryDirectory() as d:
            fake, log = os.path.join(d, "ds"), os.path.join(d, "argv")
            with open(fake, "w") as f:
                f.write(f"#!{sys.executable}\nimport json, sys\n"
                        f"json.dump(sys.argv[1:], open({log!r}, 'w'))\nprint('ok')\n")
            os.chmod(fake, 0o755)
            self.assertEqual(deepseek_client("flash", ds_path=fake, **kw)("sys", "hi"), "ok")
            import json
            with open(log) as f:
                return json.load(f)

    def test_max_by_default(self):
        argv = self.argv_for()
        self.assertEqual(argv[argv.index("--think") + 1], "max")

    def test_re2_sends_no_effort(self):
        argv = self.argv_for(re2=True)
        self.assertNotIn("--think", argv)
        self.assertIn("--re2", argv)


class TestClaudePolicy(unittest.TestCase):
    """Haiku only with a Sonnet-or-better checker; Sonnet solo or with an
    Opus checker; Opus solo (Joe, 2026-10-13)."""

    def test_allowed(self):
        from winnow import claude_policy_error
        for model, checker in [("haiku", "sonnet"), ("haiku", "opus"),
                               ("sonnet", None), ("sonnet", "opus"),
                               ("opus", None),
                               ("claude-haiku-5-5", "claude-sonnet-5-5"),
                               ("claude-opus-5-5", None)]:
            self.assertIsNone(claude_policy_error(model, checker),
                              (model, checker))

    def test_refused(self):
        from winnow import claude_policy_error
        for model, checker in [("haiku", None), ("haiku", "haiku"),
                               ("claude-haiku-5-5", None),
                               ("sonnet", "haiku"), ("sonnet", "sonnet"),
                               ("opus", "opus"), ("opus", "sonnet"),
                               ("mystery-model", None), ("sonnet", "gpt")]:
            self.assertIsNotNone(claude_policy_error(model, checker),
                                 (model, checker))

    def test_cli_refuses_unchecked_haiku(self):
        import subprocess
        here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        with tempfile.TemporaryDirectory() as d:
            tp = os.path.join(d, "t.txt")
            open(tp, "w").write(TRANSCRIPT)
            r = subprocess.run(
                [sys.executable, os.path.join(here, "winnow.py"), tp,
                 "--out", os.path.join(d, "o.wno"),
                 "--backend", "claude-code", "--model", "haiku"],
                capture_output=True, text=True)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("checker", r.stderr)


class TestClaudeCodeClient(unittest.TestCase):
    """The claude-code backend runs an isolated `claude -p`: no tools, no
    hooks or plugins, max effort, prompt on stdin."""

    def test_isolated_call(self):
        import json
        from winnow import claude_code_client
        with tempfile.TemporaryDirectory() as d:
            fake, log = os.path.join(d, "claude"), os.path.join(d, "seen")
            with open(fake, "w") as f:
                f.write(
                    f"#!{sys.executable}\nimport json, os, sys\n"
                    "a = sys.argv[1:]\n"
                    "system = open(a[a.index('--system-prompt-file') + 1]).read()\n"
                    f"json.dump({{'argv': a, 'stdin': sys.stdin.read(), "
                    "'system': system, 'cwd': os.listdir('.'), "
                    "'raw': os.environ.get('LITTLEWING_RAW'), "
                    "'wno': os.environ.get('LITTLEWING_WNO')}, "
                    f"open({log!r}, 'w'))\nprint('ok')\n")
            os.chmod(fake, 0o755)
            call = claude_code_client("sonnet", claude_path=fake)
            self.assertEqual(call("SYS", "hello"), "ok")
            with open(log) as f:
                seen = json.load(f)
        argv = seen["argv"]
        self.assertEqual(argv[argv.index("--model") + 1], "sonnet")
        self.assertEqual(argv[argv.index("--effort") + 1], "max")
        self.assertEqual(argv[argv.index("--tools") + 1], "")
        self.assertEqual(argv[argv.index("--setting-sources") + 1], "project")
        for flag in ("-p", "--strict-mcp-config", "--disable-slash-commands",
                     "--no-session-persistence"):
            self.assertIn(flag, argv)
        self.assertEqual((seen["stdin"], seen["system"]), ("hello", "SYS"))
        self.assertEqual(seen["cwd"], [])        # nothing for it to load
        self.assertEqual((seen["raw"], seen["wno"]), ("off", "off"))


class TestChecker(unittest.TestCase):
    def test_checker_output_is_what_commits(self):
        extractor = "\n%%%\n".join([
            "(add (claim x1 (causes thing risk) :by user :src t1))\n"
            "(add (claim x9 (causes thing fire) :by user :src t1))",
            "(add (decision y1 (implement system approach) :by assistant :src t2))",
        ])
        checked = "\n%%%\n".join([
            "(add (claim x1 (causes thing risk) :by user :src t1))",
            "(add (decision y1 (implement system approach) :by assistant :src t2))",
        ])
        seen = []
        with tempfile.TemporaryDirectory() as d:
            tp, op = os.path.join(d, "t.txt"), os.path.join(d, "out.wno")
            ep, cp = os.path.join(d, "e.txt"), os.path.join(d, "c.txt")
            open(tp, "w").write(TRANSCRIPT)
            open(ep, "w").write(extractor)
            open(cp, "w").write(checked)
            check = replay_client(cp)
            g = run(tp, op, replay_client(ep), llm_normalize=False,
                    per_turn=True, verbose=False,
                    checker=lambda s, u: seen.append(u) or check(s, u))
        self.assertEqual(set(g.nodes), {"c1", "d1"})
        self.assertIn("(causes thing fire)", seen[0])
        self.assertIn("NEW TURNS:\n[t1 user]", seen[0])
        self.assertIn("CANDIDATE DELTA:", seen[0])


class TestOrchestratorReplay(unittest.TestCase):
    def test_full_loop(self):
        with tempfile.TemporaryDirectory() as d:
            tp = os.path.join(d, "t.txt")
            fp = os.path.join(d, "f.txt")
            op = os.path.join(d, "out.wno")
            open(tp, "w").write(TRANSCRIPT)
            open(fp, "w").write(FIXTURE)
            g = run(tp, op, replay_client(fp), llm_normalize=True,
                    per_turn=True, verbose=False)
            # t1: c1 + q1; t2: d1 + answers edge + q1 update;
            # restated claim deduped both times
            self.assertEqual(set(g.nodes), {"c1", "q1", "d1"})
            self.assertEqual(g.nodes["q1"]["status"], "answered")
            self.assertIn(("answers", "d1", "q1"), g.edges)
            self.assertEqual(g.validate(), [])
            # log itself must re-fold to the same graph
            g2 = Graph()
            for form in parse(tokenize(open(op).read())):
                if form[0] == "meta":
                    g2.set_meta(form)
                else:
                    g2.apply(form)
            self.assertEqual(set(g2.nodes), set(g.nodes))
            self.assertEqual(sorted(g2.edges), sorted(g.edges))


class TestRenderDelta(unittest.TestCase):
    def test_render_parses_back(self):
        ops = [["term", "foo", ":gloss", "x"],
               ["add", ["claim", "c1", ["has", "a", "b"],
                        ":by", "user", ":src", "t1"]]]
        text = render_delta(4, ops)
        form = parse(tokenize(text))[0]
        self.assertEqual(form[0], "delta")
        self.assertEqual(form[2], "4")


if __name__ == "__main__":
    unittest.main()
