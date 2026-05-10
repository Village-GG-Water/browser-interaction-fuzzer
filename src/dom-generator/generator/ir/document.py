"""
Document — DOM Generator의 최상위 IR 객체.

Document 하나가 HTML 파일 하나에 대응한다.
"""

from __future__ import annotations
import copy
from dataclasses import dataclass, field

from generator.ir.context import GlobalContext
from generator.ir.element import DOMTree
from generator.ir.css import CSSRule, CSSKeyframesRule, CSSVariables
from generator.ir.js import EventHandler, ScriptFunction, InlineScript


@dataclass
class Document:
    """문서 전체를 담는 최상위 IR 객체.

    lower/html_writer.py 가 이 객체를 받아 HTML 문자열을 생성한다.

    JS 구조:
      event_handlers  — FD-IR 방식 이벤트 핸들러 (f0~f4). mutation 가능.
      script_functions — corpus JS 함수 (statement-level 분해). 부분 mutation 가능.
      inline_scripts   — corpus JS 인라인 코드 (statement-level 분해). 부분 mutation 가능.
    """

    # DOM 트리 (body 내부)
    dom_tree: DOMTree = field(default_factory=DOMTree)

    # CSS
    css_rules: list[CSSRule] = field(default_factory=list)
    css_keyframes: list[CSSKeyframesRule] = field(default_factory=list)
    css_variables: CSSVariables = field(default_factory=lambda: CSSVariables({}))

    # JS: FD-IR 방식 생성된 이벤트 핸들러 (mutation 가능)
    event_handlers: list[EventHandler] = field(default_factory=list)

    # JS: corpus에서 온 함수 (statement-level 분해, 부분 mutation 가능)
    script_functions: list[ScriptFunction] = field(default_factory=list)

    # JS: corpus에서 온 인라인 코드 (statement-level 분해, 부분 mutation 가능)
    inline_scripts: list[InlineScript] = field(default_factory=list)

    # 공유 상태
    context: GlobalContext = field(default_factory=GlobalContext)

    def clone(self) -> Document:
        """문서 전체를 깊이 복사한다.

        corpus 문서를 mutation 하기 전에 원본 보존용으로 사용한다.
        clone() 후에는 rebuild_context()를 호출해야 context가 새 DOM을 가리킨다.
        """
        new_dom = DOMTree(
            body_children=[e.clone() for e in self.dom_tree.body_children]
        )
        return Document(
            dom_tree=new_dom,
            css_rules=[r.clone() for r in self.css_rules],
            css_keyframes=[kf.clone() for kf in self.css_keyframes],
            css_variables=self.css_variables.clone(),
            event_handlers=[h.clone() for h in self.event_handlers],
            script_functions=[f.clone() for f in self.script_functions],
            inline_scripts=[s.clone() for s in self.inline_scripts],
            context=copy.deepcopy(self.context),
        )

    def rebuild_context(self) -> None:
        """DOM 트리를 순회하여 GlobalContext를 재구축한다.

        clone() 후 또는 대규모 mutation 후 context를 동기화할 때 사용한다.
        """
        ctx = GlobalContext(
            _next_id=self.context._next_id,
            _next_class=self.context._next_class,
            _next_keyframe=self.context._next_keyframe,
        )
        for elem in self.dom_tree.walk():
            ctx.elements.append(elem)
            if elem.tag == "filter" and elem.namespace == "svg":
                ctx.filter_ids.append(elem.id)
            if elem.tag == "clipPath" and elem.namespace == "svg":
                ctx.clippath_ids.append(elem.id)

        ctx.css_variables = list(self.css_variables.variables.keys())

        classes: set[str] = set()
        for elem in self.dom_tree.walk():
            if "class" in elem.attributes:
                for c in elem.attributes["class"].split():
                    classes.add(c)
        ctx.classes = list(classes)
        ctx._next_class = self.context._next_class

        ctx.keyframe_names = [kf.name for kf in self.css_keyframes]
        ctx._next_keyframe = self.context._next_keyframe

        self.context = ctx

    def handler_by_id(self, func_id: str) -> EventHandler | None:
        for h in self.event_handlers:
            if h.func_id == func_id:
                return h
        return None

    def script_function_by_name(self, name: str) -> ScriptFunction | None:
        for f in self.script_functions:
            if f.name == name:
                return f
        return None

    def __repr__(self) -> str:
        return (
            f"<Document elements={len(self.context.elements)} "
            f"css_rules={len(self.css_rules)} "
            f"handlers={len(self.event_handlers)} "
            f"script_functions={len(self.script_functions)} "
            f"inline_scripts={len(self.inline_scripts)}>"
        )
