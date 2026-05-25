import unittest
from unittest.mock import patch

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

from user_interaction_simulator.executor import execute_action, safe_url


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


class _Element:
    def __init__(self, exc=None):
        self._exc = exc

    def click(self, timeout=None, button="left"):
        if self._exc:
            raise self._exc


class TestExecuteActionExceptionClassification(unittest.TestCase):
    def test_re_raises_timeout_errors_for_run_testcase_classification(self):
        with patch(
            "user_interaction_simulator.executor.resolve_dom_target",
            return_value=(_Element(PlaywrightTimeoutError("click timeout")), 0),
        ):
            with self.assertRaises(PlaywrightTimeoutError):
                execute_action(None, {"kind": "click"}, 300, {}, None)

    def test_re_raises_crash_like_playwright_errors_for_run_testcase_classification(self):
        with patch(
            "user_interaction_simulator.executor.resolve_dom_target",
            return_value=(_Element(PlaywrightError("Target closed")), 0),
        ):
            with self.assertRaises(PlaywrightError):
                execute_action(None, {"kind": "click"}, 300, {}, None)

    def test_keeps_non_crash_playwright_errors_as_action_failures(self):
        with patch(
            "user_interaction_simulator.executor.resolve_dom_target",
            return_value=(_Element(PlaywrightError("element is not visible")), 0),
        ):
            self.assertEqual(execute_action(None, {"kind": "click"}, 300, {}, None), (False, 0))


if __name__ == "__main__":
    unittest.main()
