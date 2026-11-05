import base64
import io
import json
import os
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest import mock

import scout

BING = "https://www.bing.com/search?q="


def bing_href(target: str) -> str:
    payload = base64.urlsafe_b64encode(target.encode()).decode().rstrip("=")
    return f"https://www.bing.com/ck/a?!&&p=abc&u=a1{payload}&ntb=1"


class FakePage:
    """Search page + a dict of sites: url -> {"blocks": [(tag, text)], "links": [(text, href)]}."""

    def __init__(self, results: list[tuple[str, str]], sites: dict):
        self.results, self.sites, self.url, self.visits = results, sites, "", []

    def goto(self, url, **_):
        self.url = url
        self.visits.append(url)

    def wait_for_load_state(self, *_, **__):
        pass

    def evaluate(self, script, *_):
        if self.url.startswith(BING):
            return [{"title": title, "href": bing_href(url), "snippet": f"about {title}"} for title, url in self.results]
        site = self.sites[self.url]
        return {"title": f"title of {self.url}", "url": self.url, "fallback": "",
                "blocks": [{"tag": tag, "text": text} for tag, text in site["blocks"]],
                "links": [{"text": text, "href": href} for text, href in site.get("links", [])]}


def fake_jev(page_exists: dict[str, float], navigational: float = 0.0, is_target: float = 0.0, result_score: float = 0.8,
             calls: list | None = None, blocked: float = 0.0):
    """Answers keyed by question-name prefix; page-level `exists` looked up by state.page.url."""

    def answer(state, questions):
        if calls is not None:
            calls.append((state, questions))
        url = state.get("page", {}).get("url", "")
        values = {"exists": page_exists.get(url, 0.0), "navigational": navigational, "is_target": is_target,
                  "injection": 0.0, "blocked": blocked}
        answers = {}
        for name, question in questions.items():
            if question["type"] == "choice":
                first = next(iter(question["criteria"]))
                answers[name] = {"type": "choice", "choice": first, "confidence": 0.9, "probabilities": {first: 0.9}}
            elif name in values:
                answers[name] = {"type": "noul", "noul": values[name]}
            elif name.startswith(("relevant_", "authoritative_")):
                answers[name] = {"type": "noul", "noul": result_score}
            else:  # rel_* blocks and leads_* links
                answers[name] = {"type": "noul", "noul": 0.9 if name.startswith("rel_") else 0.0}
        return {"answers": answers, "usage": {"input_tokens": 1, "output_tokens": 0}, "model": "fake"}

    return answer


