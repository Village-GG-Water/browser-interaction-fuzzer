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
    def test_keeps_action_timeout_errors_as_action_failures(self):
        with patch(
            "user_interaction_simulator.executor.resolve_dom_target",
            return_value=(_Element(PlaywrightTimeoutError("click timeout")), 0),
        ):
            self.assertEqual(execute_action(None, {"kind": "click"}, 300, {}, None), (False, 0))

    def test_re_raises_iteration_timeout_for_run_testcase_classification(self):
        with patch(
            "user_interaction_simulator.executor.resolve_dom_target",
            return_value=(_Element(PlaywrightTimeoutError("iteration timeout")), 0),
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

    def test_sleep_action_uses_requested_delay_without_deadline(self):
        with patch("user_interaction_simulator.executor.time.sleep") as sleep:
            self.assertEqual(
                execute_action(None, {"kind": "sleep", "millis": 5}, 300, {}, None),
                (True, 0),
            )
        sleep.assert_called_once_with(0.005)

    def test_sleep_action_raises_when_iteration_deadline_has_expired(self):
        with patch("user_interaction_simulator.executor.time.sleep") as sleep:
            with self.assertRaises(PlaywrightTimeoutError):
                execute_action(None, {"kind": "sleep", "millis": 5}, 300, {}, None, deadline=0.0)
        sleep.assert_not_called()


if __name__ == "__main__":
    unittest.main()
