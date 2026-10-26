import unittest
from unittest import mock

from fetch import ExtractedPage, UrlBlocked, extract_page, is_public_ip, validate_url


class UrlPolicyTest(unittest.TestCase):
    def test_classifies_public_and_private_ips(self):
        self.assertTrue(is_public_ip("8.8.8.8"))
        self.assertTrue(is_public_ip("2606:4700:4700::1111"))
        self.assertFalse(is_public_ip("127.0.0.1"))
        self.assertFalse(is_public_ip("100.64.0.1"))
        self.assertFalse(is_public_ip("169.254.169.254"))

    def test_blocks_bad_schemes_and_credentials(self):
        for url in ["file:///etc/passwd", "ftp://8.8.8.8/x", "http://u:p@8.8.8.8/"]:
            with self.assertRaises(UrlBlocked):
                validate_url(url)

    def test_blocks_non_public_hosts(self):
        for url in [
            "http://127.0.0.1/",
            "http://10.0.0.1/",
            "http://169.254.169.254/latest/meta-data",
            "http://[::1]/",
        ]:
            with self.assertRaises(UrlBlocked):
                validate_url(url)

    def test_blocks_privileged_ports(self):
        with self.assertRaises(UrlBlocked):
            validate_url("http://8.8.8.8:22/")

    def test_allows_public_addresses(self):
        self.assertEqual(validate_url("https://8.8.8.8/x"), "https://8.8.8.8/x")
        self.assertEqual(validate_url("http://8.8.8.8:8080/"), "http://8.8.8.8:8080/")


ARTICLE = (
    "<html><head><title>Hello</title></head><body><article><h1>Hello</h1><p>"
    + ("word " * 200)
    + "</p></article></body></html>"
)
ARTICLE_ZH = (
    "<html><head><title>中文标题</title></head><body><article><p>"
    + ("这是中文正文。" * 80)
    + "</p></article></body></html>"
)


class ExtractionTest(unittest.TestCase):
    def test_extracts_english_article_and_title(self):
        page = extract_page(ARTICLE, "https://example.com/a")
        self.assertEqual(page.title, "Hello")
        self.assertIn("word", page.text)
        self.assertFalse(page.fallback)

    def test_extracts_chinese_article(self):
        page = extract_page(ARTICLE_ZH, "https://example.com/zh")
        self.assertIn("这是中文正文", page.text)

    def test_uses_fallback_when_trafilatura_returns_nothing(self):
        html = "<html><body><div>Fallback text</div></body></html>"
        with mock.patch("fetch.trafilatura.extract", return_value=None):
            page = extract_page(html, "https://example.com/f")
        self.assertTrue(page.fallback)
        self.assertIn("Fallback text", page.text)

    def test_title_falls_back_to_host(self):
        page = extract_page("<html><body><div>text</div></body></html>", "https://example.com/x")
        self.assertEqual(page.title, "example.com")
