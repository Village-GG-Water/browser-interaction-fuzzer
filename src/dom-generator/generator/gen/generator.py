"""
DocumentGenerator — Document IR 하나를 처음부터 생성한다.
"""

from __future__ import annotations
import random
from generator.ir.document import Document
from generator.ir.context import GlobalContext
from generator.config import GeneratorConfig, DEFAULT_CONFIG
from generator.keywords import get_keywords
from generator.gen.dom_tree import DOMTreeGenerator
from generator.gen.css_gen import CSSGenerator
from generator.gen.js_gen import JSGenerator


class DocumentGenerator:
    def __init__(self, cfg: GeneratorConfig | None = None):
        self.cfg = cfg or DEFAULT_CONFIG
        self.kw = get_keywords()
        seed = self.cfg.seed
        self.rng = random.Random(seed)

        self._dom_gen = DOMTreeGenerator(self.kw, self.rng, self.cfg.tree)
        self._css_gen = CSSGenerator(self.kw, self.rng, self.cfg.css)
        self._js_gen = JSGenerator(self.kw, self.rng, self.cfg.js)

    def generate(self) -> Document:
        """새 Document 를 생성하여 반환한다."""
        doc = Document()
        ctx = doc.context

        # 1. CSS 변수 먼저 생성 (DOM/JS 생성 시 참조 가능하도록)
        doc.css_variables = self._css_gen.generate_variables(ctx)

        # 2. DOM 트리 생성
        doc.dom_tree = self._dom_gen.generate(ctx)

        # 3. CSS 규칙 + keyframes 생성 (DOM 트리 기반으로 셀렉터 생성)
        doc.css_rules = self._css_gen.generate_rules(ctx)
        doc.css_keyframes = self._css_gen.generate_keyframes(ctx)

        # 4. 이벤트 핸들러 생성
        doc.event_handlers = self._js_gen.generate_handlers(ctx)

        return doc