class PureFunctions(unittest.TestCase):
    def test_unwrap_bing_decodes_target_and_passes_others_through(self):
        target = "https://example.com/path?a=1&b=two"
        self.assertEqual(scout.unwrap_bing(bing_href(target)), target)
        self.assertEqual(scout.unwrap_bing("https://example.com/x"), "https://example.com/x")
        broken = "https://www.bing.com/ck/a?u=a1%%%%"
        self.assertEqual(scout.unwrap_bing(broken), broken)

    def test_split_long_respects_limit_and_loses_nothing(self):
        text = "Short one. " * 50 + "x" * 2500 + ". Tail sentence here."
        pieces = scout.split_long(text, limit=100)
        self.assertTrue(all(len(piece) <= 100 for piece in pieces))
        self.assertEqual("".join(pieces).replace(" ", ""), text.replace(" ", ""))
        self.assertEqual(scout.split_long("tiny"), ["tiny"])

    def test_number_blocks_assigns_unique_ids_and_sections(self):
        blocks = scout.number_blocks([{"tag": "h2", "text": "Intro"}, {"tag": "p", "text": "a. " * 600}, {"tag": "p", "text": "b"}])
        ids = [block["id"] for block in blocks]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertEqual(blocks[0]["section"], "Intro")
        self.assertTrue(all(block["section"] == "Intro" for block in blocks))
        self.assertGreater(len(blocks), 3)

    def test_sections_are_heading_paths_that_reset_deeper_levels(self):
        tags = [("h1", "Guide"), ("h2", "Install"), ("p", "x"), ("h2", "Use"), ("p", "y"), ("h3", "Click"), ("p", "z"),
                ("h2", "End"), ("p", "w")]
        sections = {block["text"]: block["section"] for block in scout.number_blocks([{"tag": t, "text": s} for t, s in tags])}
        self.assertEqual([sections[text] for text in "xyzw"],
                         ["Guide > Install", "Guide > Use", "Guide > Use > Click", "Guide > End"])

    def test_windows_respect_limits_and_preserve_order(self):
        blocks = [{"id": f"B{index:03d}", "text": "x" * 40} for index in range(25)]
        batches = list(scout.windows(blocks, max_blocks=10, max_chars=200))
        self.assertTrue(all(len(batch) <= 10 and sum(len(block["text"]) for block in batch) <= 200 for batch in batches))
        self.assertEqual([block for batch in batches for block in batch], blocks)

    def test_keywords_drop_filler_and_lead_with_distinctive_terms(self):
        self.assertEqual(scout.keywords("What is the population of Bothell, Washington?"), "Bothell Washington population")
        self.assertEqual(scout.keywords("How do I take a screenshot with Playwright for Python?"), "Playwright Python take screenshot")
        self.assertEqual(scout.keywords("Where is the C# docs page for System.Text.Json?"), "C# System.Text.Json docs page")
        self.assertEqual(scout.keywords("is it?"), "is it?")  # nothing left: fall back to the goal

    def test_verdict_bands(self):
        self.assertEqual([scout.verdict(value) for value in (0.9, 0.7, 0.5, 0.35, 0.1)],
                         ["answered", "answered", "partial", "partial", "absent"])


class JevJunctions(unittest.TestCase):
    def test_judge_window_sends_one_request_with_the_full_question_contract(self):
        calls = []
        window = [{"id": "B000", "text": "alpha"}, {"id": "B001", "text": "beta"}]
        with mock.patch.object(scout, "ask_jev", fake_jev({}, calls=calls)):
            scout.judge_window("goal?", {"title": "t", "url": "u"}, window)
        self.assertEqual(len(calls), 1)
        state, questions = calls[0]
        self.assertEqual(set(state["blocks"]), {"B000", "B001"})
        self.assertTrue({"exists", "navigational", "is_target", "injection", "where", "rel_B000", "rel_B001"} <= set(questions))
        self.assertEqual(questions["where"]["criteria"], {"B000": "`blocks.B000`", "B001": "`blocks.B001`"})
        self.assertIn("`blocks.B001`", questions["rel_B001"]["instructions"])
        self.assertNotIn("alpha", json.dumps(questions))  # untrusted page text stays in state, never in instructions

    def test_judge_window_splits_on_context_overflow(self):
        inner = fake_jev({"u": 0.6})

        def overflowing(state, questions):
            if len(state["blocks"]) > 2:
                raise scout.ContextOverflow("max_tokens_exceeded")
            return inner(state, questions)

        window = [{"id": f"B{index:03d}", "text": str(index)} for index in range(5)]
        with mock.patch.object(scout, "ask_jev", overflowing):
            judgment = scout.judge_window("goal?", {"title": "t", "url": "u"}, window)
        self.assertEqual(set(judgment["relevance"]), {block["id"] for block in window})
        self.assertEqual(judgment["exists"], 0.6)

    def test_is_target_counts_only_for_navigational_goals(self):
        page = FakePage([], {"https://site/a": {"blocks": [("p", "some text")]}})
        for navigational, expected in ((0.2, "absent"), (0.9, "answered")):
            with mock.patch.object(scout, "ask_jev", fake_jev({}, navigational=navigational, is_target=0.9)):
                self.assertEqual(scout.read_page(page, "goal?", "https://site/a")["verdict"], expected)

    def test_read_page_never_sends_blank_state(self):
        page = FakePage([], {"https://site/empty": {"blocks": []}})
        jev = mock.Mock()
        with mock.patch.object(scout, "ask_jev", jev), self.assertRaises(scout.ParseError):
            scout.read_page(page, "goal?", "https://site/empty")
        jev.assert_not_called()

    def test_search_rejects_blank_titles(self):
        page = FakePage([("", "https://site/a")], {})
        with self.assertRaises(scout.ParseError):
            scout.search(page, "query")

    def test_rank_results_discounts_weak_sources_by_up_to_half(self):
        results = [{"title": "t", "url": "u", "snippet": "s"}]
        for authority, expected in ((0.0, 0.4), (1.0, 0.8)):
            answers = {"relevant_R00": {"noul": 0.8}, "authoritative_R00": {"noul": authority}}
            with mock.patch.object(scout, "ask_jev", return_value={"answers": answers}):
                self.assertAlmostEqual(scout.rank_results("goal?", results)[0], expected)


