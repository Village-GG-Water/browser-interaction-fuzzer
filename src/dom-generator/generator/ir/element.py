"""
Element  — DOM 노드 하나
DOMTree  — 엘리먼트 트리 전체 (html/head/body 루트 포함)
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Iterator


@dataclass
class Element:
    """DOM 노드 하나를 나타내는 IR 클래스.

    Freedom의 Element와 동일한 구조를 따르되,
    속성 값을 Value 인스턴스 대신 확정 문자열로 저장한다.
    """

    name: str                           # 인터페이스 이름 (예: "HTMLDivElement")
    tag: str                            # 태그 이름 (예: "div")
    id: str                             # 순차 id (예: "x0")
    namespace: str = "html"             # "html" | "svg"
    attributes: dict[str, str] = field(default_factory=dict)
    # 이벤트 핸들러 속성은 별도 관리 (mutation 대상에서 제외 가능)
    event_attrs: dict[str, str] = field(default_factory=dict)
    children: list[Element] = field(default_factory=list)
    text: str | None = None
    tree_depth: int = 0

    def is_void(self) -> bool:
        """자식/텍스트를 가질 수 없는 void 엘리먼트인지 확인."""
        # keywords/html/empty_elements.json 참조.
        # 실제 확인은 keywords 로더가 담당하므로 여기서는 tag만 저장.
        return False  # lower/html_writer.py에서 keywords로 판단

    def walk(self) -> Iterator[Element]:
        """DFS 순서로 자기 자신과 모든 자손을 순회한다."""
        yield self
        for child in self.children:
            yield from child.walk()

    def find_by_id(self, eid: str) -> Element | None:
        for elem in self.walk():
            if elem.id == eid:
                return elem
        return None

    def all_attributes(self) -> dict[str, str]:
        """일반 속성 + 이벤트 속성을 합쳐서 반환한다 (출력용)."""
        merged = dict(self.attributes)
        merged.update(self.event_attrs)
        return merged

    def clone(self) -> Element:
        """깊은 복사."""
        return Element(
            name=self.name,
            tag=self.tag,
            id=self.id,
            namespace=self.namespace,
            attributes=dict(self.attributes),
            event_attrs=dict(self.event_attrs),
            children=[c.clone() for c in self.children],
            text=self.text,
            tree_depth=self.tree_depth,
        )

    def __repr__(self) -> str:
        return f"<Element {self.tag}#{self.id} depth={self.tree_depth}>"


@dataclass
class DOMTree:
    """엘리먼트 트리 전체.

    html → head, body 구조를 유지한다.
    head/body 내부 컨텐츠 엘리먼트(style, script 등)는
    Document 클래스가 직접 관리하고 lower/ 에서 삽입한다.
    body 아래 사용자 엘리먼트 트리만 이 객체가 담당한다.
    """

    # body 직계 자식들
    body_children: list[Element] = field(default_factory=list)

    def walk(self) -> Iterator[Element]:
        """body 내 모든 엘리먼트를 DFS 순회한다."""
        for child in self.body_children:
            yield from child.walk()

    def find_by_id(self, eid: str) -> Element | None:
        for elem in self.walk():
            if elem.id == eid:
                return elem
        return None

    def all_elements(self) -> list[Element]:
        return list(self.walk())

    def insert(self, parent: Element, child: Element) -> None:
        """parent의 children에 child를 추가한다."""
        parent.children.append(child)

    def insert_at(self, parent: Element, index: int, child: Element) -> None:
        parent.children.insert(index, child)

    def remove(self, parent: Element, child: Element) -> bool:
        try:
            parent.children.remove(child)
            return True
        except ValueError:
            return False

    def depth_of(self, elem: Element) -> int:
        return elem.tree_depth
