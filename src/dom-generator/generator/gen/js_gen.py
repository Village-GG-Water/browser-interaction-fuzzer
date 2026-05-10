"""
이벤트 핸들러 생성 (Gf).

Freedom의 main() 에 해당하는 API 호출 시퀀스를 이벤트 핸들러 단위로 생성한다.
각 핸들러는 JSContext 를 독립적으로 가진다.
"""

from __future__ import annotations
import random
from generator.ir.js import (
    APICall, PropertyStore, PropertyLoad, RawStatement, EventHandler, Statement
)
from generator.ir.context import GlobalContext, JSContext
from generator.ir.element import Element
from generator.config import JSConfig
from generator.keywords import Keywords
from generator.gen.value_gen import ValueGen


class JSGenerator:
    INTERACTABLE_TAGS = {
        "a", "button", "input", "textarea", "select", "details", "summary",
        "dialog", "iframe", "canvas", "video", "audio",
    }
    HIGH_VALUE_EVENTS = [
        "click", "dblclick", "mousedown", "mouseup", "focus", "blur",
        "input", "change", "keydown", "keyup", "pointerdown", "pointerup",
        "mouseover", "contextmenu", "dragstart", "drop",
    ]
    MAX_EVENTS_PER_ELEMENT = 3

    def __init__(self, kw: Keywords, rng: random.Random, cfg: JSConfig):
        self.kw = kw
        self.rng = rng
        self.cfg = cfg
        self.vg = ValueGen(kw, rng)

    def generate_handlers(
        self, ctx: GlobalContext
    ) -> list[EventHandler]:
        """num_handlers 개의 이벤트 핸들러를 생성한다."""
        handlers = []
        if not ctx.elements:
            return handlers

        events = self._event_pool()
        targets = self._interactable_elements(ctx) or list(ctx.elements)
        next_id = 0

        for elem in targets:
            event_count = 1
            if self.rng.random() < 0.35:
                event_count += 1
            if self.rng.random() < 0.15:
                event_count += 1
            event_count = min(event_count, self.MAX_EVENTS_PER_ELEMENT)

            used_events = set()
            for _ in range(event_count):
                event = self._pick_unused_event(events, used_events)
                if event is None:
                    break
                used_events.add(event)
                handler = self._make_handler(ctx, elem, event, next_id)
                next_id += 1
                elem.event_attrs[f"on{event}"] = f"{handler.func_id}.call(this, event)"
                handlers.append(handler)

        while len(handlers) < self.cfg.num_handlers:
            elem = self.rng.choice(ctx.elements)
            event = self.rng.choice(events)
            handler = self._make_handler(ctx, elem, event, next_id)
            next_id += 1
            elem.event_attrs.setdefault(f"on{event}", f"{handler.func_id}.call(this, event)")
            handlers.append(handler)

        return handlers

    def _make_handler(
        self, ctx: GlobalContext, target_elem: Element, event: str, func_id: int
    ) -> EventHandler:
        jctx = JSContext()
        stmts = self._gf_generate_statements(ctx, jctx)

        return EventHandler(
            func_id=f"f{func_id}",
            event=event,
            target_element_id=target_elem.id,
            statements=stmts,
        )

    def _event_pool(self) -> list[str]:
        events = self.kw.all_event_types()
        if not events:
            events = list(self.HIGH_VALUE_EVENTS)
        merged = list(self.HIGH_VALUE_EVENTS)
        merged.extend(event for event in events if event not in merged)
        return merged

    def _pick_unused_event(self, events: list[str], used: set[str]) -> str | None:
        candidates = [event for event in events if event not in used]
        if not candidates:
            return None
        high_value = [event for event in self.HIGH_VALUE_EVENTS if event in candidates]
        if high_value and self.rng.random() < 0.85:
            return self.rng.choice(high_value)
        return self.rng.choice(candidates)

    def _interactable_elements(self, ctx: GlobalContext) -> list[Element]:
        return [elem for elem in ctx.elements if self._is_interactable(elem)]

    def _is_interactable(self, elem: Element) -> bool:
        if elem.tag in self.INTERACTABLE_TAGS:
            return True
        if "contenteditable" in elem.attributes:
            return True
        if elem.attributes.get("draggable") == "true":
            return True
        if "tabindex" in elem.attributes:
            return True
        return False

    # ── Gf: API 호출 시퀀스 생성 ──────────────────────────────────────────

    def _gf_generate_statements(
        self, ctx: GlobalContext, jctx: JSContext
    ) -> list[Statement]:
        """이벤트 핸들러 내부 API 호출 시퀀스를 생성한다."""
        stmts: list[Statement] = []
        max_stmts = self.rng.randint(5, self.cfg.max_api_calls_per_handler)

        for _ in range(max_stmts):
            stmt = self._pick_statement(ctx, jctx)
            if stmt:
                stmts.append(stmt)
                jctx.line_count += 1

        return stmts

    def _pick_statement(
        self, ctx: GlobalContext, jctx: JSContext
    ) -> Statement | None:
        """API 호출 / 프로퍼티 대입 / 프로퍼티 읽기 중 하나를 선택해 생성한다."""
        choice = self.rng.choices(
            ["dom_mutation", "self_destruct", "api_call", "property_store", "property_load"],
            weights=[35, 15, 30, 15, 5],
        )[0]

        if choice == "dom_mutation":
            return self._make_dom_mutation(ctx)
        elif choice == "self_destruct":
            return self._make_self_destruct()
        elif choice == "api_call":
            return self._make_api_call(ctx, jctx)
        elif choice == "property_store":
            return self._make_property_store(ctx, jctx)
        else:
            return self._make_property_load(ctx, jctx)

    def _get_receiver_expr(self, ctx: GlobalContext, jctx: JSContext) -> tuple[str, str]:
        """수신자 표현식과 그 타입을 반환한다.

        Returns:
            (expr, type_name)
        """
        # 이미 선언된 로컬 변수를 재사용 (50%)
        if jctx.variables and self.rng.random() < 0.5:
            var = jctx.random_var(self.rng)
            return var.name, var.type_name

        # document.getElementById("xN") 형태
        elem = ctx.random_element(self.rng)
        if elem:
            return f'document.getElementById("{elem.id}")', elem.name

        return "document.body", "HTMLBodyElement"

    def _make_api_call(
        self, ctx: GlobalContext, jctx: JSContext
    ) -> APICall | None:
        """DOM 메서드 호출 하나를 생성한다."""
        receiver_expr, type_name = self._get_receiver_expr(ctx, jctx)

        # 해당 타입에 사용 가능한 메서드 찾기
        method_info = self._find_method(type_name)
        if not method_info:
            # fallback: document 메서드
            method_info = self._random_document_method()
        if not method_info:
            return None

        method_name = method_info.get("name", "")
        raw_args = method_info.get("args", [])
        return_type = method_info.get("return")  # json 은 "return" 키 사용

        # 인자 생성: 각 항목이 {"type": "..."} 형태
        args = []
        for arg in raw_args:
            arg_type = arg.get("type", "string") if isinstance(arg, dict) else str(arg)
            args.append(self.vg.js_arg_for_type(arg_type, ctx))

        # 반환값을 변수에 저장할지 결정
        assign_to = None
        if return_type and self.rng.random() < 0.4 and len(jctx.variables) < self.cfg.max_local_vars:
            var = jctx.add_variable(return_type)
            assign_to = var.name

        return APICall(
            receiver_expr=receiver_expr,
            method=method_name,
            args=args,
            assign_to=assign_to,
            return_type=return_type,
        )

    def _make_property_store(
        self, ctx: GlobalContext, jctx: JSContext
    ) -> PropertyStore | None:
        """DOM 프로퍼티 대입 하나를 생성한다."""
        receiver_expr, type_name = self._get_receiver_expr(ctx, jctx)

        prop_info = self._find_writable_property(type_name)
        if not prop_info:
            return None

        prop_chain = prop_info.get("property", "")
        value_type = prop_info.get("value_type", "string")
        value = self.vg.js_arg_for_type(value_type, ctx)

        return PropertyStore(
            receiver_expr=receiver_expr,
            property_chain=prop_chain,
            value=value,
        )

    def _make_property_load(
        self, ctx: GlobalContext, jctx: JSContext
    ) -> PropertyLoad | None:
        """DOM 프로퍼티 읽기 + 변수 저장."""
        if len(jctx.variables) >= self.cfg.max_local_vars:
            return None

        receiver_expr, type_name = self._get_receiver_expr(ctx, jctx)

        prop_info = self._find_readable_property(type_name)
        if not prop_info:
            return None

        prop_chain = prop_info.get("property", "")
        return_type = prop_info.get("return_type", "Node")

        var = jctx.add_variable(return_type)

        return PropertyLoad(
            receiver_expr=receiver_expr,
            property_chain=prop_chain,
            assign_to=var.name,
            return_type=return_type,
        )

    # ── keywords 조회 헬퍼 ────────────────────────────────────────────────

    def _make_dom_mutation(self, ctx: GlobalContext) -> Statement | None:
        elems = ctx.elements
        if not elems:
            return None

        target = self.rng.choice(elems)
        source = self.rng.choice(elems)
        other = self.rng.choice(elems)
        target_expr = f'document.getElementById("{target.id}")'
        source_expr = f'document.getElementById("{source.id}")'
        other_expr = f'document.getElementById("{other.id}")'
        html_value = self.rng.choice([
            '"<span>fuzz</span>"',
            '"<button autofocus>go</button>"',
            '"<input value=\\"x\\">"',
            '""',
        ])
        text_value = self.vg.string(10)

        pattern = self.rng.choice([
            "remove", "append", "appendChild", "insertBefore", "replaceChildren",
            "innerHTML", "outerHTML", "textContent", "className",
        ])
        if pattern == "remove":
            return RawStatement(f"try {{ {target_expr}.remove(); }} catch(e) {{}}", "dom_mutation")
        if pattern == "append":
            return RawStatement(f"try {{ {target_expr}.append({source_expr}); }} catch(e) {{}}", "dom_mutation")
        if pattern == "appendChild":
            return RawStatement(f"try {{ {target_expr}.appendChild({source_expr}); }} catch(e) {{}}", "dom_mutation")
        if pattern == "insertBefore":
            return RawStatement(f"try {{ {target_expr}.insertBefore({source_expr}, {other_expr}); }} catch(e) {{}}", "dom_mutation")
        if pattern == "replaceChildren":
            return RawStatement(f"try {{ {target_expr}.replaceChildren({source_expr}); }} catch(e) {{}}", "dom_mutation")
        if pattern == "innerHTML":
            return RawStatement(f"try {{ {target_expr}.innerHTML = {html_value}; }} catch(e) {{}}", "dom_mutation")
        if pattern == "outerHTML":
            return RawStatement(f"try {{ {target_expr}.outerHTML = {html_value}; }} catch(e) {{}}", "dom_mutation")
        if pattern == "textContent":
            return RawStatement(f"try {{ {target_expr}.textContent = {text_value!r}; }} catch(e) {{}}", "dom_mutation")
        return RawStatement(f"try {{ {target_expr}.className = {text_value!r}; }} catch(e) {{}}", "dom_mutation")

    def _make_self_destruct(self) -> RawStatement:
        pattern = self.rng.choice([
            "remove", "outerHTML", "innerHTML", "textContent", "className",
        ])
        if pattern == "remove":
            return RawStatement("try { this.remove(); } catch(e) {}", "self_destruct")
        if pattern == "outerHTML":
            return RawStatement('try { this.outerHTML = "<span>replaced</span>"; } catch(e) {}', "self_destruct")
        if pattern == "innerHTML":
            return RawStatement('try { this.innerHTML = "<button autofocus>nested</button>"; } catch(e) {}', "self_destruct")
        if pattern == "textContent":
            return RawStatement('try { this.textContent = "mutated"; } catch(e) {}', "self_destruct")
        return RawStatement('try { this.className = "mutated"; } catch(e) {}', "self_destruct")

    def _find_method(self, type_name: str) -> dict | None:
        """type_name 에 맞는 랜덤 메서드 정보를 반환한다.

        keywords.py 의 methods_for_type() 를 활용한다.
        반환 형식: {name, args: [{type}], return}
        """
        candidates = self.kw.methods_for_type(type_name, include_ancestors=True)
        if not candidates:
            return None
        return self.rng.choice(candidates)

    def _random_document_method(self) -> dict | None:
        """Document 타입 메서드를 랜덤으로 하나 반환한다."""
        methods = self.kw.js_methods.get("Document", [])
        if not methods:
            return None
        return self.rng.choice(methods)

    def _find_writable_property(self, type_name: str) -> dict | None:
        candidates = self.kw.writable_props_for_type(type_name)
        if not candidates:
            return None
        return self.rng.choice(candidates)

    def _find_readable_property(self, type_name: str) -> dict | None:
        candidates = self.kw.readable_props_for_type(type_name)
        if not candidates:
            return None
        return self.rng.choice(candidates)
