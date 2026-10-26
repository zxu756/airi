import json
import unittest
from unittest import mock

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


class ParserTest(unittest.TestCase):
    def test_parses_results(self):
        hits = parse_searxng(SEARXNG_JSON)
        self.assertEqual(len(hits), 2)
        self.assertEqual(hits[0].title, "GitHub - moeru-ai/airi")
        self.assertEqual(hits[0].url, "https://github.com/moeru-ai/airi")
        self.assertEqual(hits[0].snippet, "Self hosted AI companion")

    def test_skips_invalid_urls(self):
        hits = parse_searxng(SEARXNG_JSON)
        self.assertNotIn("javascript:alert(1)", [hit.url for hit in hits])

    def test_invalid_json_raises_search_error(self):
        with self.assertRaises(SearchError):
            parse_searxng("<html>not json</html>")


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

    def test_raises_when_searxng_fails(self):
        with mock.patch("search._fetch_searxng", side_effect=SearchError("down")):
            with self.assertRaises(SearchError) as ctx:
                search_web("airi")
        self.assertIn("down", str(ctx.exception))

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

    def test_time_range_reaches_searxng(self):
        with mock.patch("search._fetch_searxng", return_value=SEARXNG_JSON) as fetch:
            search_web("airi", time_range="week")
        self.assertIn("time_range=week", fetch.call_args.args[0])
