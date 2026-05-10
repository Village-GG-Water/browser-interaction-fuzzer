from __future__ import annotations

import argparse
import json
import os
import random
import shutil
import sys
import time
from pathlib import Path
from typing import Any


INTERACTABLE_CSS = (
    "a,button,input,textarea,select,details,summary,dialog,"
    "iframe,canvas,video,audio,[contenteditable],[tabindex],[draggable]"
)
TEXT_INPUTS_CSS = "input,textarea,select,[contenteditable]"
DRAGGABLE_CSS = "[draggable],img,a,div,canvas"
EVENT_HANDLER_CSS = (
    "[onclick],[ondblclick],[onmousedown],[onmouseup],"
    "[onfocus],[onblur],[oninput],[onchange],"
    "[onkeydown],[onkeyup],[onsubmit],"
    "[onpointerdown],[onpointerup],[ontouchstart],"
    "[onmouseover],[onmouseout],[oncontextmenu],"
    "[ondragstart],[ondrop]"
)

CRASH_MARKERS = [
    "crashed",
    "target closed",
    "browser closed",
    "connection refused",
    "browser has been closed",
    "process exited",
    "browser was disconnected",
]

CLEANUP_JS = """() => {
    try { localStorage.clear(); } catch (_) {}
    try { sessionStorage.clear(); } catch (_) {}
    try {
        if (navigator.serviceWorker) {
            navigator.serviceWorker.getRegistrations().then((regs) => {
                for (const reg of regs) { reg.unregister(); }
            });
        }
    } catch (_) {}
    try {
        if (window.caches && caches.keys) {
            caches.keys().then((keys) => {
                for (const k of keys) { caches.delete(k); }
            });
        }
    } catch (_) {}
}"""


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

    try:
        for raw_line in sys.stdin:
            line = raw_line.strip()
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
                    config = initialize(message)
                    playwright = start_playwright()
                    respond({"status": "ok"})
                elif cmd == "run_testcase":
                    if config is None or playwright is None:
                        respond({"status": "error", "reason": "not initialized"})
                        continue
                    respond(run_testcase(playwright, config, message))
                elif cmd == "shutdown":
                    respond({"status": "ok"})
                    break
                else:
                    respond({"status": "error", "error": f"unknown cmd: {cmd!r}"})
            except Exception as exc:
                respond({"status": "error", "reason": str(exc)[:500]})
    finally:
        if playwright is not None:
            playwright.stop()


def initialize(message: dict[str, Any]) -> dict[str, Any]:
    required = ["browser_path", "browser_kind", "sancov_dir", "asan_dir", "out_dir"]
    for key in required:
        if not message.get(key):
            raise ValueError(f"missing {key}")

    config = dict(message)
    Path(config["sancov_dir"]).mkdir(parents=True, exist_ok=True)
    Path(config["asan_dir"]).mkdir(parents=True, exist_ok=True)
    Path(config["out_dir"]).mkdir(parents=True, exist_ok=True)
    log(f"[simulator] initialized browser_kind={config['browser_kind']}")
    return config


def start_playwright():
    from playwright.sync_api import sync_playwright

    return sync_playwright().start()


