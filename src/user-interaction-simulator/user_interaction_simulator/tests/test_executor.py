import unittest

from playwright.sync_api import Error as PlaywrightError

from user_interaction_simulator.executor import safe_url


class _PageWithUrl:
    def __init__(self, url):
        self._url = url

    @property
    def url(self):
        if isinstance(self._url, Exception):
            raise self._url
        return self._url


class TestSafeUrl(unittest.TestCase):
    def test_returns_current_url(self):
        self.assertEqual(safe_url(_PageWithUrl("https://example.test/")), "https://example.test/")

    def test_returns_empty_string_when_playwright_url_lookup_fails(self):
        self.assertEqual(safe_url(_PageWithUrl(PlaywrightError("page closed"))), "")


if __name__ == "__main__":
    unittest.main()
