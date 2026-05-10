"""
JS 변이 (Statement-level).

EventHandler 및 ScriptFunction / InlineScript 의 statement 리스트가 대상.
ConditionalBlock 내부 분기도 재귀적으로 대상이 된다.

EventHandler ops (생성된 핸들러):
  append_api        — API 호출 추가 (Gf)
  insert_api        — API 호출 삽입 (Mf1)
  replace_api       — API 호출 교체 (Mf2)
  mutate_api        — API 인자 변이 (Mf3)

Statement-level ops (EventHandler + ScriptFunction + InlineScript 공통):
  reorder_statement — 문장 순서 변경
  remove_statement  — 문장 제거
  insert_statement  — 새 APICall 삽입
  mutate_api_args   — APICall 인자 변이

RawStatement 는 내부 code 수정 불가, 위치 이동/삭제만 가능.
ConditionalBlock.condition 수정 불가.
"""

from __future__ import annotations
import random
from generator.ir.document import Document
from generator.ir.js import (
    EventHandler, ScriptFunction, InlineScript,
    APICall, PropertyStore, PropertyLoad,
    RawStatement, ConditionalBlock, Statement,
)
from generator.ir.context import GlobalContext, JSContext
from generator.keywords import Keywords
from generator.gen.js_gen import JSGenerator
from generator.config import JSConfig


def _collect_statement_lists(doc: Document) -> list[list[Statement]]:
    """문서 내 모든 mutation 가능한 statement 리스트를 수집한다.

    EventHandler, ScriptFunction, InlineScript 의 statements,
    그리고 ConditionalBlock 내부 분기까지 재귀적으로 수집한다.
    """
    results = []

    def collect_from(stmts: list[Statement]) -> None:
        results.append(stmts)
        for stmt in stmts:
            if isinstance(stmt, ConditionalBlock):
                collect_from(stmt.then_branch)
                if stmt.else_branch is not None:
                    collect_from(stmt.else_branch)

    for h in doc.event_handlers:
        collect_from(h.statements)
    for f in doc.script_functions:
        collect_from(f.statements)
    for s in doc.inline_scripts:
        collect_from(s.statements)

    return results


def _mutable_api_calls(stmts: list[Statement]) -> list[APICall]:
    """statement 리스트에서 APICall만 재귀적으로 추출한다."""
    results = []
    for stmt in stmts:
        if isinstance(stmt, APICall):
            results.append(stmt)
        elif isinstance(stmt, ConditionalBlock):
            results.extend(_mutable_api_calls(stmt.then_branch))
            if stmt.else_branch:
                results.extend(_mutable_api_calls(stmt.else_branch))
    return results