def run_testcase(pw, config: dict[str, Any], message: dict[str, Any]) -> dict[str, Any]:
    from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

    started = now_ms()
    timings = {
        "launch_ms": 0,
        "load_ms": 0,
        "actions_ms": 0,
        "close_ms": 0,
        "simulator_total_ms": 0,
        "asan_scan_ms": 0,
        "sancov_parse_ms": 0,
        "iteration_total_ms": 0,
    }
    action_stats = {
        "actions_attempted": len(message.get("actions", [])),
        "actions_succeeded": 0,
        "selector_fallbacks": 0,
        "slow_actions": 0,
    }

    browser = None
    context = None
    profile_dir = Path(config["out_dir"]) / f"profile_{message.get('iteration', 0)}"

    def finish(status: str, reason: str | None = None) -> dict[str, Any]:
        timings["simulator_total_ms"] = elapsed_ms(started)
        timings["iteration_total_ms"] = timings["simulator_total_ms"]
        response = {"status": status, "timings": timings, **action_stats}
        if reason is not None:
            response["reason"] = reason[:500]
        return response

    try:
        phase = now_ms()
        browser, context = launch_context(pw, config, profile_dir)
        timings["launch_ms"] = elapsed_ms(phase)

        page = context.new_page()
        phase = now_ms()
        html_path = message.get("html_path")
        if html_path:
            page.goto(path_to_file_url(html_path), timeout=config_timeout(config), wait_until="load")
        else:
            page.goto(message.get("initial_url") or "about:blank", timeout=config_timeout(config))

        ready_timeout = int(config.get("page_ready_timeout_ms") or 0)
        if ready_timeout > 0:
            try:
                page.wait_for_function(
                    "document.readyState === 'complete'",
                    timeout=ready_timeout,
                )
            except Exception:
                pass
        try:
            page.evaluate(CLEANUP_JS)
        except Exception:
            pass
        timings["load_ms"] = elapsed_ms(phase)

        phase = now_ms()
        action_timeout = min(config_timeout(config), int(config.get("action_timeout_ms") or 3000))
        inter_delay = int(config.get("inter_action_delay_ms") or 0)
        for action in message.get("actions", []):
            action_started = now_ms()
            ok, fallbacks = execute_action(page, action, action_timeout)
            action_ms = elapsed_ms(action_started)
            if ok:
                action_stats["actions_succeeded"] += 1
            if action_ms >= action_timeout:
                action_stats["slow_actions"] += 1
            action_stats["selector_fallbacks"] += fallbacks
            if inter_delay > 0:
                time.sleep(inter_delay / 1000)

        settle = int(config.get("post_actions_settle_ms") or 0)
        if settle > 0:
            time.sleep(settle / 1000)
        timings["actions_ms"] = elapsed_ms(phase)

        phase = now_ms()
        close_context(browser, context, profile_dir)
        browser = None
        context = None
        timings["close_ms"] = elapsed_ms(phase)
        return finish("ok")

    except Exception as exc:
        phase = now_ms()
        close_context(browser, context, profile_dir)
        timings["close_ms"] += elapsed_ms(phase)
        text = str(exc)
        if isinstance(exc, PlaywrightTimeoutError) or "timeout" in text.lower():
            return finish("timeout", text)
        if is_crash_error(exc):
            return finish("crash", text)
        return finish("error", text)


