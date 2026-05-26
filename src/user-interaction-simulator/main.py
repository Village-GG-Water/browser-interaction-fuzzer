# src/user-interaction-simulator/user_interaction_simulator/main.py
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from .backend_loader import load_backend
from .base import BaseBackend
from .browser_env import BrowserSession, start_playwright
from .executor import run_testcase


def main() -> None:
    parser = argparse.ArgumentParser(description="User interaction simulator")
    sub = parser.add_subparsers(dest="mode")
    sub.add_parser("serve", help="JSON-lines IPC server")
    parser.set_defaults(mode="help")
    args = parser.parse_args()

    if args.mode == "serve":
        serve()
    else:
        parser.print_help()


def serve() -> None:
    config: dict[str, Any] | None = None
    playwright = None
    browser_session: BrowserSession | None = None
    ui_backend: BaseBackend | None = None

    try:
        for raw_line in sys.stdin.buffer:
            line = raw_line.decode("utf-8", errors="replace").strip()
            if not line:
                continue

            try:
                message = json.loads(line)
            except json.JSONDecodeError as exc:
                respond({"status": "error", "error": f"JSON parse error: {exc}"})
                continue

            cmd = message.get("cmd")
            try:
                if cmd == "initialize":
                    config, ui_backend = initialize(message)
                    playwright = start_playwright()
                    browser_session = BrowserSession(playwright, config)
                    respond({"status": "ok"})
                elif cmd == "run_testcase":
                    if config is None or browser_session is None:
                        respond({"status": "error", "reason": "not initialized"})
                        continue
                    respond(run_testcase(browser_session, config, message, ui_backend))
                elif cmd == "shutdown":
                    respond({"status": "ok"})
                    break
                else:
                    respond({"status": "error", "error": f"unknown cmd: {cmd!r}"})
            except Exception as exc:
                respond({"status": "error", "reason": str(exc)[:500]})
    finally:
        if browser_session is not None:
            browser_session.close()
        if playwright is not None:
            playwright.stop()


def initialize(message: dict[str, Any]) -> tuple[dict[str, Any], BaseBackend]:
    required = ["browser_path", "browser_kind", "sancov_dir", "asan_dir", "out_dir"]
    for key in required:
        if not message.get(key):
            raise ValueError(f"missing {key}")

    config = dict(message)
    Path(config["sancov_dir"]).mkdir(parents=True, exist_ok=True)
    Path(config["asan_dir"]).mkdir(parents=True, exist_ok=True)
    Path(config["out_dir"]).mkdir(parents=True, exist_ok=True)
    
    ui_backend = load_backend(message.get("ui_backend"))
    log(f"[simulator] initialized browser_kind={config['browser_kind']}, ui_backend={type(ui_backend).__name__}")
    return config, ui_backend


def respond(message: dict[str, Any]) -> None:
    sys.stdout.buffer.write((json.dumps(message, ensure_ascii=False) + "\n").encode("utf-8"))
    sys.stdout.buffer.flush()


def log(message: str) -> None:
    print(message, file=sys.stderr, flush=True)
