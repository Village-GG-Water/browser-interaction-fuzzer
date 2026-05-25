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
        self.reuse_browser = bool_env("SIMULATOR_REUSE_BROWSER")
        self.browser: Browser | None = None

    def open_context(self, profile_dir: Path) -> tuple[Browser, BrowserContext]:
        if not self.reuse_browser:
            return launch_context(self.pw, self.config, profile_dir)

        if self.browser is None or not is_browser_connected(self.browser):
            self.browser = launch_browser(self.pw, self.config)
        return self.browser, self.browser.new_context()

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
        if discard_browser and browser is self.browser:
            self.browser = None

    def close(self) -> None:
        if self.browser:
            try:
                self.browser.close()
            except Exception:
                pass
            self.browser = None

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

def is_browser_connected(browser: Browser) -> bool:
    try:
        return browser.is_connected()
    except Exception:
        return False

def bool_env(name: str) -> bool:
    value = os.environ.get(name, "")
    return value.strip().lower() in {"1", "true", "yes", "on"}

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