def execute_action(page, action: dict[str, Any], timeout_ms: int) -> tuple[bool, int]:
    kind = action.get("kind")
    target = action.get("target")

    if target and target.get("space") == "browser_ui":
        # 확장 지점: 접근성 API 기반 browser UI backend가 여기에 연결된다.
        return False, 0

    try:
        if kind == "click":
            element, fallback = resolve_dom_target(page, target, INTERACTABLE_CSS)
            if element:
                element.click(timeout=timeout_ms)
                return True, fallback
            return False, fallback
        if kind == "double_click":
            element, fallback = resolve_dom_target(page, target, INTERACTABLE_CSS)
            if element:
                element.dblclick(timeout=timeout_ms)
                return True, fallback
            return False, fallback
        if kind == "right_click":
            element, fallback = resolve_dom_target(page, target, INTERACTABLE_CSS)
            if element:
                element.click(button="right", timeout=timeout_ms)
                return True, fallback
            return False, fallback
        if kind == "type_text":
            element, fallback = resolve_dom_target(page, target, TEXT_INPUTS_CSS)
            if element:
                element.type(str(action.get("text", "")), timeout=timeout_ms)
                return True, fallback
            return False, fallback
        if kind == "clear":
            element, fallback = resolve_dom_target(page, target, TEXT_INPUTS_CSS)
            if element:
                element.fill("", timeout=timeout_ms)
                return True, fallback
            return False, fallback
        if kind == "drag_drop":
            src, first_fallback = resolve_dom_target(page, target, DRAGGABLE_CSS)
            dst, second_fallback = resolve_dom_target(page, action.get("to"), DRAGGABLE_CSS)
            if src and dst:
                src.drag_to(dst, timeout=timeout_ms)
                return True, first_fallback + second_fallback
            return False, first_fallback + second_fallback
        if kind == "scroll":
            page.evaluate(f"window.scrollBy({int(action.get('x') or 0)}, {int(action.get('y') or 0)})")
            return True, 0
        if kind == "scroll_into_view":
            element, fallback = resolve_dom_target(page, target, INTERACTABLE_CSS)
            if element:
                element.scroll_into_view_if_needed(timeout=timeout_ms)
                return True, fallback
            return False, fallback
        if kind == "focus":
            element, fallback = resolve_dom_target(page, target, INTERACTABLE_CSS)
            if element:
                element.focus()
                return True, fallback
            return False, fallback
        if kind == "blur":
            element, fallback = resolve_dom_target(page, target, INTERACTABLE_CSS)
            if element:
                element.evaluate("el => el.blur()")
                return True, fallback
            return False, fallback
        if kind == "hover":
            element, fallback = resolve_dom_target(page, target, INTERACTABLE_CSS)
            if element:
                element.hover(timeout=timeout_ms)
                return True, fallback
            return False, fallback
        if kind == "press_key":
            page.keyboard.press(str(action.get("key") or "Enter"))
            return True, 0
        if kind == "refresh":
            page.reload(timeout=timeout_ms)
            return True, 0
        if kind == "back":
            page.go_back(timeout=timeout_ms)
            return True, 0
        if kind == "forward":
            page.go_forward(timeout=timeout_ms)
            return True, 0
        if kind == "sleep":
            time.sleep(int(action.get("millis") or 1) / 1000)
            return True, 0
    except Exception:
        return False, 0

    return False, 0


def resolve_dom_target(page, target: dict[str, Any] | None, fallback_css: str):
    selector = ""
    if target and target.get("space") == "dom":
        selector = str(target.get("selector") or "")

    if selector:
        try:
            element = page.query_selector(selector)
            if element:
                return element, 0
        except Exception:
            pass

    try:
        handlers = page.query_selector_all(EVENT_HANDLER_CSS)
        if handlers:
            return random.choice(handlers), 1
    except Exception:
        pass

    try:
        elements = page.query_selector_all(fallback_css)
        if elements:
            return random.choice(elements), 1
    except Exception:
        pass

    return None, 1


def launch_context(pw, config: dict[str, Any], profile_dir: Path):
    browser_kind = str(config.get("browser_kind") or "chromium").lower()
    if browser_kind != "chromium":
        raise ValueError(f"unsupported browser_kind for v1: {browser_kind}")

    browser = pw.chromium.launch(
        executable_path=config["browser_path"],
        headless=True,
        args=browser_args(config),
        env=browser_env(config),
        timeout=config_timeout(config),
    )
    return browser, browser.new_context()


def close_context(browser, context, profile_dir: Path) -> None:
    if context:
        try:
            context.close()
        except Exception:
            pass
    if browser:
        try:
            browser.close()
        except Exception:
            pass
    shutil.rmtree(profile_dir, ignore_errors=True)


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


def is_crash_error(exc: Exception) -> bool:
    text = str(exc).lower()
    return any(marker in text for marker in CRASH_MARKERS)


def respond(message: dict[str, Any]) -> None:
    sys.stdout.write(json.dumps(message, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def log(message: str) -> None:
    print(message, file=sys.stderr, flush=True)


def now_ms() -> float:
    return time.perf_counter()


def elapsed_ms(started: float) -> int:
    return int((time.perf_counter() - started) * 1000)
