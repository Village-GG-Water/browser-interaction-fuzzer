"""
CSSDeclaration     — CSS 프로퍼티 하나 (property: value)
CSSSelector        — 셀렉터 하나 (#x0, .cls0:hover, div > span, ...)
CSSRule            — 셀렉터 + 선언 블록
CSSKeyframe        — @keyframes 내 단일 키프레임 (from/to/N%)
CSSKeyframesRule   — @keyframes name { ... }
CSSVariables       — :root { --css-color: ...; ... }
"""

from __future__ import annotations
from dataclasses import dataclass, field


@dataclass
class CSSDeclaration:
    """CSS 선언 하나: property: value"""
    property: str
    value: str

    def __str__(self) -> str:
        return f"{self.property}: {self.value};"

    def clone(self) -> CSSDeclaration:
        return CSSDeclaration(self.property, self.value)


@dataclass
class CSSSelector:
    """단일 셀렉터 컴포넌트.

    Freedom의 셀렉터 구조를 따른다.
    base: 태그/id/클래스 (예: "#x0", ".cls0", "div")
    pseudo_class: ":hover", ":focus", ...
    pseudo_element: "::before", "::after", ...
    combinator: ">", "+", "~", " " (공백=descendant)
    """
    base: str
    pseudo_class: str | None = None
    pseudo_element: str | None = None
    combinator: str | None = None  # 다음 셀렉터와 연결하는 combinator

    def __str__(self) -> str:
        s = self.base
        if self.pseudo_class:
            s += self.pseudo_class
        if self.pseudo_element:
            s += self.pseudo_element
        return s

    def clone(self) -> CSSSelector:
        return CSSSelector(
            base=self.base,
            pseudo_class=self.pseudo_class,
            pseudo_element=self.pseudo_element,
            combinator=self.combinator,
        )


def selectors_to_string(selectors: list[CSSSelector]) -> str:
    """셀렉터 리스트를 CSS 셀렉터 문자열로 변환한다.

    예: [div, > span] → "div > span"
    """
    parts = []
    for i, sel in enumerate(selectors):
        if i > 0 and sel.combinator:
            parts.append(sel.combinator)
        parts.append(str(sel))
    return " ".join(parts)


@dataclass
class CSSRule:
    """CSS 규칙: 셀렉터(들) + 선언 블록.

    Freedom은 selector_groups (쉼표로 구분되는 복수 셀렉터)를 지원했으나,
    여기서는 단순하게 selector_groups: list[list[CSSSelector]] 로 표현한다.
    각 내부 list 는 하나의 복합 셀렉터 (예: div > span:hover).
    """
    selector_groups: list[list[CSSSelector]]  # 각 그룹은 쉼표로 구분
    declarations: list[CSSDeclaration]

    def selector_string(self) -> str:
        groups = [selectors_to_string(g) for g in self.selector_groups]
        return ", ".join(groups)

    def __str__(self) -> str:
        sel = self.selector_string()
        decls = "\n    ".join(str(d) for d in self.declarations)
        return f"{sel} {{\n    {decls}\n}}"

    def clone(self) -> CSSRule:
        return CSSRule(
            selector_groups=[[s.clone() for s in g] for g in self.selector_groups],
            declarations=[d.clone() for d in self.declarations],
        )


@dataclass
class CSSKeyframe:
    """@keyframes 내 단일 키프레임."""
    stop: str  # "from", "to", "0%", "50%", "100%"
    declarations: list[CSSDeclaration]

    def __str__(self) -> str:
        decls = "\n        ".join(str(d) for d in self.declarations)
        return f"{self.stop} {{\n        {decls}\n    }}"

    def clone(self) -> CSSKeyframe:
        return CSSKeyframe(
            stop=self.stop,
            declarations=[d.clone() for d in self.declarations],
        )


@dataclass
class CSSKeyframesRule:
    """@keyframes 규칙 전체."""
    name: str
    keyframes: list[CSSKeyframe]

    def __str__(self) -> str:
        frames = "\n    ".join(str(kf) for kf in self.keyframes)
        return f"@keyframes {self.name} {{\n    {frames}\n}}"

    def clone(self) -> CSSKeyframesRule:
        return CSSKeyframesRule(
            name=self.name,
            keyframes=[kf.clone() for kf in self.keyframes],
        )


@dataclass
class CSSVariables:
    """:root { --css-color: red; --css-length: 10px; ... }"""
    variables: dict[str, str]  # name → value

    def __str__(self) -> str:
        decls = "\n    ".join(f"{k}: {v};" for k, v in self.variables.items())
        return f":root {{\n    {decls}\n}}"

    def clone(self) -> CSSVariables:
        return CSSVariables(dict(self.variables))
