import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest import mock

import httpx

import fetch
from fetch import (
    ExtractedPage,
    FetchedPage,
    UnsupportedContent,
    UrlBlocked,
    extract_page,
    fetch_page,
    is_public_ip,
    validate_url,
)

REAL_VALIDATE = fetch.validate_url


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


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/ok":
            body = b"<html><head><title>OK</title></head><body><p>hello page</p></body></html>"
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
        elif self.path == "/redirect-private":
            self.send_response(302)
            self.send_header("Location", "http://169.254.169.254/latest/meta-data")
            self.end_headers()
            return
        elif self.path == "/pdf":
            body = b"%PDF-1.4"
            self.send_response(200)
            self.send_header("Content-Type", "application/pdf")
        elif self.path == "/big":
            body = b"x" * (3 * 1024 * 1024)
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
        elif self.path == "/slow":
            time.sleep(1.5)
            body = b"slow"
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
        else:
            self.send_response(404)
            body = b"missing"
            self.send_header("Content-Type", "text/plain")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def log_message(self, *args):
        pass


class FetchTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        cls.server.daemon_threads = True
        cls.port = cls.server.server_address[1]
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()

    def allow_local(self, url):
        if url.startswith(f"http://127.0.0.1:{self.port}/"):
            return url
        return REAL_VALIDATE(url)

    def test_fetches_html(self):
        with mock.patch("fetch.validate_url", self.allow_local):
            page = fetch_page(f"http://127.0.0.1:{self.port}/ok")
        self.assertEqual(page.status, 200)
        self.assertIn("hello page", page.html)
        self.assertFalse(page.truncated)

    def test_blocks_redirect_to_metadata_address(self):
        with mock.patch("fetch.validate_url", self.allow_local):
            with self.assertRaises(fetch.UrlBlocked):
                fetch_page(f"http://127.0.0.1:{self.port}/redirect-private")

    def test_rejects_pdf(self):
        with mock.patch("fetch.validate_url", self.allow_local):
            with self.assertRaises(UnsupportedContent):
                fetch_page(f"http://127.0.0.1:{self.port}/pdf")

    def test_truncates_large_body(self):
        with mock.patch("fetch.validate_url", self.allow_local):
            page = fetch_page(f"http://127.0.0.1:{self.port}/big")
        self.assertTrue(page.truncated)
        self.assertLessEqual(len(page.html.encode("utf-8")), 2 * 1024 * 1024)

    def test_times_out_slow_host(self):
        with mock.patch("fetch.validate_url", self.allow_local):
            with self.assertRaises(httpx.TimeoutException):
                fetch_page(f"http://127.0.0.1:{self.port}/slow", timeout=0.2)