class JSMutator:
    def __init__(self, kw: Keywords, rng: random.Random, cfg: JSConfig):
        self.kw = kw
        self.rng = rng
        self.cfg = cfg
        self._gen = JSGenerator(kw, rng, cfg)

    def apply(self, doc: Document, op: str) -> bool:
        ctx = doc.context

        # EventHandler 전용 ops
        if op in ("append_api", "insert_api", "replace_api", "mutate_api"):
            if not doc.event_handlers:
                return False
            handler = self.rng.choice(doc.event_handlers)
            if op == "append_api":
                return self._append_api(handler.statements, ctx)
            elif op == "insert_api":
                return self._insert_api(handler.statements, ctx)
            elif op == "replace_api":
                return self._replace_api(handler.statements, ctx)
            elif op == "mutate_api":
                return self._mutate_api_args(handler.statements, ctx)

        # Statement-level ops (모든 컨테이너 대상)
        all_lists = _collect_statement_lists(doc)
        non_empty = [sl for sl in all_lists if sl]

        if op == "reorder_statement":
            return self._reorder_statement(non_empty)
        elif op == "remove_statement":
            return self._remove_statement(non_empty)
        elif op == "insert_statement":
            if not all_lists:
                return False
            target = self.rng.choice(all_lists)
            return self._insert_api(target, ctx)
        elif op == "mutate_api_args":
            return self._mutate_api_args_global(doc, ctx)
        else:
            raise ValueError(f"Unknown JS mutation op: {op!r}")

    # ── EventHandler 전용 ops ─────────────────────────────────────────────

    def _append_api(self, stmts: list[Statement], ctx: GlobalContext) -> bool:
        jctx = self._jctx_from(stmts)
        stmt = self._gen._pick_statement(ctx, jctx)
        if stmt is None:
            return False
        stmts.append(stmt)
        return True

    def _insert_api(self, stmts: list[Statement], ctx: GlobalContext) -> bool:
        jctx = self._jctx_from(stmts)
        stmt = self._gen._pick_statement(ctx, jctx)
        if stmt is None:
            return False
        idx = self.rng.randrange(len(stmts) + 1)
        stmts.insert(idx, stmt)
        return True

    def _replace_api(self, stmts: list[Statement], ctx: GlobalContext) -> bool:
        if not stmts:
            return False
        jctx = self._jctx_from(stmts)
        new_stmt = self._gen._pick_statement(ctx, jctx)
        if new_stmt is None:
            return False
        idx = self.rng.randrange(len(stmts))
        stmts[idx] = new_stmt
        return True

    def _mutate_api_args(self, stmts: list[Statement], ctx: GlobalContext) -> bool:
        from generator.gen.value_gen import ValueGen
        vg = ValueGen(self.kw, self.rng)
        api_calls = _mutable_api_calls(stmts)
        if not api_calls:
            return False
        call = self.rng.choice(api_calls)
        if not call.args:
            return False
        idx = self.rng.randrange(len(call.args))
        old_arg = call.args[idx]
        if old_arg.startswith('"') or old_arg.startswith("'"):
            new_val = f'"{vg.string()}"'
        elif old_arg in ("true", "false"):
            new_val = self.rng.choice(["true", "false"])
        elif old_arg.lstrip("-").isdigit():
            new_val = str(self.rng.randint(0, 100))
        elif "getElementById" in old_arg:
            new_val = vg.get_element_expr(ctx)
        else:
            new_val = vg.js_arg_for_type("string", ctx)
        call.args[idx] = new_val
        return True

    # ── Statement-level ops ──────────────────────────────────────────────

    def _reorder_statement(self, non_empty_lists: list[list[Statement]]) -> bool:
        """무작위 statement 리스트에서 두 문장의 순서를 바꾼다."""
        if not non_empty_lists:
            return False
        target = self.rng.choice(non_empty_lists)
        if len(target) < 2:
            return False
        i, j = self.rng.sample(range(len(target)), 2)
        target[i], target[j] = target[j], target[i]
        return True

    def _remove_statement(self, non_empty_lists: list[list[Statement]]) -> bool:
        """무작위 statement 하나를 제거한다.

        최소 1개는 남긴다.
        """
        candidates = [sl for sl in non_empty_lists if len(sl) > 1]
        if not candidates:
            return False
        target = self.rng.choice(candidates)
        idx = self.rng.randrange(len(target))
        target.pop(idx)
        return True

    def _mutate_api_args_global(self, doc: Document, ctx: GlobalContext) -> bool:
        """문서 전체에서 APICall 인자 하나를 변이한다."""
        all_lists = _collect_statement_lists(doc)
        all_calls: list[APICall] = []
        for sl in all_lists:
            all_calls.extend(_mutable_api_calls(sl))
        if not all_calls:
            return False
        call = self.rng.choice(all_calls)
        if not call.args:
            return False
        from generator.gen.value_gen import ValueGen
        vg = ValueGen(self.kw, self.rng)
        idx = self.rng.randrange(len(call.args))
        old_arg = call.args[idx]
        if old_arg.startswith('"') or old_arg.startswith("'"):
            call.args[idx] = f'"{vg.string()}"'
        elif "getElementById" in old_arg:
            call.args[idx] = vg.get_element_expr(ctx)
        else:
            call.args[idx] = vg.js_arg_for_type("string", ctx)
        return True

    # ── 내부 헬퍼 ────────────────────────────────────────────────────────

    def _jctx_from(self, stmts: list[Statement]) -> JSContext:
        """statement 리스트로부터 JSContext를 간단하게 재구성한다."""
        jctx = JSContext()
        for stmt in stmts:
            if isinstance(stmt, (APICall, PropertyLoad)):
                if getattr(stmt, "assign_to", None):
                    rt = getattr(stmt, "return_type", None) or "Node"
                    jctx.add_variable(rt)
            jctx.line_count += 1
        return jctx
