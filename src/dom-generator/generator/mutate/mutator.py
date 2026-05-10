"""
Mutator — ops 목록을 받아 Document 에 순서대로 적용하는 퍼사드.
"""

from __future__ import annotations
import random
from generator.ir.document import Document
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

ALL_OPS = list(_DOM_OPS | _CSS_OPS | _JS_OPS)


class Mutator:
    def __init__(self, cfg: GeneratorConfig | None = None):
        self.cfg = cfg or DEFAULT_CONFIG
        kw = get_keywords()
        rng = random.Random()  # mutation 은 항상 랜덤

        self._dom = DOMTreeMutator(kw, rng, self.cfg.tree)
        self._css = CSSMutator(kw, rng, self.cfg.css)
        self._js  = JSMutator(kw, rng, self.cfg.js)

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
        else:
            raise ValueError(f"Unknown mutation op: {op!r}")
