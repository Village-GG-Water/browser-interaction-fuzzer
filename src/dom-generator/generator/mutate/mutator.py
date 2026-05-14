"""
Mutator — ops 목록을 받아 Document 에 순서대로 적용하는 퍼사드.
"""

from __future__ import annotations
import random
from generator.ir.document import Document
from generator.ir.js import EventHandler, RawStatement
from generator.keywords import get_keywords
from generator.config import GeneratorConfig, DEFAULT_CONFIG
from generator.mutate.dom_tree import DOMTreeMutator
from generator.mutate.css_mutate import CSSMutator
from generator.mutate.js_mutate import JSMutator

# op 이름 → 담당 mutator 카테고리
_DOM_OPS = {"insert_element", "append_attribute", "mutate_attribute",
            "replace_attribute", "mutate_text"}
_CSS_OPS = {"append_css_rule", "replace_css_rule", "mutate_css_rule",
            "mutate_css_keyframes"}
_JS_OPS  = {"append_api", "insert_api", "replace_api", "mutate_api",
            "reorder_statement", "remove_statement", "insert_statement", "mutate_api_args"}
_LIFECYCLE_OPS = {"insert_self_invalidate_handler", "insert_cross_invalidate_handler",
                  "wrap_invalidation_async", "insert_focus_invalidate_handler"}

ALL_OPS = list(_DOM_OPS | _CSS_OPS | _JS_OPS | _LIFECYCLE_OPS)


class Mutator:
    def __init__(self, cfg: GeneratorConfig | None = None):
        self.cfg = cfg or DEFAULT_CONFIG
        kw = get_keywords()
        rng = random.Random()  # mutation 은 항상 랜덤

        self._dom = DOMTreeMutator(kw, rng, self.cfg.tree)
        self._css = CSSMutator(kw, rng, self.cfg.css)
        self._js  = JSMutator(kw, rng, self.cfg.js)
        self._rng = rng

    def apply_ops(self, doc: Document, ops: list[str]) -> None:
        """ops 목록을 순서대로 Document 에 적용한다."""
        for op in ops:
            self._apply_one(doc, op)

    def _apply_one(self, doc: Document, op: str) -> bool:
        if op in _DOM_OPS:
            return self._dom.apply(doc, op)
        elif op in _CSS_OPS:
            return self._css.apply(doc, op)
        elif op in _JS_OPS:
            return self._js.apply(doc, op)
        elif op in _LIFECYCLE_OPS:
            return self._apply_lifecycle(doc, op)
        else:
            raise ValueError(f"Unknown mutation op: {op!r}")

    def _apply_lifecycle(self, doc: Document, op: str) -> bool:
        elements = list(doc.dom_tree.walk())
        if not elements:
            return False

        if op == "insert_self_invalidate_handler":
            target = self._rng.choice(elements)
            self._add_handler(doc, target.id, self._pick_event(target), self._self_invalidation())
            return True

        if op == "insert_cross_invalidate_handler":
            if len(elements) < 2:
                return False
            trigger = self._rng.choice(elements)
            victims = [elem for elem in elements if elem.id != trigger.id]
            victim = self._rng.choice(victims)
            self._add_handler(
                doc,
                trigger.id,
                self._pick_event(trigger),
                self._target_invalidation(victim.id),
            )
            return True

        if op == "wrap_invalidation_async":
            target = self._rng.choice(elements)
            statement = self._async_wrap(self._self_invalidation().code)
            self._add_handler(doc, target.id, self._pick_event(target), statement)
            return True

        if op == "insert_focus_invalidate_handler":
            focusable = [
                elem for elem in elements
                if elem.tag.lower() in {"a", "button", "input", "textarea", "select"}
                or "tabindex" in {key.lower() for key in elem.attributes}
                or "contenteditable" in {key.lower() for key in elem.attributes}
            ]
            target = self._rng.choice(focusable or elements)
            self._add_handler(doc, target.id, self._rng.choice(["focus", "input", "click"]), self._self_invalidation())
            return True

        return False

    def _add_handler(self, doc: Document, target_id: str, event: str, statement: RawStatement) -> None:
        doc.event_handlers.append(
            EventHandler(
                func_id=self._next_handler_id(doc),
                event=event,
                target_element_id=target_id,
                statements=[statement],
            )
        )

    def _next_handler_id(self, doc: Document) -> str:
        max_id = -1
        for handler in doc.event_handlers:
            if handler.func_id.startswith("f") and handler.func_id[1:].isdigit():
                max_id = max(max_id, int(handler.func_id[1:]))
        return f"f{max_id + 1}"

    def _pick_event(self, elem) -> str:
        tag = elem.tag.lower()
        if tag in {"input", "textarea", "select"}:
            return self._rng.choice(["focus", "input", "change", "click"])
        return self._rng.choice(["click", "pointerdown", "mousedown", "focus"])

    def _self_invalidation(self) -> RawStatement:
        mode = self._rng.choice(["remove", "outer_html_replace", "replace_children"])
        if mode == "remove":
            code = "try { this.remove(); } catch(e) {}"
        elif mode == "outer_html_replace":
            code = 'try { this.outerHTML = "<button id=\\"replacement\\">replacement</button>"; } catch(e) {}'
        else:
            code = 'try { this.replaceChildren(document.createTextNode("replaced")); } catch(e) {}'
        return RawStatement(code, "self_destruct")

    def _target_invalidation(self, target_id: str) -> RawStatement:
        mode = self._rng.choice(["remove", "outer_html_replace", "replace_children"])
        if mode == "remove":
            body = "__victim.remove();"
        elif mode == "outer_html_replace":
            body = '__victim.outerHTML = "<button id=\\"replacement\\">replacement</button>";'
        else:
            body = '__victim.replaceChildren(document.createTextNode("replaced"));'
        code = (
            f'try {{ var __victim = document.getElementById("{target_id}"); '
            f"if (__victim) {{ {body} }} }} catch(e) {{}}"
        )
        return RawStatement(code, "dom_mutation")

    def _async_wrap(self, code: str) -> RawStatement:
        boundary = self._rng.choice(["queue_microtask", "request_animation_frame", "set_timeout_0", "set_timeout_16"])
        if boundary == "queue_microtask":
            return RawStatement(f"queueMicrotask(function() {{ {code} }});", "timer")
        if boundary == "request_animation_frame":
            return RawStatement(f"requestAnimationFrame(function() {{ {code} }});", "timer")
        delay = 0 if boundary == "set_timeout_0" else 16
        return RawStatement(f"setTimeout(function() {{ {code} }}, {delay});", "timer")
