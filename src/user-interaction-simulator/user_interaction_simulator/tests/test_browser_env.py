import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from user_interaction_simulator.browser_env import BrowserSession


class _FakeContext:
    def __init__(self):
        self.closed = False

    def close(self):
        self.closed = True


class _FakeBrowser:
    def __init__(self):
        self.closed = False
        self.contexts = []

    def is_connected(self):
        return not self.closed

    def new_context(self):
        context = _FakeContext()
        self.contexts.append(context)
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


def _config():
    return {
        "browser_kind": "chromium",
        "browser_path": "/tmp/chromium",
        "sancov_dir": "/tmp/sancov",
        "asan_dir": "/tmp/asan",
        "iteration_timeout_ms": 12000,
    }


class TestBrowserSession(unittest.TestCase):
    def test_default_mode_closes_browser_after_each_context(self):
        pw = _FakePlaywright()
        with patch.dict("os.environ", {"SIMULATOR_REUSE_BROWSER": ""}):
            session = BrowserSession(pw, _config())
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
        with patch.dict("os.environ", {"SIMULATOR_REUSE_BROWSER": "1"}):
            session = BrowserSession(pw, _config())
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


if __name__ == "__main__":
    unittest.main()
