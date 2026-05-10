"""
IR → HTML 문자열 변환.

Freedom의 Document.__str__() 를 참고하되:
  - main() 함수, onload 속성, gc(), doNothing(), run_count 제거
  - RawFunction / RawInlineScript 출력 추가
"""

from __future__ import annotations
import json
from generator.ir.document import Document
from generator.ir.element import Element
from generator.ir.css import CSSRule, CSSKeyframesRule, CSSVariables
from generator.ir.js import EventHandler, ScriptFunction, InlineScript
from generator.keywords import get_keywords


def _indent(text: str, spaces: int = 4) -> str:
    pad = " " * spaces
    return "\n".join(pad + line if line.strip() else line for line in text.splitlines())


def _render_element(elem: Element, kw, level: int = 0) -> str:
    """Element 를 HTML 태그 문자열로 변환한다."""
    indent = "    " * level
    is_void = kw.is_void_element(elem.tag)

    # 속성 문자열 생성
    attrs = {}
    attrs["id"] = elem.id
    attrs.update(elem.attributes)
    attrs.update(elem.event_attrs)

    attr_str = ""
    if attrs:
        parts = []
        for k, v in attrs.items():
            if v is None or v == "":
                parts.append(k)
            else:
                escaped = str(v).replace('"', "&quot;")
                parts.append(f'{k}="{escaped}"')
        attr_str = " " + " ".join(parts)

    if is_void:
        return f"{indent}<{elem.tag}{attr_str}>"

    open_tag = f"{indent}<{elem.tag}{attr_str}>"
    close_tag = f"{indent}</{elem.tag}>"

    # 자식이 없고 텍스트만 있는 경우: 한 줄로
    if not elem.children and elem.text:
        text = elem.text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        return f"{open_tag}{text}</{elem.tag}>"

    # 자식이 없고 텍스트도 없는 경우
    if not elem.children and not elem.text:
        return f"{open_tag}</{elem.tag}>"

    # 자식이 있는 경우
    lines = [open_tag]
    if elem.text:
        text = elem.text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        lines.append("    " * (level + 1) + text)
    for child in elem.children:
        lines.append(_render_element(child, kw, level + 1))
    lines.append(close_tag)
    return "\n".join(lines)


def _render_css_block(doc: Document) -> str:
    """스타일 규칙, keyframes, CSS 변수를 <style> 블록으로 변환한다."""
    sections = []

    if doc.css_rules:
        rules_str = "\n\n".join(str(r) for r in doc.css_rules)
        sections.append(f"<style>\n{_indent(rules_str, 4)}\n</style>")

    if doc.css_keyframes:
        kf_str = "\n\n".join(str(kf) for kf in doc.css_keyframes)
        sections.append(f"<style>\n{_indent(kf_str, 4)}\n</style>")

    if doc.css_variables.variables:
        sections.append(f"<style>\n{_indent(str(doc.css_variables), 4)}\n</style>")

    return "\n".join(sections)


def _render_script_block(doc: Document) -> str:
    """이벤트 핸들러 + ScriptFunction 을 하나의 <script> 블록으로 묶어 출력한다.

    InlineScript 는 별도 <script> 블록으로 분리한다.
    """
    parts = []

    # 생성된 이벤트 핸들러 (f0~f4)
    if doc.event_handlers:
        handler_parts = [h.to_js() for h in doc.event_handlers]
        parts.append("\n\n".join(handler_parts))
        parts.append(_render_event_listener_setup(doc.event_handlers))

    # corpus JS 함수 (ScriptFunction, statement-level 분해)
    if doc.script_functions:
        func_parts = [f.to_js() for f in doc.script_functions]
        parts.append("\n\n".join(func_parts))

    sections = []
    if parts:
        combined = "\n\n".join(parts)
        sections.append(f"<script>\n{_indent(combined, 4)}\n</script>")

    # corpus 인라인 스크립트: 각각 별도 <script>
    for inline in doc.inline_scripts:
        sections.append(f"<script>\n{_indent(inline.to_js(), 4)}\n</script>")

    return "\n".join(sections)


def _render_event_listener_setup(handlers: list[EventHandler]) -> str:
    lines = ["document.addEventListener('DOMContentLoaded', function() {"]
    for handler in handlers:
        elem_id = json.dumps(handler.target_element_id)
        event = json.dumps(handler.event)
        lines.append("    try {")
        lines.append(f"        var el = document.getElementById({elem_id});")
        lines.append(
            f"        if (el) {{ el.addEventListener({event}, function(event) {{ {handler.func_id}.call(this, event); }}); }}"
        )
        lines.append("    } catch(e) {}")
    lines.append("});")
    return "\n".join(lines)


def render(doc: Document) -> str:
    """Document IR 을 HTML 문자열로 변환한다.

    Freedom 대비 변경:
      - <body onload="main()"> → <body>
      - main() 함수 없음
      - gc(), doNothing(), run_count 없음
    """
    kw = get_keywords()

    lines = ["<!DOCTYPE html>", "<html>", "<head>"]

    # CSS
    css_block = _render_css_block(doc)
    if css_block:
        for css_line in css_block.splitlines():
            lines.append("    " + css_line)

    # Script (이벤트 핸들러 + RawFunction + RawInlineScript)
    script_block = _render_script_block(doc)
    if script_block:
        for s_line in script_block.splitlines():
            lines.append("    " + s_line)

    lines.append("</head>")
    lines.append("<body>")

    # DOM 트리
    for child in doc.dom_tree.body_children:
        lines.append(_render_element(child, kw, level=1))

    lines.append("</body>")
    lines.append("</html>")

    return "\n".join(lines)
