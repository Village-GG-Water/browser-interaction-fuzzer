# src/user-interaction-simulator/user_interaction_simulator/dom_utils.py
from __future__ import annotations

import random
import logging
from typing import Any

from playwright.sync_api import Page, ElementHandle, Error as PlaywrightError

from .constants import EVENT_HANDLER_CSS

def resolve_dom_target(page: Page, target: dict[str, Any] | None, fallback_css: str) -> tuple[ElementHandle | None, int]:
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
        except PlaywrightError as e:
            logging.debug(f"Selector '{selector}' query failed: {e}")

    if not allow_fallback:
        return None, 0

    try:
        handlers = page.query_selector_all(EVENT_HANDLER_CSS)
        if handlers:
            return random.choice(handlers), 1
    except PlaywrightError as e:
        logging.debug(f"Fallback handler query failed: {e}")

    try:
        elements = page.query_selector_all(fallback_css)
        if elements:
            return random.choice(elements), 1
    except PlaywrightError as e:
        logging.debug(f"Fallback css query failed: {e}")

    return None, 1


def inspect_action_target(page: Page, target: dict[str, Any] | None, target_cache: dict[str, dict[str, float]]) -> dict[str, Any]:
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
    except PlaywrightError as e:
        logging.debug(f"inspect_action_target query failed for '{selector}': {e}")
        return {"exists": False}


def uses_cached_point(target: dict[str, Any] | None) -> bool:
    return bool(target and target.get("space") == "dom" and target.get("resolution") == "cached_point")


def cached_point(target: dict[str, Any] | None, target_cache: dict[str, dict[str, float]]) -> dict[str, float] | None:
    if not target or target.get("space") != "dom":
        return None
    selector = str(target.get("selector") or "")
    return target_cache.get(selector)


def click_cached_point(
    page: Page,
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


def hover_cached_point(page: Page, target: dict[str, Any] | None, target_cache: dict[str, dict[str, float]]) -> tuple[bool, int]:
    point = cached_point(target, target_cache)
    if not point:
        return False, 0
    page.mouse.move(point["x"], point["y"])
    return True, 0
