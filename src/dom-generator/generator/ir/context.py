"""
GlobalContext  — 문서 전체에서 생성/변이 시 참조하는 공유 상태
JSContext      — 이벤트 핸들러 하나의 스코프 내 상태
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from generator.ir.element import Element


@dataclass
class GlobalContext:
    """트리 내 실제 존재하는 객체들의 레퍼런스를 관리한다.

    생성/변이 로직이 시맨틱 정합성이 있는 값을 만들기 위해 조회한다.
    예) CSS 셀렉터가 #x3 을 참조하려면 x3 이 실제 트리에 있어야 한다.
    """

    # 트리 내 엘리먼트 목록 (생성 순서 유지)
    elements: list[Element] = field(default_factory=list)
    # 사용 중인 CSS 클래스 이름
    classes: list[str] = field(default_factory=list)
    # 정의된 @keyframes 이름
    keyframe_names: list[str] = field(default_factory=list)
    # 정의된 CSS 변수 이름 (예: "--css-color")
    css_variables: list[str] = field(default_factory=list)
    # SVG <filter> 엘리먼트의 id
    filter_ids: list[str] = field(default_factory=list)
    # SVG <clipPath> 엘리먼트의 id
    clippath_ids: list[str] = field(default_factory=list)
    # 다음에 부여할 엘리먼트 순차 번호 (x0, x1, ...)
    _next_id: int = field(default=0, repr=False)
    # 다음에 부여할 CSS 클래스 번호 (cls0, cls1, ...)
    _next_class: int = field(default=0, repr=False)
    # 다음에 부여할 keyframe 번호 (kf0, kf1, ...)
    _next_keyframe: int = field(default=0, repr=False)

    def next_element_id(self) -> str:
        eid = f"x{self._next_id}"
        self._next_id += 1
        return eid

    def next_class_name(self) -> str:
        name = f"cls{self._next_class}"
        self._next_class += 1
        self.classes.append(name)
        return name

    def next_keyframe_name(self) -> str:
        name = f"kf{self._next_keyframe}"
        self._next_keyframe += 1
        self.keyframe_names.append(name)
        return name

    def register_element(self, elem: Element) -> None:
        self.elements.append(elem)
        if elem.tag in ("filter",) and elem.namespace == "svg":
            self.filter_ids.append(elem.id)
        if elem.tag == "clipPath" and elem.namespace == "svg":
            self.clippath_ids.append(elem.id)

    def elements_by_type(self, interface_name: str) -> list[Element]:
        """특정 인터페이스 이름을 가진 엘리먼트 목록을 반환한다."""
        return [e for e in self.elements if e.name == interface_name]

    def random_element(self, rng) -> Element | None:
        if not self.elements:
            return None
        return rng.choice(self.elements)

    def random_class(self, rng) -> str | None:
        if not self.classes:
            return None
        return rng.choice(self.classes)

    def random_id(self, rng) -> str | None:
        if not self.elements:
            return None
        return rng.choice(self.elements).id

    def random_keyframe(self, rng) -> str | None:
        if not self.keyframe_names:
            return None
        return rng.choice(self.keyframe_names)

    def random_filter_id(self, rng) -> str | None:
        if not self.filter_ids:
            return None
        return rng.choice(self.filter_ids)

    def random_clippath_id(self, rng) -> str | None:
        if not self.clippath_ids:
            return None
        return rng.choice(self.clippath_ids)


@dataclass
class LocalVar:
    """이벤트 핸들러 내 로컬 변수 정보."""
    name: str           # "v0", "v1", ...
    type_name: str      # "HTMLDivElement", "Node", ...
    line: int           # 선언된 줄 (0-indexed)


@dataclass
class JSContext:
    """이벤트 핸들러 하나의 스코프 내 상태.

    API 호출 생성/변이 시 현재 스코프에서 사용 가능한 변수와
    타입 정보를 관리한다.
    """

    variables: list[LocalVar] = field(default_factory=list)
    line_count: int = field(default=0)
    _next_var: int = field(default=0, repr=False)

    def next_var_name(self) -> str:
        name = f"v{self._next_var}"
        self._next_var += 1
        return name

    def add_variable(self, type_name: str) -> LocalVar:
        var = LocalVar(
            name=self.next_var_name(),
            type_name=type_name,
            line=self.line_count,
        )
        self.variables.append(var)
        return var

    def vars_by_type(self, type_name: str) -> list[LocalVar]:
        return [v for v in self.variables if v.type_name == type_name]

    def vars_by_types(self, type_names: list[str]) -> list[LocalVar]:
        return [v for v in self.variables if v.type_name in type_names]

    def random_var(self, rng) -> LocalVar | None:
        if not self.variables:
            return None
        return rng.choice(self.variables)

    def random_var_by_type(self, type_name: str, rng) -> LocalVar | None:
        candidates = self.vars_by_type(type_name)
        if not candidates:
            return None
        return rng.choice(candidates)
