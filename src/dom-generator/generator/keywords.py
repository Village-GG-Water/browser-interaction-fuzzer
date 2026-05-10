"""
keywords/ 디렉토리의 JSON 파일을 로드하고 캐싱한다.

생성/변이 로직은 이 모듈을 통해 keyword 데이터에 접근한다.
파일을 편집하면 즉시 생성 범위가 바뀐다.
"""

from __future__ import annotations
import json
import os
import warnings
from functools import cached_property
from pathlib import Path

_KEYWORDS_DIR = Path(__file__).parent.parent / "keywords"


def _load(path: Path) -> dict | list:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


class Keywords:
    """keywords/ JSON 파일 전체를 지연 로드한다."""

    def __init__(self, keywords_dir: Path = _KEYWORDS_DIR):
        self._dir = keywords_dir

    def _path(self, *parts: str) -> Path:
        return self._dir.joinpath(*parts)

    # ── HTML ──────────────────────────────────────────────────────────────

    @cached_property
    def html_elements(self) -> dict:
        """interface_name → tag_name 플랫 딕셔너리.
        예: {"HTMLDivElement": "div", ...}
        """
        return _load(self._path("html", "elements.json"))

    @cached_property
    def html_attributes(self) -> dict:
        """global / event_handlers / aria / element_specific 섹션."""
        return _load(self._path("html", "attributes.json"))

    @cached_property
    def html_empty_elements(self) -> list[str]:
        """void 태그 목록."""
        return _load(self._path("html", "empty_elements.json"))

    @cached_property
    def html_child_rules(self) -> dict:
        """specific / general / other 섹션."""
        return _load(self._path("html", "child_rules.json"))

    # ── CSS ───────────────────────────────────────────────────────────────

    @cached_property
    def css_properties(self) -> dict:
        """prop_name → {values: [type_string, ...]} 딕셔너리.
        최상위 "properties" 키 아래의 딕셔너리를 반환한다.
        """
        raw = _load(self._path("css", "properties.json"))
        return raw.get("properties", raw) if isinstance(raw, dict) else {}

    @cached_property
    def css_property_names(self) -> list[str]:
        """CSS 속성 이름 목록."""
        return list(self.css_properties.keys())

    @cached_property
    def css_selectors(self) -> dict:
        """pseudo_classes / pseudo_elements / combinators 섹션."""
        return _load(self._path("css", "selectors.json"))

    @cached_property
    def css_at_rules(self) -> dict:
        """keyframes_animatable 섹션."""
        return _load(self._path("css", "at_rules.json"))

    @cached_property
    def css_values(self) -> dict:
        """colors / lengths / ... 섹션."""
        return _load(self._path("css", "values.json"))

    # ── JS ────────────────────────────────────────────────────────────────

    @cached_property
    def js_functions(self) -> dict:
        """최상위 구조 그대로 반환.
        {methods: {TypeName: [{name, args, return}]}, hierarchy: {}, ...}
        """
        return _load(self._path("js", "functions.json"))

    @cached_property
    def js_methods(self) -> dict:
        """TypeName → [{name, args, return}] 딕셔너리."""
        return self.js_functions.get("methods", {})

    @cached_property
    def js_hierarchy(self) -> dict:
        """TypeName → [parent_type, ...] 딕셔너리.
        주의: js/functions.json 의 hierarchy 는 부모→자식 방향이다.
        검색은 js_ancestors() 를 사용하면 편리하다.
        """
        return self.js_functions.get("hierarchy", {})

    @cached_property
    def js_properties(self) -> dict:
        """TypeName → {read_only: {prop: type}, read_write: {prop: type}} 딕셔너리.
        최상위 "properties" 키 아래의 딕셔너리를 반환한다.
        """
        raw = _load(self._path("js", "properties.json"))
        return raw.get("properties", raw) if isinstance(raw, dict) else {}

    @cached_property
    def js_events(self) -> dict:
        """카테고리별 이벤트 타입."""
        return _load(self._path("js", "events.json"))

    @cached_property
    def js_constructors(self) -> list[dict]:
        """생성자 목록."""
        return _load(self._path("js", "constructors.json"))

    # ── SVG ───────────────────────────────────────────────────────────────

    @cached_property
    def svg_elements(self) -> dict:
        """최상위 구조: {elements: {interface: tag}, categories: {...}, child_rules: {...}}"""
        return _load(self._path("svg", "elements.json"))

    @cached_property
    def svg_element_map(self) -> dict:
        """interface_name → tag_name 플랫 딕셔너리."""
        return self.svg_elements.get("elements", {})

    @cached_property
    def svg_child_rules(self) -> dict:
        """tag → [허용 자식 tag] 딕셔너리."""
        return self.svg_elements.get("child_rules", {})

    @cached_property
    def svg_attributes(self) -> dict:
        """global / presentation / mandatory / elements 섹션."""
        return _load(self._path("svg", "attributes.json"))

    @cached_property
    def svg_filters(self) -> dict:
        """filter primitives 목록."""
        return _load(self._path("svg", "filters.json"))

    # ── 편의 메서드 ───────────────────────────────────────────────────────

    def is_void_element(self, tag: str) -> bool:
        return tag in self.html_empty_elements

    def allowed_children(self, parent_tag: str) -> list[str]:
        """parent 태그가 허용하는 자식 태그 목록을 반환한다.

        child_rules.json 구조:
          {child_rules: {tag: [children]},
           general_child_elements: [...],
           other_child_elements: [...]}
        """
        specific = self.html_child_rules.get("child_rules", {})
        if parent_tag in specific:
            return specific[parent_tag]
        general = self.html_child_rules.get("general_child_elements", [])
        return general

    def tag_to_interface(self, tag: str) -> str:
        """태그 이름으로 HTML 인터페이스 이름을 반환한다."""
        for interface, t in self.html_elements.items():
            if t == tag:
                return interface
        for interface, t in self.svg_element_map.items():
            if t == tag:
                return interface
        return f"HTML{tag.capitalize()}Element"

    def element_attributes(self, tag: str) -> list[str]:
        """주어진 태그에 적용 가능한 속성 이름 목록을 반환한다.

        글로벌 속성 + 엘리먼트별 속성을 합친다.
        html/attributes.json 구조:
          {global: [name, ...], element_specific: {tag: [name, ...]}, ...}
        """
        attrs = self.html_attributes
        result = list(attrs.get("global", []))
        element_specific = attrs.get("element_specific", {})
        if tag in element_specific:
            result.extend(element_specific[tag])
        return result

    def css_value_types_for(self, prop_name: str) -> list[str]:
        """CSS 속성에 허용되는 값 타입 목록을 반환한다.
        예: "color" → ["color"]
            "animation-name" → ["custom-ident"]
        """
        prop_info = self.css_properties.get(prop_name, {})
        return prop_info.get("values", ["length"])

    def all_event_types(self) -> list[str]:
        """모든 이벤트 타입 이름을 평탄화하여 반환한다."""
        events = self.js_events
        result = []
        for category_events in events.values():
            if isinstance(category_events, list):
                result.extend(category_events)
            elif isinstance(category_events, dict):
                for v in category_events.values():
                    if isinstance(v, list):
                        result.extend(v)
                    else:
                        result.append(v)
        return result

    def methods_for_type(self, type_name: str, include_ancestors: bool = True) -> list[dict]:
        """type_name 에 사용 가능한 메서드 목록을 반환한다.

        include_ancestors=True 이면 계층 상위 타입의 메서드도 포함한다.
        hierarchy 는 부모→자식 방향이므로 역방향으로 상위 타입을 찾는다.
        """
        # 직접 메서드
        candidates = list(self.js_methods.get(type_name, []))

        if include_ancestors:
            # hierarchy: parent → [children], 즉 상위 타입을 찾으려면 역검색
            # 간단히: type_name 이 child 로 등록된 parent 를 재귀 탐색
            visited = {type_name}
            queue = [type_name]
            while queue:
                current = queue.pop()
                for parent, children in self.js_hierarchy.items():
                    if current in children and parent not in visited:
                        visited.add(parent)
                        queue.append(parent)
                        candidates.extend(self.js_methods.get(parent, []))

        return candidates

    def writable_props_for_type(self, type_name: str) -> list[dict]:
        """type_name 에 쓰기 가능한 프로퍼티 목록을 [{property, value_type}] 형태로 반환한다."""
        result = []
        visited = {type_name}
        queue = [type_name]
        while queue:
            current = queue.pop()
            type_props = self.js_properties.get(current, {})
            for prop, vtype in type_props.get("read_write", {}).items():
                result.append({"property": prop, "value_type": vtype})
            for parent, children in self.js_hierarchy.items():
                if current in children and parent not in visited:
                    visited.add(parent)
                    queue.append(parent)
        return result

    def readable_props_for_type(self, type_name: str) -> list[dict]:
        """type_name 에 읽기 가능한 프로퍼티 목록을 [{property, return_type}] 형태로 반환한다."""
        result = []
        visited = {type_name}
        queue = [type_name]
        while queue:
            current = queue.pop()
            type_props = self.js_properties.get(current, {})
            for prop, rtype in type_props.get("read_only", {}).items():
                result.append({"property": prop, "return_type": rtype})
            for prop, rtype in type_props.get("read_write", {}).items():
                result.append({"property": prop, "return_type": rtype})
            for parent, children in self.js_hierarchy.items():
                if current in children and parent not in visited:
                    visited.add(parent)
                    queue.append(parent)
        return result

    def validate(self) -> list[str]:
        """키워드 간 의존 관계 검증. 경고 메시지 목록을 반환한다."""
        warnings_list = []

        # SVGFilterElement 가 없는데 CSS filter 참조가 있는 경우
        svg_tags = set(self.svg_element_map.values())
        if "filter" not in svg_tags:
            if "filter" in self.css_properties:
                warnings_list.append(
                    "CSS 'filter' 속성이 있지만 SVG <filter> 엘리먼트가 없습니다."
                )

        return warnings_list


# 프로세스 내 공유 싱글톤
_instance: Keywords | None = None


def get_keywords(keywords_dir: Path | None = None) -> Keywords:
    global _instance
    if _instance is None or keywords_dir is not None:
        _instance = Keywords(keywords_dir or _KEYWORDS_DIR)
        issues = _instance.validate()
        for w in issues:
            warnings.warn(w, stacklevel=2)
    return _instance