class Transport(unittest.TestCase):
    def setUp(self):
        os.environ["TYPESAFE_API_KEY"] = "test-key"
        scout.SENT_STATES.clear()  # tests reuse states; the repeated-state guard is per run

    def tearDown(self):
        os.environ.pop("TYPESAFE_API_KEY", None)

    @staticmethod
    def http_error(code: int, body: str, headers: dict | None = None):
        return urllib.error.HTTPError(scout.API_URL, code, "err", headers or {}, io.BytesIO(body.encode()))

    def test_retries_rate_limit_then_meters_success(self):
        ok = io.BytesIO(json.dumps({"answers": {}, "usage": {"input_tokens": 42}, "model": "jev-x"}).encode())
        before = scout.METER["input_tokens"]
        with mock.patch("urllib.request.urlopen", side_effect=[self.http_error(429, "slow down", {"retry-after": "0"}), ok]), \
             mock.patch("time.sleep") as sleep:
            scout.ask_jev("s", {"q": scout.noul("?")})
        sleep.assert_called_once_with(0.0)
        self.assertEqual(scout.METER["input_tokens"] - before, 42)

    def test_context_overflow_is_typed(self):
        with mock.patch("urllib.request.urlopen", side_effect=self.http_error(400, '{"detail":"max_tokens_exceeded"}')), \
             self.assertRaises(scout.ContextOverflow):
            scout.ask_jev("s", {"q": scout.noul("?")})

    def test_empty_question_set_is_refused_before_any_request(self):
        with mock.patch("urllib.request.urlopen") as urlopen, self.assertRaises(ValueError):
            scout.ask_jev("s", {})
        urlopen.assert_not_called()

    def test_images_send_assets_with_danger_zone_header(self):
        sent = []
        ok = io.BytesIO(json.dumps({"answers": {}, "usage": {"input_tokens": 1}, "model": "jev-x"}).encode())
        with mock.patch("urllib.request.urlopen", side_effect=lambda request, **_: sent.append(request) or ok):
            scout.ask_jev({"shot": "image-1"}, {"q": scout.noul("?")}, assets={"image-1": {"type": "image"}})
        self.assertEqual(sent[0].get_header("Typesafe-danger-zone-images"), "true")
        self.assertIn("image-1", json.loads(sent[0].data)["assets"])

    def test_look_screenshot_is_placeholder_in_state_and_within_jev_image_limits(self):
        page = mock.Mock(url="https://site/x")
        page.title.return_value = "x"
        page.screenshot.return_value = b"png-bytes"
        captured = {}

        def jev(state, questions, assets):
            captured.update(state=state, questions=questions, assets=assets)
            return {"answers": {name: {"noul": 0.5} for name in questions}}

        with mock.patch.object(scout, "ask_jev", jev):
            report = scout.look(page, "https://site/x", "Is `screenshot` blue?")
        placeholder = captured["state"]["screenshot"]
        self.assertEqual(set(captured["assets"]), {placeholder})
        self.assertEqual(base64.b64decode(captured["assets"][placeholder]["data_base64"]), b"png-bytes")
        width, height = scout.LOOK_VIEWPORT["width"], scout.LOOK_VIEWPORT["height"]
        self.assertTrue(280 <= min(width, height) and max(width, height) <= 1568 and width * height <= 2_458_624)
        self.assertEqual(report["question"], 0.5)

    def test_api_key_prefers_env_then_key_file(self):
        self.assertEqual(scout.api_key(), "test-key")
        os.environ.pop("TYPESAFE_API_KEY")
        with tempfile.NamedTemporaryFile("w", suffix=".key", delete=False) as handle:
            handle.write("file-key\n")
        with mock.patch.dict(os.environ, {"TYPESAFE_KEY_FILE": handle.name}):
            self.assertEqual(scout.api_key(), "file-key")
        os.unlink(handle.name)


