import unittest

from fetch import UrlBlocked, is_public_ip, validate_url


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
