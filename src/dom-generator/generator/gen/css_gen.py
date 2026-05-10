"""
CSS 생성 (Gc1 ~ Gc3).

Gc1: 새 스타일 규칙 생성
Gc2: 추가 셀렉터
Gc3: 추가 프로퍼티
"""

from __future__ import annotations
import random
from generator.ir.css import (
    CSSDeclaration, CSSSelector, CSSRule, CSSKeyframe, CSSKeyframesRule, CSSVariables
)
from generator.ir.context import GlobalContext
from generator.config import CSSConfig
from generator.keywords import Keywords
from generator.gen.value_gen import ValueGen

_CSS_VAR_NAMES = ["--css-color", "--css-length", "--css-length-percent", "--css-line-width"]
_CSS_VAR_DEFAULTS = {
    "--css-color": "red",
    "--css-length": "10px",
    "--css-length-percent": "50%",
    "--css-line-width": "2px",
}


class CSSGenerator:
    def __init__(self, kw: Keywords, rng: random.Random, cfg: CSSConfig):
        self.kw = kw
        self.rng = rng
        self.cfg = cfg
        self.vg = ValueGen(kw, rng)

    # ── CSS 변수 생성 ─────────────────────────────────────────────────────

    def generate_variables(self, ctx: GlobalContext) -> CSSVariables:
        variables = {}
        for name in _CSS_VAR_NAMES:
            default = _CSS_VAR_DEFAULTS[name]
            if "color" in name:
                val = self.vg.color()
            elif "length" in name:
                val = self.vg.length()
            else:
                val = default
            variables[name] = val
            if name not in ctx.css_variables:
                ctx.css_variables.append(name)
        return CSSVariables(variables)

    # ── Gc1: 규칙 생성 ────────────────────────────────────────────────────

    def generate_rules(self, ctx: GlobalContext) -> list[CSSRule]:
        count = self.rng.randint(10, self.cfg.max_rules)
        return [self.gc1_new_rule(ctx) for _ in range(count)]

    def gc1_new_rule(self, ctx: GlobalContext) -> CSSRule:
        """새 CSS 규칙 하나 생성."""
        selectors = [self._make_selector(ctx)]
        decls = self._make_declarations(ctx, count=self.rng.randint(1, 5))
        return CSSRule(selector_groups=[selectors], declarations=decls)

    # ── Gc2: 셀렉터 추가 ──────────────────────────────────────────────────

    def gc2_add_selector(self, rule: CSSRule, ctx: GlobalContext) -> None:
        """기존 규칙에 셀렉터 그룹 추가."""
        if len(rule.selector_groups) >= self.cfg.max_selectors_per_rule:
            return
        rule.selector_groups.append([self._make_selector(ctx)])

    # ── Gc3: 프로퍼티 추가 ────────────────────────────────────────────────

    def gc3_add_declaration(self, rule: CSSRule, ctx: GlobalContext) -> None:
        """기존 규칙에 선언 추가."""
        if len(rule.declarations) >= self.cfg.max_declarations_per_rule:
            return
        rule.declarations.extend(self._make_declarations(ctx, count=1))

    # ── keyframes 생성 ────────────────────────────────────────────────────

    def generate_keyframes(self, ctx: GlobalContext) -> list[CSSKeyframesRule]:
        count = self.rng.randint(0, self.cfg.max_keyframes)
        result = []
        for _ in range(count):
            name = ctx.next_keyframe_name()
            kf_rule = self._make_keyframes_rule(name, ctx)
            result.append(kf_rule)
        return result

    def _make_keyframes_rule(self, name: str, ctx: GlobalContext) -> CSSKeyframesRule:
        stops = ["from", "to"]
        extra_stops = self.rng.randint(0, self.cfg.max_keyframe_stops - 2)
        for _ in range(extra_stops):
            stops.append(f"{self.rng.randint(1, 99)}%")

        keyframes = []
        for stop in stops:
            decls = self._make_declarations(ctx, count=self.rng.randint(1, 3))
            keyframes.append(CSSKeyframe(stop=stop, declarations=decls))

        return CSSKeyframesRule(name=name, keyframes=keyframes)

    # ── 내부 헬퍼 ─────────────────────────────────────────────────────────

    def _make_selector(self, ctx: GlobalContext) -> CSSSelector:
        """컨텍스트에 있는 실제 id/class 를 참조하는 셀렉터 생성."""
        mode = self.rng.choice(["id", "class", "tag"])

        if mode == "id" and ctx.elements:
            eid = ctx.random_id(self.rng)
            base = f"#{eid}"
        elif mode == "class" and ctx.classes:
            cls = ctx.random_class(self.rng)
            base = f".{cls}"
        else:
            # 태그 셀렉터: html_elements 에서 랜덤 태그 (interface → tag 플랫 dict)
            tags = list(self.kw.html_elements.values())
            tag = self.rng.choice(tags) if tags else "div"
            base = tag

        # pseudo-class 추가 (확률적)
        pseudo_class = None
        if self.rng.random() < 0.3:
            pseudo_classes = self.kw.css_selectors.get("pseudo_classes", [])
            if pseudo_classes:
                pseudo_class = self.rng.choice(pseudo_classes)

        # pseudo-element 추가 (확률적, pseudo-class 없을 때만)
        pseudo_element = None
        if pseudo_class is None and self.rng.random() < 0.15:
            pseudo_elements = self.kw.css_selectors.get("pseudo_elements", [])
            if pseudo_elements:
                pseudo_element = self.rng.choice(pseudo_elements)

        return CSSSelector(
            base=base,
            pseudo_class=pseudo_class,
            pseudo_element=pseudo_element,
        )

    def _make_declarations(self, ctx: GlobalContext, count: int) -> list[CSSDeclaration]:
        """CSS 선언 목록 생성.

        css_properties 는 {prop_name: {values: [type, ...]}} 딕셔너리이다.
        """
        prop_names = self.kw.css_property_names
        if not prop_names:
            return []

        selected = self.rng.choices(prop_names, k=count)
        decls = []
        for prop_name in selected:
            value_types = self.kw.css_value_types_for(prop_name)
            # 여러 타입 중 하나 선택
            value_type = self.rng.choice(value_types) if value_types else "length"

            # enum: 처리
            if value_type.startswith("enum:"):
                options = value_type[5:].split("|")
                value = self.rng.choice(options)
            else:
                # CSS 변수 참조 (확률적)
                if self.rng.random() < 0.1 and ctx.css_variables:
                    value = self.vg.css_var_ref(ctx) or self.vg.css_value_for_type(value_type, ctx)
                else:
                    value = self.vg.css_value_for_type(value_type, ctx)

            decls.append(CSSDeclaration(property=prop_name, value=value))
        return decls
