import json
import unittest
from unittest import mock

import httpx

import search
from search import SearchError, TTLCache, parse_searxng, search_web

SEARXNG_JSON = json.dumps({
    "results": [
        {
            "title": "GitHub - moeru-ai/airi",
            "url": "https://github.com/moeru-ai/airi",
            "content": "Self hosted AI companion",
            "engine": "brave",
        },
        {
            "title": "Project AIRI",
            "url": "https://airi.moeru.ai/",
            "content": "Open source cyber companion",
            "engine": "google cse",
        },
        {
            "title": "bad",
            "url": "javascript:alert(1)",
            "content": "no",
        },
    ],
})

EMPTY_JSON = json.dumps({"results": []})

FAILED_JSON = json.dumps({
    "results": [],
    "unresponsive_engines": [
        ["duckduckgo", "CAPTCHA"],
        ["brave", "timeout"],
    ],
})

HUGE_JSON = json.dumps({
    "results": [
        {
            "title": "x" * 1000,
            "url": "https://example.com/x",
            "content": "y" * 2000,
        },
    ],
})


class ParserTest(unittest.TestCase):
    def test_parses_results(self):
        parsed = parse_searxng(SEARXNG_JSON)
        self.assertEqual(len(parsed.hits), 2)
        self.assertEqual(parsed.hits[0].title, "GitHub - moeru-ai/airi")
        self.assertEqual(parsed.hits[0].url, "https://github.com/moeru-ai/airi")
        self.assertEqual(parsed.hits[0].snippet, "Self hosted AI companion")

    def test_skips_invalid_urls(self):
        parsed = parse_searxng(SEARXNG_JSON)
        self.assertNotIn("javascript:alert(1)", [hit.url for hit in parsed.hits])

    def test_invalid_json_raises_search_error(self):
        with self.assertRaises(SearchError):
            parse_searxng("<html>not json</html>")

    def test_caps_result_fields(self):
        parsed = parse_searxng(HUGE_JSON)
        self.assertEqual(len(parsed.hits[0].title), 300)
        self.assertEqual(len(parsed.hits[0].snippet), 500)


def clear_cache():
    search._CACHE.clear()


class SearchTest(unittest.TestCase):
    def setUp(self):
        clear_cache()

    def test_uses_searxng(self):
        with mock.patch("search._fetch_searxng", return_value=SEARXNG_JSON) as fetch:
            result = search_web("airi")
        self.assertEqual(result.engine, "searxng")
        self.assertEqual(len(result.hits), 2)
        self.assertIn("format=json", fetch.call_args.args[0])

    def test_returns_empty_result(self):
        with mock.patch("search._fetch_searxng", return_value=EMPTY_JSON):
            result = search_web("nothing")
        self.assertEqual(result.engine, "searxng")
        self.assertEqual(result.hits, [])

    def test_raises_when_all_engines_fail(self):
        with mock.patch("search._fetch_searxng", return_value=FAILED_JSON):
            with self.assertRaises(SearchError) as ctx:
                search_web("airi")
        self.assertIn("duckduckgo", str(ctx.exception))
        self.assertIn("brave", str(ctx.exception))

    def test_does_not_cache_failed_search(self):
        with mock.patch("search._fetch_searxng", return_value=FAILED_JSON):
            with self.assertRaises(SearchError):
                search_web("airi")
        self.assertIsNone(search._CACHE.get(("airi", 5, None)))

    def test_raises_when_searxng_fails(self):
        with mock.patch("search._fetch_searxng", side_effect=SearchError("down")):
            with self.assertRaises(SearchError) as ctx:
                search_web("airi")
        self.assertIn("down", str(ctx.exception))

    def test_maps_timeout(self):
        with mock.patch("search.httpx.get", side_effect=httpx.TimeoutException("slow")):
            with self.assertRaises(SearchError) as ctx:
                search_web("airi")
        self.assertIn("timed out", str(ctx.exception))

    def test_cache_prevents_second_fetch(self):
        with mock.patch("search._fetch_searxng", return_value=SEARXNG_JSON) as fetch:
            search_web("same query")
            search_web("same query")
        self.assertEqual(fetch.call_count, 1)

    def test_ttl_cache_expires(self):
        cache = TTLCache(ttl=10)
        with mock.patch("search.time.monotonic", return_value=100):
            cache.set("k", "v")
        with mock.patch("search.time.monotonic", return_value=105):
            self.assertEqual(cache.get("k"), "v")
        with mock.patch("search.time.monotonic", return_value=111):
            self.assertIsNone(cache.get("k"))

    def test_cache_evicts_old_entries(self):
        cache = TTLCache(ttl=100, max_entries=2)
        cache.set("a", 1)
        cache.set("b", 2)
        cache.set("c", 3)
        self.assertIsNone(cache.get("a"))
        self.assertEqual(cache.get("b"), 2)
        self.assertEqual(cache.get("c"), 3)

    def test_time_range_reaches_searxng(self):
        with mock.patch("search._fetch_searxng", return_value=SEARXNG_JSON) as fetch:
            search_web("airi", time_range="week")
        self.assertIn("time_range=week", fetch.call_args.args[0])

    def test_query_too_long_is_rejected(self):
        with self.assertRaises(SearchError):
            search_web("x" * 501)
