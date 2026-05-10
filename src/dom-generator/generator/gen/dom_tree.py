"""
DOM 트리 생성 (Gt1 ~ Gt3).

Gt1: 엘리먼트 삽입
Gt2: 속성 추가
Gt3: 텍스트 노드 삽입
"""

from __future__ import annotations
import random
from generator.ir.element import Element, DOMTree
from generator.ir.context import GlobalContext
from generator.config import TreeConfig
from generator.keywords import Keywords
from generator.gen.value_gen import ValueGen


class DOMTreeGenerator:
    def __init__(self, kw: Keywords, rng: random.Random, cfg: TreeConfig):
        self.kw = kw
        self.rng = rng
        self.cfg = cfg
        self.vg = ValueGen(kw, rng)

    def generate(self, ctx: GlobalContext) -> DOMTree:
        """빈 문서에 Gt1~Gt3 를 순서대로 적용하여 DOM 트리를 생성한다."""
        tree = DOMTree()

        # Gt1: 엘리먼트 삽입
        target_count = self.rng.randint(self.cfg.min_elements, self.cfg.max_elements)
        self._gt1_populate(tree, ctx, target_count)

        # Gt2: 속성 추가
        for elem in tree.walk():
            self._gt2_add_attributes(elem, ctx)

        # Gt3: 텍스트 노드 삽입
        for elem in tree.walk():
            self._gt3_add_text(elem)

        return tree

    # ── Gt1: 엘리먼트 삽입 ────────────────────────────────────────────────

    def _gt1_populate(self, tree: DOMTree, ctx: GlobalContext, target: int) -> None:
        """child_rules 를 준수하며 엘리먼트를 삽입한다."""
        # 첫 번째 엘리먼트: body의 직계 자식
        first = self._make_element("div", ctx, depth=0)
        tree.body_children.append(first)
        ctx.register_element(first)

        count = 1
        attempts = 0
        max_attempts = target * 10

        while count < target and attempts < max_attempts:
            attempts += 1
            # 트리에서 랜덤 부모 선택
            all_elems = list(tree.walk())
            parent = self.rng.choice(all_elems)

            # 깊이 제한
            if parent.tree_depth >= self.cfg.max_depth:
                continue

            # void 엘리먼트는 자식 불가
            if self.kw.is_void_element(parent.tag):
                continue

            # child_rules 에서 허용된 자식 태그 선택
            child_tag = self._pick_child_tag(parent.tag)
            if child_tag is None:
                continue

            # SVG 확률 적용
            if child_tag == "__svg__":
                child_tag = self._pick_svg_tag()

            child = self._make_element(child_tag, ctx, depth=parent.tree_depth + 1)
            parent.children.append(child)
            ctx.register_element(child)
            count += 1

    def _pick_child_tag(self, parent_tag: str) -> str | None:
        """parent 태그에 허용되는 자식 태그를 랜덤으로 고른다."""
        # keywords.py 의 allowed_children() 이 child_rules.json 를 올바르게 파싱
        candidates = self.kw.allowed_children(parent_tag)

        if not candidates:
            return None

        # SVG를 확률적으로 포함
        if self.rng.random() < self.cfg.svg_prob:
            return "__svg__"

        return self.rng.choice(candidates)

    def _pick_svg_tag(self) -> str:
        """SVG 엘리먼트 중 랜덤으로 하나 선택한다."""
        svg_tags = list(self.kw.svg_element_map.values())
        if svg_tags:
            return self.rng.choice(svg_tags)
        return "rect"

    def _make_element(self, tag: str, ctx: GlobalContext, depth: int) -> Element:
        """새 Element 를 생성하고 id를 할당한다."""
        interface = self.kw.tag_to_interface(tag)
        eid = ctx.next_element_id()
        is_svg = tag in self.kw.svg_element_map.values()

        return Element(
            name=interface,
            tag=tag,
            id=eid,
            namespace="svg" if is_svg else "html",
            tree_depth=depth,
        )

    def _is_svg_tag(self, tag: str) -> bool:
        return tag in self.kw.svg_element_map.values()

    # ── Gt2: 속성 추가 ────────────────────────────────────────────────────

    def _gt2_add_attributes(self, elem: Element, ctx: GlobalContext) -> None:
        """엘리먼트에 속성을 랜덤으로 추가한다.

        html/attributes.json 의 element_attributes() 는 속성 이름 문자열을 반환한다.
        """
        available = self.kw.element_attributes(elem.tag)
        if not available:
            return

        n = self.rng.randint(0, min(self.cfg.max_attributes, len(available)))
        chosen = self.rng.sample(available, k=n)

        for attr_name in chosen:
            if not attr_name or attr_name.startswith("on"):
                continue
            val = self._make_attr_value(attr_name, elem, ctx)
            if val is not None:
                elem.attributes[attr_name] = val

    def _make_attr_value(
        self, name: str, elem: Element, ctx: GlobalContext
    ) -> str | None:
        """속성 이름으로 적절한 값을 생성한다."""
        if name == "id":
            return None  # id 는 elem.id 로 이미 관리
        if name == "class":
            return ctx.next_class_name()
        if name in ("href", "src", "action", "data"):
            return "about:blank"
        if name == "style":
            return None  # CSS는 별도 <style> 에서 관리
        if name in ("disabled", "checked", "selected", "multiple",
                    "readonly", "required", "hidden", "autofocus",
                    "autoplay", "loop", "muted", "controls",
                    "novalidate", "reversed", "open", "default"):
            return ""  # boolean 속성
        if name in ("tabindex", "rowspan", "colspan", "span",
                    "size", "maxlength", "minlength", "width", "height"):
            return str(self.rng.randint(1, 10))
        if name == "type":
            return self.rng.choice(["text", "button", "checkbox", "radio",
                                    "submit", "hidden", "number", "email"])
        if name in ("for", "form", "list", "headers"):
            return ctx.random_id(self.rng) or ""
        if name == "contenteditable":
            return self.rng.choice(["true", "false", ""])
        if name == "dir":
            return self.rng.choice(["ltr", "rtl", "auto"])
        if name == "draggable":
            return self.rng.choice(["true", "false"])

        return self.vg.string(8)

    # ── Gt3: 텍스트 노드 삽입 ─────────────────────────────────────────────

    def _gt3_add_text(self, elem: Element) -> None:
        """일부 엘리먼트에 텍스트를 추가한다."""
        if self.kw.is_void_element(elem.tag):
            return
        if elem.children:
            return
        if self.rng.random() < 0.4:
            words = ["foo", "bar", "baz", "test", "hello", "world", "abc", "xyz"]
            elem.text = " ".join(self.rng.choices(words, k=self.rng.randint(1, 4)))
