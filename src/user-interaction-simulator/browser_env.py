# src/user-interaction-simulator/user_interaction_simulator/browser_env.py
from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import Any

from playwright.sync_api import Browser, BrowserContext, Playwright

def start_playwright() -> Playwright:
    from playwright.sync_api import sync_playwright
    return sync_playwright().start()

class BrowserSession:
    def __init__(self, pw: Playwright, config: dict[str, Any]):
        self.pw = pw
        self.config = config
        self.reuse_browser = bool(config.get("reuse_browser"))
        self.browser: Browser | None = None
        self.browser_launch_id = 0
        self.context_id = 0
        self.last_open_info: dict[str, Any] = {}
        self.last_close_info: dict[str, Any] = {}

    def open_context(self, profile_dir: Path) -> tuple[Browser, BrowserContext]:
        self.last_open_info = {}
        self.last_close_info = {}
        if not self.reuse_browser:
            browser = launch_browser(self.pw, self.config)
            self.browser_launch_id += 1
            context = browser.new_context()
            self._record_open(browser, reused_existing_browser=False)
            return browser, context

        reused_existing_browser = self.browser is not None and is_browser_connected(self.browser)
        if self.browser is None or not is_browser_connected(self.browser):
            self.browser = launch_browser(self.pw, self.config)
            self.browser_launch_id += 1
        context = self.browser.new_context()
        self._record_open(self.browser, reused_existing_browser=reused_existing_browser)
        return self.browser, context

    def close_context(
        self,
        browser: Browser | None,
        context: BrowserContext | None,
        profile_dir: Path,
        discard_browser: bool = False,
    ) -> None:
        close_context(
            browser,
            context,
            profile_dir,
            close_browser=(not self.reuse_browser) or discard_browser,
        )
        self.last_close_info = {
            "open_contexts_after_close": open_context_count(browser),
            "discarded_browser": bool(discard_browser),
        }
        if discard_browser and browser is self.browser:
            self.browser = None

    def close(self) -> None:
        if self.browser:
            try:
                self.browser.close()
            except Exception:
                pass
            self.browser = None

    def diagnostics(self) -> dict[str, Any]:
        return {
            **self.last_open_info,
            **self.last_close_info,
        }

    def _record_open(self, browser: Browser, reused_existing_browser: bool) -> None:
        self.context_id += 1
        self.last_close_info = {}
        self.last_open_info = {
            "reuse_browser": self.reuse_browser,
            "browser_reused": bool(reused_existing_browser),
            "browser_launch_id": self.browser_launch_id,
            "context_id": self.context_id,
            "open_contexts_after_open": open_context_count(browser),
        }

def launch_context(pw: Playwright, config: dict[str, Any], profile_dir: Path) -> tuple[Browser, BrowserContext]:
    browser = launch_browser(pw, config)
    return browser, browser.new_context()

def launch_browser(pw: Playwright, config: dict[str, Any]) -> Browser:
    browser_kind = str(config.get("browser_kind") or "chromium").lower()
    if browser_kind != "chromium":
        raise ValueError(f"unsupported browser_kind for v1: {browser_kind}")

    return pw.chromium.launch(
        executable_path=config["browser_path"],
        headless=True,
        args=browser_args(config),
        env=browser_env(config),
        timeout=config_timeout(config),
    )

def close_context(
    browser: Browser | None,
    context: BrowserContext | None,
    profile_dir: Path,
    close_browser: bool = True,
) -> None:
    if context:
        try:
            context.close()
        except Exception:
            pass
    if browser and close_browser:
        try:
            browser.close()
        except Exception:
            pass
    shutil.rmtree(profile_dir, ignore_errors=True)

def open_context_count(browser: Browser | None) -> int | None:
    if browser is None:
        return None
    try:
        return len(browser.contexts)
    except Exception:
        return None

def is_browser_connected(browser: Browser) -> bool:
    try:
        return browser.is_connected()
    except Exception:
        return False

def browser_env(config: dict[str, Any]) -> dict[str, str]:
    symbolizer = config.get("asan_symbolizer_path")
    asan_opts = (
        "coverage=1"
        f":coverage_dir='{config['sancov_dir']}'"
        f":log_path='{os.path.join(config['asan_dir'], 'asan')}'"
        ":symbolize=1"
        ":fast_unwind_on_fatal=1"
        ":abort_on_error=1"
    )
    if symbolizer:
        asan_opts += f":external_symbolizer_path='{symbolizer}'"

    env = {**os.environ, "ASAN_OPTIONS": asan_opts, "SANCOV_PATH": config["sancov_dir"]}
    if symbolizer:
        env["ASAN_SYMBOLIZER_PATH"] = str(symbolizer)
    return env

def browser_args(config: dict[str, Any]) -> list[str]:
    args = [
        "--no-sandbox",
        "--disable-gpu",
        "--disable-extensions",
        "--disable-background-networking",
        "--disable-default-apps",
        "--disable-sync",
        "--disable-stack-profiler",
        "--disable-translate",
        "--hide-scrollbars",
        "--metrics-recording-only",
        "--mute-audio",
        "--no-first-run",
        "--safebrowsing-disable-auto-update",
        "--disable-dev-shm-usage",
    ]
    if config.get("disable_breakpad", True):
        args.append("--disable-breakpad")
    return args

def config_timeout(config: dict[str, Any]) -> int:
    return int(config.get("iteration_timeout_ms") or 12000)

def path_to_file_url(path: str) -> str:
    value = str(Path(path).resolve()).replace("\\", "/")
    if not value.startswith("/"):
        value = "/" + value
    return "file://" + value
