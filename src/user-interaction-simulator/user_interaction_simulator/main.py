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

from .backend_loader import load_backend

ui_backend = None


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
    global ui_backend
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
    action_trace: list[dict[str, Any]] = []

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
        target_cache: dict[str, dict[str, float]] = {}
        for index, action in enumerate(message.get("actions", [])):
            action_started = now_ms()
            before = inspect_action_target(page, action.get("target"), target_cache)
            url_before = safe_url(page)
            ok, fallbacks = execute_action(page, action, action_timeout, target_cache)
            action_ms = elapsed_ms(action_started)
            after = inspect_action_target(page, action.get("target"), target_cache)
            url_after = safe_url(page)
            if ok:
                action_stats["actions_succeeded"] += 1
            if action_ms >= action_timeout:
                action_stats["slow_actions"] += 1
            action_stats["selector_fallbacks"] += fallbacks
            action_trace.append({
                "index": index,
                "kind": action.get("kind"),
                "target": action.get("target"),
                "ok": ok,
                "fallback_used": fallbacks > 0,
                "elapsed_ms": action_ms,
                "exists_before": before.get("exists"),
                "exists_after": after.get("exists"),
                "url_before": url_before,
                "url_after": url_after,
            })
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
        response = finish("ok")
        response["action_trace"] = action_trace
        return response

    except Exception as exc:
        phase = now_ms()
        close_context(browser, context, profile_dir)
        timings["close_ms"] += elapsed_ms(phase)
        text = str(exc)
        if isinstance(exc, PlaywrightTimeoutError) or "timeout" in text.lower():
            response = finish("timeout", text)
            response["action_trace"] = action_trace
            return response
        if is_crash_error(exc):
            response = finish("crash", text)
            response["action_trace"] = action_trace
            return response
        response = finish("error", text)
        response["action_trace"] = action_trace
        return response


def execute_action(
    page,
    action: dict[str, Any],
    timeout_ms: int,
    target_cache: dict[str, dict[str, float]],
) -> tuple[bool, int]:
    kind = action.get("kind")
    target = action.get("target")

    if target and target.get("space") == "browser_ui":
        if ui_backend is None:
             return False, 0
        
        role = target.get("role")
        name = target.get("name")
        timeout = timeout_ms / 1000
        
        element = ui_backend.find_element(role, name, timeout)
        if not element: 
            return False, 0
        
        if kind == "click":
            return ui_backend.click(element), 0
        elif kind == "focus":
            return ui_backend.focus(element), 0
        elif kind == "type_text":
            return ui_backend.type_text(element, action.get("text", "")), 0
        elif kind == "drag_drop":
            dst_target = action.get("to")
            if dst_target and dst_target.get("space") == "browser_ui":
                dst_element = ui_backend.find_element(dst_target.get("role"), dst_target.get("name"), timeout)
                if dst_element:
                    return ui_backend.drag_drop(element, dst_element), 0
        
        return False, 0

    try:
        if kind == "click":
            if uses_cached_point(target):
                return click_cached_point(page, target, target_cache)
            element, fallback = resolve_dom_target(page, target, INTERACTABLE_CSS)
            if element:
                element.click(timeout=timeout_ms)
                return True, fallback
            return False, fallback
        if kind == "double_click":
            if uses_cached_point(target):
                return click_cached_point(page, target, target_cache, click_count=2)
            element, fallback = resolve_dom_target(page, target, INTERACTABLE_CSS)
            if element:
                element.dblclick(timeout=timeout_ms)
                return True, fallback
            return False, fallback
        if kind == "right_click":
            if uses_cached_point(target):
                return click_cached_point(page, target, target_cache, button="right")
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
            if uses_cached_point(target):
                return click_cached_point(page, target, target_cache)
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
            if uses_cached_point(target):
                return hover_cached_point(page, target, target_cache)
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
    allow_fallback = True
    if target and target.get("space") == "dom":
        selector = str(target.get("selector") or "")
        allow_fallback = bool(target.get("fallback", True))

    if selector:
        try:
            element = page.query_selector(selector)
            if element:
                return element, 0
        except Exception:
            pass

    if not allow_fallback:
        return None, 0

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


def inspect_action_target(page, target: dict[str, Any] | None, target_cache: dict[str, dict[str, float]]) -> dict[str, Any]:
    selector = ""
    if target and target.get("space") == "dom":
        selector = str(target.get("selector") or "")
    if not selector:
        return {"exists": None}
    try:
        element = page.query_selector(selector)
        if not element:
            return {"exists": False}
        box = element.bounding_box()
        if box:
            target_cache[selector] = {
                "x": float(box["x"]) + float(box["width"]) / 2.0,
                "y": float(box["y"]) + float(box["height"]) / 2.0,
            }
        return {"exists": True}
    except Exception:
        return {"exists": False}


def uses_cached_point(target: dict[str, Any] | None) -> bool:
    return bool(target and target.get("space") == "dom" and target.get("resolution") == "cached_point")


def cached_point(target: dict[str, Any] | None, target_cache: dict[str, dict[str, float]]):
    if not target or target.get("space") != "dom":
        return None
    selector = str(target.get("selector") or "")
    return target_cache.get(selector)


def click_cached_point(
    page,
    target: dict[str, Any] | None,
    target_cache: dict[str, dict[str, float]],
    button: str = "left",
    click_count: int = 1,
) -> tuple[bool, int]:
    point = cached_point(target, target_cache)
    if not point:
        return False, 0
    page.mouse.click(point["x"], point["y"], button=button, click_count=click_count)
    return True, 0


def hover_cached_point(page, target: dict[str, Any] | None, target_cache: dict[str, dict[str, float]]) -> tuple[bool, int]:
    point = cached_point(target, target_cache)
    if not point:
        return False, 0
    page.mouse.move(point["x"], point["y"])
    return True, 0


def safe_url(page) -> str:
    try:
        return str(page.url)
    except Exception:
        return ""


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
