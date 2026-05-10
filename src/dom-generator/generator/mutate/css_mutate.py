"""
CSS 변이 (Mc1 ~ Mc3).

append_css_rule      — 규칙 추가 (Gc1)
replace_css_rule     — 규칙 교체 (Mc1)
mutate_css_rule      — 셀렉터/선언 변이 (Mc2)
mutate_css_keyframes — 키프레임 변이 (Mc3)
"""

from __future__ import annotations
import random
from generator.ir.document import Document
from generator.ir.context import GlobalContext
from generator.keywords import Keywords
from generator.gen.css_gen import CSSGenerator
from generator.config import CSSConfig


class CSSMutator:
    def __init__(self, kw: Keywords, rng: random.Random, cfg: CSSConfig):
        self.kw = kw
        self.rng = rng
        self.cfg = cfg
        self._gen = CSSGenerator(kw, rng, cfg)

    def apply(self, doc: Document, op: str) -> bool:
        ctx = doc.context

        if op == "append_css_rule":
            return self.append_css_rule(doc, ctx)
        elif op == "replace_css_rule":
            return self.replace_css_rule(doc, ctx)
        elif op == "mutate_css_rule":
            return self.mutate_css_rule(doc, ctx)
        elif op == "mutate_css_keyframes":
            return self.mutate_css_keyframes(doc, ctx)
        else:
            raise ValueError(f"Unknown CSS mutation op: {op}")

    # ── append_css_rule (Gc1) ─────────────────────────────────────────────

    def append_css_rule(self, doc: Document, ctx: GlobalContext) -> bool:
        rule = self._gen.gc1_new_rule(ctx)
        doc.css_rules.append(rule)
        return True

    # ── replace_css_rule (Mc1) ────────────────────────────────────────────

    def replace_css_rule(self, doc: Document, ctx: GlobalContext) -> bool:
        if not doc.css_rules:
            return False
        idx = self.rng.randrange(len(doc.css_rules))
        doc.css_rules[idx] = self._gen.gc1_new_rule(ctx)
        return True

    # ── mutate_css_rule (Mc2) ─────────────────────────────────────────────

    def mutate_css_rule(self, doc: Document, ctx: GlobalContext) -> bool:
        if not doc.css_rules:
            return False
        rule = self.rng.choice(doc.css_rules)

        # 셀렉터 교체 vs 선언 수정 vs 선언 추가
        action = self.rng.choice(["replace_selector", "replace_declaration", "add_declaration"])

        if action == "replace_selector" and rule.selector_groups:
            idx = self.rng.randrange(len(rule.selector_groups))
            rule.selector_groups[idx] = [self._gen._make_selector(ctx)]

        elif action == "replace_declaration" and rule.declarations:
            idx = self.rng.randrange(len(rule.declarations))
            rule.declarations[idx] = self._gen._make_declarations(ctx, 1)[0]

        elif action == "add_declaration":
            self._gen.gc3_add_declaration(rule, ctx)

        return True

    # ── mutate_css_keyframes (Mc3) ────────────────────────────────────────

    def mutate_css_keyframes(self, doc: Document, ctx: GlobalContext) -> bool:
        if not doc.css_keyframes:
            # keyframes 가 없으면 새로 생성
            new_kf_rules = self._gen.generate_keyframes(ctx)
            doc.css_keyframes.extend(new_kf_rules)
            return bool(new_kf_rules)

        kf_rule = self.rng.choice(doc.css_keyframes)
        if not kf_rule.keyframes:
            return False

        kf = self.rng.choice(kf_rule.keyframes)
        # 키프레임 내 선언 중 하나를 교체
        if kf.declarations:
            idx = self.rng.randrange(len(kf.declarations))
            kf.declarations[idx] = self._gen._make_declarations(ctx, 1)[0]

        return True
