"""
값 생성 유틸리티.

CSS / 속성 / JS 인자에 쓰이는 구체적인 값을 context를 고려하여 생성한다.
Freedom의 Value 시스템을 단순화한 버전이다.
"""

from __future__ import annotations
import random
from generator.ir.context import GlobalContext
from generator.keywords import Keywords


class ValueGen:
    """context-aware 값 생성기."""

    def __init__(self, kw: Keywords, rng: random.Random):
        self.kw = kw
        self.rng = rng

    # ── 기본 값 ───────────────────────────────────────────────────────────

    def color(self) -> str:
        colors = self.kw.css_values.get("colors", [])
        if colors:
            return self.rng.choice(colors)
        r, g, b = self.rng.randint(0, 255), self.rng.randint(0, 255), self.rng.randint(0, 255)
        return f"rgb({r}, {g}, {b})"

    def length(self) -> str:
        """CSS 길이값 (px, em, %, ...)"""
        lengths = self.kw.css_values.get("lengths", [])
        if lengths:
            return self.rng.choice(lengths)
        n = self.rng.randint(1, 200)
        unit = self.rng.choice(["px", "em", "rem", "%", "vw", "vh"])
        return f"{n}{unit}"

    def length_or_auto(self) -> str:
        if self.rng.random() < 0.15:
            return "auto"
        return self.length()

    def integer(self, lo: int = 0, hi: int = 100) -> str:
        return str(self.rng.randint(lo, hi))

    def float_val(self, lo: float = 0.0, hi: float = 1.0) -> str:
        return f"{self.rng.uniform(lo, hi):.2f}"

    def string(self, max_len: int = 16) -> str:
        """임의 텍스트 문자열."""
        charset = "abcdefghijklmnopqrstuvwxyz0123456789"
        n = self.rng.randint(1, max_len)
        return "".join(self.rng.choices(charset, k=n))

    def url(self) -> str:
        return "about:blank"

    # ── context 의존 값 ────────────────────────────────────────────────────

    def element_id(self, ctx: GlobalContext) -> str | None:
        """트리에 실제 존재하는 엘리먼트 id."""
        return ctx.random_id(self.rng)

    def class_name(self, ctx: GlobalContext) -> str | None:
        return ctx.random_class(self.rng)

    def keyframe_name(self, ctx: GlobalContext) -> str | None:
        return ctx.random_keyframe(self.rng)

    def filter_ref(self, ctx: GlobalContext) -> str | None:
        fid = ctx.random_filter_id(self.rng)
        if fid:
            return f"url(#{fid})"
        return None

    def clippath_ref(self, ctx: GlobalContext) -> str | None:
        cid = ctx.random_clippath_id(self.rng)
        if cid:
            return f"url(#{cid})"
        return None

    def css_var_ref(self, ctx: GlobalContext) -> str | None:
        if not ctx.css_variables:
            return None
        var = self.rng.choice(ctx.css_variables)
        return f"var({var})"

    def get_element_expr(self, ctx: GlobalContext) -> str:
        """document.getElementById("xN") 형태의 JS 표현식."""
        eid = self.element_id(ctx)
        if eid:
            return f'document.getElementById("{eid}")'
        return 'document.body'

    # ── CSS 값 타입별 생성 ────────────────────────────────────────────────

    def css_value_for_type(self, value_type: str, ctx: GlobalContext) -> str:
        """keywords/css/properties.json 의 value_type 에 맞는 값을 생성한다."""
        t = value_type.lower()

        if t in ("color", "color-value"):
            return self.color()
        if t in ("length", "length-value"):
            return self.length()
        if t in ("length-percentage", "length-or-percentage"):
            return self.length()
        if t in ("number", "integer"):
            return self.integer()
        if t == "percentage":
            return f"{self.rng.randint(0, 100)}%"
        if t == "opacity":
            return self.float_val(0.0, 1.0)
        if t == "url":
            return f"url({self.url()})"
        if t in ("string", "text"):
            return f'"{self.string()}"'
        if t == "auto":
            return "auto"
        if t == "none":
            return "none"
        if t == "animation-name":
            name = self.keyframe_name(ctx)
            return name if name else "none"
        if t == "filter":
            ref = self.filter_ref(ctx)
            return ref if ref else "none"
        if t == "clip-path":
            ref = self.clippath_ref(ctx)
            return ref if ref else "none"
        if t == "time":
            return f"{self.rng.choice([0.1, 0.2, 0.3, 0.5, 1.0, 2.0])}s"
        if t in ("transform-function", "transform"):
            funcs = [
                f"rotate({self.rng.randint(0, 360)}deg)",
                f"scale({self.float_val(0.5, 2.0)})",
                f"translate({self.length()}, {self.length()})",
                f"skewX({self.rng.randint(0, 45)}deg)",
            ]
            return self.rng.choice(funcs)

        # 기본: 길이 반환
        return self.length()

    def css_value_for_property(self, prop_name: str, ctx: GlobalContext) -> str:
        """속성 이름으로 적합한 값을 생성한다."""
        props = self.kw.css_properties
        for p in props:
            if isinstance(p, dict) and p.get("property") == prop_name:
                value_type = p.get("value_type", "length")
                return self.css_value_for_type(value_type, ctx)
        return self.length()

    # ── JS 인자 값 생성 ───────────────────────────────────────────────────

    def js_arg_for_type(self, arg_type: str, ctx: GlobalContext) -> str:
        """JS API 인자 타입에 맞는 값을 생성한다."""
        t = arg_type.lower()

        if t in ("string", "domstring"):
            return f'"{self.string()}"'
        if t in ("integer", "long", "unsigned long", "int", "number"):
            return self.integer()
        if t == "float":
            return self.float_val()
        if t == "boolean":
            return self.rng.choice(["true", "false"])
        if t in ("node", "element", "htmlelement"):
            return self.get_element_expr(ctx)
        if t == "null":
            return "null"
        if t in ("eventtype", "event_type"):
            events = self.kw.all_event_types()
            if events:
                return f'"{self.rng.choice(events)}"'
            return '"click"'
        if t == "tag":
            # createElement 같은 API에 전달하는 태그 이름
            tags = list(self.kw.html_elements.values())
            tag = self.rng.choice(tags) if tags else "div"
            return f'"{tag}"'
        if t in ("document_fragment", "document", "shadow_root"):
            return "document.createDocumentFragment()"
        if t in ("node_list", "html_collection", "named_node_map", "dom_token_list"):
            return self.get_element_expr(ctx) + ".childNodes"

        return "null"
