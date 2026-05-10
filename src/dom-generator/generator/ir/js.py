"""
JS IR 클래스.

Statement 계층 (공통):
  APICall          — DOM 메서드 호출 (mutation 가능)
  PropertyStore    — DOM 프로퍼티 대입 (mutation 가능)
  PropertyLoad     — DOM 프로퍼티 읽기 (mutation 가능)
  RawStatement     — FD-IR 불가 코드 원본 (위치 이동/삭제만 가능)
  ConditionalBlock — if/else (condition 불가, 내부 statement 가능)

컨테이너:
  EventHandler     — FD-IR 방식 이벤트 핸들러 (f0~f4)
  ScriptFunction   — corpus JS 함수 (statement-level 분해)
  InlineScript     — corpus JS 인라인 코드 (statement-level 분해)
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Union


# ---------------------------------------------------------------------------
# Statement 타입들
# ---------------------------------------------------------------------------

@dataclass
class APICall:
    """DOM 메서드 호출 하나. mutation 가능.

    예: document.getElementById("x3").appendChild(document.getElementById("x1"))
        receiver_expr = "document.getElementById('x3')"
        method        = "appendChild"
        args          = ["document.getElementById('x1')"]

    EventHandler 내에서는 항상 try-catch로 감싸진다.
    """
    receiver_expr: str
    method: str
    args: list[str] = field(default_factory=list)
    assign_to: str | None = None    # var v0 = ... 형태로 저장할 변수명
    return_type: str | None = None  # JSContext 업데이트용

    def to_js(self, indent: str = "") -> str:
        args_str = ", ".join(self.args)
        call = f"{self.receiver_expr}.{self.method}({args_str})"
        if self.assign_to:
            call = f"var {self.assign_to} = {call}"
        return f"{indent}try {{ {call}; }} catch(e) {{}}"

    def clone(self) -> APICall:
        return APICall(
            receiver_expr=self.receiver_expr,
            method=self.method,
            args=list(self.args),
            assign_to=self.assign_to,
            return_type=self.return_type,
        )


@dataclass
class PropertyStore:
    """DOM 프로퍼티 대입. mutation 가능.

    예: document.getElementById("x5").style.color = "blue"
    """
    receiver_expr: str
    property_chain: str   # "style.color", "innerHTML", "textContent", ...
    value: str

    def to_js(self, indent: str = "") -> str:
        assign = f"{self.receiver_expr}.{self.property_chain} = {self.value!r}"
        return f"{indent}try {{ {assign}; }} catch(e) {{}}"

    def clone(self) -> PropertyStore:
        return PropertyStore(
            receiver_expr=self.receiver_expr,
            property_chain=self.property_chain,
            value=self.value,
        )


@dataclass
class PropertyLoad:
    """DOM 프로퍼티 읽기 + 변수 저장. mutation 가능.

    예: var v2 = document.getElementById("x1").childNodes;
    """
    receiver_expr: str
    property_chain: str
    assign_to: str
    return_type: str | None = None

    def to_js(self, indent: str = "") -> str:
        expr = f"{self.receiver_expr}.{self.property_chain}"
        return f"{indent}try {{ var {self.assign_to} = {expr}; }} catch(e) {{}}"

    def clone(self) -> PropertyLoad:
        return PropertyLoad(
            receiver_expr=self.receiver_expr,
            property_chain=self.property_chain,
            assign_to=self.assign_to,
            return_type=self.return_type,
        )


@dataclass
class RawStatement:
    """FD-IR로 표현 불가능한 JS 문장 원본.

    내부 code 수정 불가. 위치 이동/삭제만 mutation 가능.
    try-catch를 붙이지 않는다 (원본 동작 보존).

    tag: mutation 시 이 문장의 역할 힌트 (선택적)
        "timer"        — setTimeout / requestAnimationFrame
        "event_param"  — event.* 접근
        "window_api"   — window.open / window.close
        "control_flow" — 제어흐름 (단일 RawStatement로 표현된 경우)
        None           — 미분류
    """
    code: str
    tag: str | None = None

    def to_js(self, indent: str = "") -> str:
        return f"{indent}{self.code}"

    def clone(self) -> RawStatement:
        return RawStatement(code=self.code, tag=self.tag)


@dataclass
class ConditionalBlock:
    """if/else 블록.

    condition은 raw string이므로 수정 불가.
    then_branch / else_branch 내 Statement는 mutation 가능.
    """
    condition: str
    then_branch: list[Statement] = field(default_factory=list)
    else_branch: list[Statement] | None = None

    def to_js(self, indent: str = "") -> str:
        inner = indent + "    "
        lines = [f"{indent}if ({self.condition}) {{"]
        for stmt in self.then_branch:
            lines.append(stmt.to_js(inner))
        if self.else_branch is not None:
            lines.append(f"{indent}}} else {{")
            for stmt in self.else_branch:
                lines.append(stmt.to_js(inner))
        lines.append(f"{indent}}}")
        return "\n".join(lines)

    def clone(self) -> ConditionalBlock:
        return ConditionalBlock(
            condition=self.condition,
            then_branch=[s.clone() for s in self.then_branch],
            else_branch=[s.clone() for s in self.else_branch] if self.else_branch is not None else None,
        )


# Statement 유니언 타입 (forward reference 해결을 위해 클래스 정의 후에 선언)
Statement = Union[APICall, PropertyStore, PropertyLoad, RawStatement, ConditionalBlock]


# ---------------------------------------------------------------------------
# 컨테이너 타입들
# ---------------------------------------------------------------------------

@dataclass
class EventHandler:
    """FD-IR 방식 이벤트 핸들러 (mutation 가능).

    statements에는 APICall / PropertyStore / PropertyLoad만 포함된다.
    corpus ScriptFunction과 달리 RawStatement가 없으므로 자유롭게 mutation 가능.

    엘리먼트 속성에 onclick="f0()" 형태로 바인딩된다.
    """
    func_id: str            # "f0", "f1", ...
    event: str              # "click", "mouseover", ...
    target_element_id: str  # 바인딩된 엘리먼트 id ("x3")
    statements: list[Statement] = field(default_factory=list)

    def to_js(self) -> str:
        lines = [f"function {self.func_id}(event) {{"]
        for stmt in self.statements:
            lines.append(stmt.to_js("    "))
        lines.append("}")
        return "\n".join(lines)

    def clone(self) -> EventHandler:
        return EventHandler(
            func_id=self.func_id,
            event=self.event,
            target_element_id=self.target_element_id,
            statements=[s.clone() for s in self.statements],
        )


@dataclass
class ScriptFunction:
    """corpus JS 함수. statement-level로 분해된 형태.

    내부 statements에 APICall과 RawStatement가 혼재할 수 있다.
    - APICall/PropertyStore: mutation 가능 (인자 변이, 교체)
    - RawStatement: 내부 수정 불가, 위치 이동/삭제만 가능

    예 (CVE-2025-8882 drop 함수):
        ScriptFunction(
            name="drop",
            params=["event"],
            statements=[
                RawStatement("event.preventDefault();", tag="event_param"),
                RawStatement("var data = event.dataTransfer.getData('text');", tag="event_param"),
                APICall("document", "getElementById", ['"' + data + '"'], assign_to="__el"),
                # 또는 RawStatement로 통째로:
                RawStatement("event.target.appendChild(document.getElementById(data));"),
            ]
        )
    """
    name: str
    params: list[str] = field(default_factory=list)
    statements: list[Statement] = field(default_factory=list)

    def to_js(self) -> str:
        params_str = ", ".join(self.params)
        lines = [f"function {self.name}({params_str}) {{"]
        for stmt in self.statements:
            lines.append(stmt.to_js("    "))
        lines.append("}")
        return "\n".join(lines)

    def clone(self) -> ScriptFunction:
        return ScriptFunction(
            name=self.name,
            params=list(self.params),
            statements=[s.clone() for s in self.statements],
        )


@dataclass
class InlineScript:
    """corpus JS 인라인 코드. statement-level로 분해된 형태.

    <script> 태그에 직접 들어가는 즉시 실행 코드.
    ConditionalBlock을 포함할 수 있다.

    예 (CVE-2025-8882 인라인 블록):
        InlineScript(statements=[
            ConditionalBlock(
                condition='window.location.hash==""',
                then_branch=[
                    APICall("document", "getElementById", ['"drop"'], assign_to="div"),
                    APICall("document.body", "removeChild", ["div"]),
                ],
                else_branch=[
                    APICall("document", "getElementById", ['"drag"'], assign_to="img"),
                    APICall("document.body", "removeChild", ["img"]),
                ],
            )
        ])
    """
    statements: list[Statement] = field(default_factory=list)

    def to_js(self) -> str:
        lines = []
        for stmt in self.statements:
            lines.append(stmt.to_js())
        return "\n".join(lines)

    def clone(self) -> InlineScript:
        return InlineScript(statements=[s.clone() for s in self.statements])
