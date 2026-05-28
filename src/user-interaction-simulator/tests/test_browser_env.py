import tempfile
import unittest
from pathlib import Path

import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from browser_env import BrowserSession  # noqa: E402


class _FakeContext:
    def __init__(self, browser):
        self.browser = browser
        self.closed = False

    def close(self):
        self.closed = True


class _FakeBrowser:
    def __init__(self):
        self.closed = False
        self._contexts = []

    @property
    def contexts(self):
        return [context for context in self._contexts if not context.closed]

    def is_connected(self):
        return not self.closed

    def new_context(self):
        context = _FakeContext(self)
        self._contexts.append(context)
        return context

    def close(self):
        self.closed = True


class _FakeChromium:
    def __init__(self):
        self.launches = []

    def launch(self, **kwargs):
        browser = _FakeBrowser()
        self.launches.append((browser, kwargs))
        return browser


class _FakePlaywright:
    def __init__(self):
        self.chromium = _FakeChromium()


def _config(reuse_browser: bool = False):
    return {
        "browser_kind": "chromium",
        "browser_path": "/tmp/chromium",
        "sancov_dir": "/tmp/sancov",
        "asan_dir": "/tmp/asan",
        "iteration_timeout_ms": 12000,
        "reuse_browser": reuse_browser,
    }


class TestBrowserSession(unittest.TestCase):
    def test_default_mode_closes_browser_after_each_context(self):
        pw = _FakePlaywright()
        session = BrowserSession(pw, _config(reuse_browser=False))
        with tempfile.TemporaryDirectory() as tmp:
            first_browser, first_context = session.open_context(Path(tmp) / "p1")
            session.close_context(first_browser, first_context, Path(tmp) / "p1")
            second_browser, second_context = session.open_context(Path(tmp) / "p2")
            session.close_context(second_browser, second_context, Path(tmp) / "p2")

        self.assertEqual(len(pw.chromium.launches), 2)
        self.assertIsNot(first_browser, second_browser)
        self.assertTrue(first_browser.closed)
        self.assertTrue(second_browser.closed)
        self.assertTrue(first_context.closed)
        self.assertTrue(second_context.closed)

    def test_reuse_mode_keeps_browser_between_contexts(self):
        pw = _FakePlaywright()
        session = BrowserSession(pw, _config(reuse_browser=True))
        with tempfile.TemporaryDirectory() as tmp:
            first_browser, first_context = session.open_context(Path(tmp) / "p1")
            session.close_context(first_browser, first_context, Path(tmp) / "p1")
            second_browser, second_context = session.open_context(Path(tmp) / "p2")
            session.close_context(second_browser, second_context, Path(tmp) / "p2")
            session.close()

        self.assertEqual(len(pw.chromium.launches), 1)
        self.assertIs(first_browser, second_browser)
        self.assertTrue(first_browser.closed)
        self.assertTrue(first_context.closed)
        self.assertTrue(second_context.closed)

    def test_reuse_mode_records_context_isolation_diagnostics(self):
        pw = _FakePlaywright()
        session = BrowserSession(pw, _config(reuse_browser=True))
        with tempfile.TemporaryDirectory() as tmp:
            first_browser, first_context = session.open_context(Path(tmp) / "p1")
            self.assertEqual(
                session.diagnostics(),
                {
                    "reuse_browser": True,
                    "browser_reused": False,
                    "browser_launch_id": 1,
                    "context_id": 1,
                    "open_contexts_after_open": 1,
                },
            )
            session.close_context(first_browser, first_context, Path(tmp) / "p1")
            self.assertEqual(session.diagnostics()["open_contexts_after_close"], 0)

            second_browser, second_context = session.open_context(Path(tmp) / "p2")
            self.assertEqual(session.diagnostics()["browser_reused"], True)
            self.assertEqual(session.diagnostics()["browser_launch_id"], 1)
            self.assertEqual(session.diagnostics()["context_id"], 2)
            self.assertEqual(session.diagnostics()["open_contexts_after_open"], 1)
            session.close_context(second_browser, second_context, Path(tmp) / "p2")

        self.assertIs(first_browser, second_browser)
        self.assertEqual(session.diagnostics()["open_contexts_after_close"], 0)


if __name__ == "__main__":
    unittest.main()
