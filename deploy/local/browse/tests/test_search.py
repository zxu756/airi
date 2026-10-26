import unittest
from unittest import mock

import search
from search import (
    SearchError,
    TTLCache,
    parse_bing_rss,
    parse_brave,
    search_web,
)

BRAVE = """
<div class="snippet" data-type="web">
  <a href="https://github.com/moeru-ai/airi">
    <div class="title search-snippet-title" title="GitHub - moeru-ai/airi">GitHub - moeru-ai/airi</div>
  </a>
  <div class="generic-snippet"><div class="content">Self hosted AI companion</div></div>
</div>
"""

BRAVE_ZH = """
<div class="snippet">
  <a href="https://example.cn/weather"><div class="title search-snippet-title">北京天气</div></a>
  <div class="generic-snippet"><div class="content">今天晴，二十度。</div></div>
</div>
"""

BING_RSS = """<?xml version="1.0" encoding="utf-8"?>
<rss version="2.0"><channel>
  <item>
    <title>Example page</title>
    <link>https://example.com/page</link>
    <description>An example &amp; snippet.</description>
  </item>
</channel></rss>
"""

EMPTY_RSS = """<?xml version="1.0" encoding="utf-8"?>
<rss version="2.0"><channel></channel></rss>
"""


class ParserTest(unittest.TestCase):
    def test_parses_brave_result(self):
        hits = parse_brave(BRAVE)
        self.assertEqual(len(hits), 1)
        self.assertEqual(hits[0].url, "https://github.com/moeru-ai/airi")
        self.assertIn("moeru-ai", hits[0].title)
        self.assertEqual(hits[0].snippet, "Self hosted AI companion")

    def test_parses_chinese_brave_result(self):
        hits = parse_brave(BRAVE_ZH)
        self.assertEqual(hits[0].title, "北京天气")
        self.assertIn("今天晴", hits[0].snippet)

    def test_ignores_brave_internal_links(self):
        html = '<div class="snippet"><a href="https://search.brave.com/x"><div class="title search-snippet-title">bad</div></a></div>'
        self.assertEqual(parse_brave(html), [])

    def test_parses_bing_rss(self):
        hits = parse_bing_rss(BING_RSS)
        self.assertEqual(len(hits), 1)
        self.assertEqual(hits[0].title, "Example page")
        self.assertEqual(hits[0].url, "https://example.com/page")
        self.assertEqual(hits[0].snippet, "An example & snippet.")


def clear_cache():
    search._CACHE.clear()
    search._LAST_BRAVE = 0.0


class SearchTest(unittest.TestCase):
    def setUp(self):
        clear_cache()

    def test_uses_brave_first(self):
        with mock.patch("search._fetch_brave", return_value=BRAVE) as brave, \
             mock.patch("search._fetch_bing") as bing:
            result = search_web("airi")
        self.assertEqual(result.engine, "brave")
        self.assertEqual(len(result.hits), 1)
        brave.assert_called_once()
        bing.assert_not_called()

    def test_falls_back_to_bing(self):
        with mock.patch("search._fetch_brave", return_value="<html></html>"), \
             mock.patch("search._fetch_bing", return_value=BING_RSS):
            result = search_web("airi")
        self.assertEqual(result.engine, "bing")
        self.assertEqual(result.hits[0].url, "https://example.com/page")

    def test_raises_when_both_engines_fail(self):
        with mock.patch("search._fetch_brave", side_effect=SearchError("429")), \
             mock.patch("search._fetch_bing", side_effect=SearchError("503")):
            with self.assertRaises(SearchError) as ctx:
                search_web("airi")
        self.assertIn("429", str(ctx.exception))
        self.assertIn("503", str(ctx.exception))

    def test_returns_empty_result_when_both_engines_have_no_hits(self):
        with mock.patch("search._fetch_brave", return_value="<html></html>"), \
             mock.patch("search._fetch_bing", return_value=EMPTY_RSS):
            result = search_web("nothing")
        self.assertEqual(result.engine, "none")
        self.assertEqual(result.hits, [])

    def test_cache_prevents_second_fetch(self):
        with mock.patch("search._fetch_brave", return_value=BRAVE) as brave:
            search_web("same query")
            search_web("same query")
        self.assertEqual(brave.call_count, 1)

    def test_ttl_cache_expires(self):
        cache = TTLCache(ttl=10)
        with mock.patch("search.time.monotonic", return_value=100):
            cache.set("k", "v")
        with mock.patch("search.time.monotonic", return_value=105):
            self.assertEqual(cache.get("k"), "v")
        with mock.patch("search.time.monotonic", return_value=111):
            self.assertIsNone(cache.get("k"))

    def test_time_range_maps_to_brave_parameter(self):
        with mock.patch("search._fetch_brave", return_value=BRAVE) as brave:
            search_web("airi", time_range="week")
        self.assertIn("tf=pw", brave.call_args.args[0])

    def test_time_range_maps_to_bing_filter(self):
        with mock.patch("search._fetch_brave", return_value="<html></html>"), \
             mock.patch("search._fetch_bing", return_value=BING_RSS) as bing:
            search_web("airi", time_range="week")
        self.assertIn("filters=ex1%3A%22ez2%22", bing.call_args.args[0])
