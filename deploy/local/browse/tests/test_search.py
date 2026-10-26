import unittest

from search import decode_bing_url, parse_bing, parse_brave

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

BING = """
<li class="b_algo">
  <h2><a href="https://www.bing.com/ck/a?!&amp;&amp;p=abc&amp;u=a1aHR0cHM6Ly9leGFtcGxlLmNvbS9wYWdl&amp;ntb=1">Example page</a></h2>
  <div class="b_caption"><p>An example snippet.</p></div>
</li>
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

    def test_decodes_bing_redirect(self):
        href = "https://www.bing.com/ck/a?!&&p=abc&u=a1aHR0cHM6Ly9leGFtcGxlLmNvbS9wYWdl&ntb=1"
        self.assertEqual(decode_bing_url(href), "https://example.com/page")

    def test_parses_bing_result_to_real_url(self):
        hits = parse_bing(BING)
        self.assertEqual(len(hits), 1)
        self.assertEqual(hits[0].url, "https://example.com/page")
        self.assertEqual(hits[0].title, "Example page")

    def test_ignores_brave_internal_links(self):
        html = '<div class="snippet"><a href="https://search.brave.com/x"><div class="title search-snippet-title">bad</div></a></div>'
        self.assertEqual(parse_brave(html), [])
