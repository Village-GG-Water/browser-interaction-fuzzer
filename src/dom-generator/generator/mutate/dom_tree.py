"""
DOM 트리 변이 (Mt1 ~ Mt3 + Gt1/Gt2).

insert_element    — 새 엘리먼트 삽입 (Gt1)
append_attribute  — 속성 추가 (Gt2)
mutate_attribute  — 속성 값 변이 (Mt1)
replace_attribute — 속성 교체 (Mt2)
mutate_text       — 텍스트 변이 (Mt3)
"""

from __future__ import annotations
import random
from generator.ir.document import Document
from generator.ir.element import Element
from generator.ir.context import GlobalContext
from generator.keywords import Keywords
from generator.gen.dom_tree import DOMTreeGenerator
from generator.gen.value_gen import ValueGen
from generator.config import TreeConfig


class DOMTreeMutator:
    def __init__(self, kw: Keywords, rng: random.Random, cfg: TreeConfig):
        self.kw = kw
        self.rng = rng
        self.cfg = cfg
        self.vg = ValueGen(kw, rng)
        # 엘리먼트 생성에 DOMTreeGenerator 재사용
        self._gen = DOMTreeGenerator(kw, rng, cfg)

    def apply(self, doc: Document, op: str) -> bool:
        """op 이름에 해당하는 변이를 문서에 적용한다.

        Returns:
            True if mutation was applied, False if skipped (no candidates).
        """
        ctx = doc.context

        if op == "insert_element":
            return self.insert_element(doc, ctx)
        elif op == "append_attribute":
            return self.append_attribute(doc, ctx)
        elif op == "mutate_attribute":
            return self.mutate_attribute(doc, ctx)
        elif op == "replace_attribute":
            return self.replace_attribute(doc, ctx)
        elif op == "mutate_text":
            return self.mutate_text(doc, ctx)
        else:
            raise ValueError(f"Unknown DOM mutation op: {op}")

    # ── insert_element (Gt1) ──────────────────────────────────────────────

    def insert_element(self, doc: Document, ctx: GlobalContext) -> bool:
        all_elems = list(doc.dom_tree.walk())
        if not all_elems:
            return False

        parent = self.rng.choice(all_elems)

        if self.kw.is_void_element(parent.tag):
            return False
        if parent.tree_depth >= self.cfg.max_depth:
            return False

        child_tag = self._gen._pick_child_tag(parent.tag)
        if child_tag is None:
            return False
        if child_tag == "__svg__":
            child_tag = self._gen._pick_svg_tag()

        child = self._gen._make_element(child_tag, ctx, parent.tree_depth + 1)
        self._gen._gt2_add_attributes(child, ctx)
        self._gen._gt3_add_text(child)

        parent.children.append(child)
        ctx.register_element(child)
        return True

    # ── append_attribute (Gt2) ────────────────────────────────────────────

    def append_attribute(self, doc: Document, ctx: GlobalContext) -> bool:
        all_elems = list(doc.dom_tree.walk())
        if not all_elems:
            return False

        elem = self.rng.choice(all_elems)
        available = self.kw.element_attributes(elem.tag)
        if not available:
            return False

        # 아직 없는 속성 중에서 선택 (available 은 이름 문자열 목록)
        existing = set(elem.attributes.keys()) | set(elem.event_attrs.keys())
        candidates = [a for a in available if a not in existing]
        if not candidates:
            return False

        attr_name = self.rng.choice(candidates)
        if not attr_name or attr_name.startswith("on"):
            return False

        val = self._gen._make_attr_value(attr_name, elem, ctx)
        if val is not None:
            elem.attributes[attr_name] = val
        return True

    # ── mutate_attribute (Mt1) ────────────────────────────────────────────

    def mutate_attribute(self, doc: Document, ctx: GlobalContext) -> bool:
        """기존 속성 값을 새 값으로 교체한다."""
        elems_with_attrs = [
            e for e in doc.dom_tree.walk() if e.attributes
        ]
        if not elems_with_attrs:
            return False

        elem = self.rng.choice(elems_with_attrs)
        attr_name = self.rng.choice(list(elem.attributes.keys()))

        # 속성 메타 정보 조회
        available = self.kw.element_attributes(elem.tag)
        new_val = self._gen._make_attr_value(attr_name, elem, ctx)
        if new_val is not None:
            elem.attributes[attr_name] = new_val
        return True

    # ── replace_attribute (Mt2) ───────────────────────────────────────────

    def replace_attribute(self, doc: Document, ctx: GlobalContext) -> bool:
        """속성 하나를 제거하고 다른 속성을 추가한다."""
        elems_with_attrs = [
            e for e in doc.dom_tree.walk() if e.attributes
        ]
        if not elems_with_attrs:
            return False

        elem = self.rng.choice(elems_with_attrs)
        # 제거
        old_key = self.rng.choice(list(elem.attributes.keys()))
        del elem.attributes[old_key]

        # 추가
        return self.append_attribute(doc, ctx)

    # ── mutate_text (Mt3) ─────────────────────────────────────────────────

    def mutate_text(self, doc: Document, ctx: GlobalContext) -> bool:
        elems_with_text = [
            e for e in doc.dom_tree.walk()
            if e.text and not self.kw.is_void_element(e.tag)
        ]
        if not elems_with_text:
            return False

        elem = self.rng.choice(elems_with_text)
        words = ["foo", "bar", "baz", "test", "hello", "world", "abc", "xyz",
                 "<b>bold</b>", "0", "null", "undefined"]
        elem.text = " ".join(self.rng.choices(words, k=self.rng.randint(1, 5)))
        return True