class Loop(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.trace_path = Path(self.directory.name) / "trace.jsonl"

    def tearDown(self):
        self.directory.cleanup()

    def sites(self):
        return {url: {"blocks": [("p", f"text of {url}")]} for url in ("https://a", "https://b", "https://c")}

    def test_trace_reload_marks_read_errors_and_redirect_targets_visited(self):
        self.trace_path.write_text("\n".join(json.dumps(entry) for entry in (
            {"step": "read", "url": "https://x/#frag", "final_url": "https://y/"},
            {"step": "error", "url": "https://z"},
            {"step": "search", "query": "q"})))
        self.assertEqual(scout.Trace(str(self.trace_path)).visited, {"https://x", "https://y", "https://z"})

    def test_stops_at_first_answer_and_skips_pages_already_traced(self):
        self.trace_path.write_text(json.dumps({"step": "read", "url": "https://a"}) + "\n")
        page = FakePage([("A", "https://a"), ("B", "https://b"), ("C", "https://c")], self.sites())
        with mock.patch.object(scout, "ask_jev", fake_jev({"https://b": 0.95})):
            report = scout.run_scout(page, "goal?", "query", scout.Trace(str(self.trace_path)))
        self.assertEqual(report["status"], "answered")
        self.assertEqual([entry["url"] for entry in report["visited"]], ["https://b"])
        self.assertNotIn("https://a", page.visits)
        self.assertNotIn("pop", report)

    def test_pops_to_caller_within_page_budget_when_unanswered(self):
        page = FakePage([("A", "https://a"), ("B", "https://b"), ("C", "https://c")], self.sites())
        with mock.patch.object(scout, "ask_jev", fake_jev({})):
            report = scout.run_scout(page, "goal?", "query", scout.Trace(str(self.trace_path)), max_pages=2)
        self.assertEqual(report["status"], "absent")
        self.assertEqual(len(report["visited"]), 2)
        self.assertIn("pop", report)

    def test_seed_urls_are_read_in_order_and_skip_search_without_query(self):
        page = FakePage([("A", "https://a")], self.sites())
        with mock.patch.object(scout, "ask_jev", fake_jev({"https://c": 0.9})):
            report = scout.run_scout(page, "goal?", None, scout.Trace(None), seeds=["https://b", "https://c"])
        self.assertFalse(any(url.startswith(BING) for url in page.visits))
        self.assertEqual(page.visits, ["https://b", "https://c"])
        self.assertEqual(report["status"], "answered")

    def test_needs_a_query_or_seeds(self):
        with self.assertRaises(ValueError):
            scout.run_scout(FakePage([], {}), "goal?", None, scout.Trace(None))

    def test_blocked_pages_are_reported_as_blocked_not_absent(self):
        page = FakePage([("A", "https://a")], self.sites())
        with mock.patch.object(scout, "ask_jev", fake_jev({}, blocked=0.95)):
            report = scout.run_scout(page, "goal?", "query", scout.Trace(str(self.trace_path)), max_pages=1)
        self.assertEqual(report["visited"], [{"url": "https://a", "verdict": "blocked"}])
        self.assertTrue(json.loads(self.trace_path.read_text().splitlines()[-1])["blocked"])

    def test_reads_best_result_even_when_every_snippet_scores_low(self):
        page = FakePage([("A", "https://a"), ("B", "https://b")], self.sites())
        with mock.patch.object(scout, "ask_jev", fake_jev({}, result_score=0.05)):
            report = scout.run_scout(page, "goal?", "query", scout.Trace(None))
        self.assertEqual(len(report["visited"]), 1)


if __name__ == "__main__":
    unittest.main()
