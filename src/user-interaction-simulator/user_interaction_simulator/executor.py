# src/user-interaction-simulator/user_interaction_simulator/executor.py
from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Any

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import Page, Playwright, TimeoutError as PlaywrightTimeoutError

from .base import BaseBackend
from .browser_env import (
    launch_context,
    close_context,
    config_timeout,
    path_to_file_url,
)
from .constants import (
    CLEANUP_JS,
    CRASH_MARKERS,
    INTERACTABLE_CSS,
    TEXT_INPUTS_CSS,
    DRAGGABLE_CSS,
)
from .dom_utils import (
    inspect_action_target,
    resolve_dom_target,
    uses_cached_point,
    click_cached_point,
    hover_cached_point,
)


def run_testcase(pw: Playwright, config: dict[str, Any], message: dict[str, Any], ui_backend: BaseBackend | None) -> dict[str, Any]:
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
            ok, fallbacks = execute_action(page, action, action_timeout, target_cache, ui_backend)
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
    page: Page,
    action: dict[str, Any],
    timeout_ms: int,
    target_cache: dict[str, dict[str, float]],
    ui_backend: BaseBackend | None,
) -> tuple[bool, int]:
    kind = action.get("kind")
    target = action.get("target")

    if target and target.get("space") == "browser_ui":
        if ui_backend is None:
             return False, 0
        
        role = target.get("role")
        name = target.get("name")
        timeout = timeout_ms / 1000.0
        
        element = ui_backend.find_element(role, name, timeout)
        if not element: 
            return False, 0
        
        if kind == "click":
            return ui_backend.click(element), 0
        elif kind == "focus":
            return ui_backend.focus(element), 0
        elif kind == "type_text":
            return ui_backend.type_text(element, str(action.get("text", ""))), 0
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
            time.sleep(int(action.get("millis") or 1) / 1000.0)
            return True, 0
    except Exception:
        return False, 0

    return False, 0


def safe_url(page: Page) -> str:
    try:
        return str(page.url)
    except PlaywrightError as e:
        logging.debug(f"safe_url failed: {e}")
        return ""


def is_crash_error(exc: Exception) -> bool:
    text = str(exc).lower()
    return any(marker in text for marker in CRASH_MARKERS)


def now_ms() -> float:
    return time.perf_counter()


def elapsed_ms(started: float) -> int:
    return int((time.perf_counter() - started) * 1000)
