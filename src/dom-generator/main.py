"""
DOM Generator 진입점.

두 가지 모드:
  generate  — 샘플 HTML 파일을 생성한다 (개발/디버깅용)
  serve     — Rust 퍼저와 stdin/stdout JSON 프로토콜로 통신한다

사용법:
  python main.py generate -n 5 -o output/
  python main.py generate -n 1 --stdout
  python main.py serve
"""

from __future__ import annotations
import argparse
import json
import os
import sys
import pickle
from pathlib import Path

# generator 패키지를 임포트하기 위해 프로젝트 루트를 path 에 추가
sys.path.insert(0, str(Path(__file__).parent))

from generator.config import CSSConfig, GeneratorConfig, JSConfig, TreeConfig
from generator.gen.generator import DocumentGenerator
from generator.mutate.mutator import Mutator
from generator.lower.html_writer import render

_CORPUS_DIR = Path(__file__).parent / "corpus"
_CORPUS_CACHE: dict[str, object] = {}  # id → Document (로드된 corpus)
_CORPUS_ORIGINALS: dict[str, object] = {}  # id → Document (reset 용 원본)


# ── generate 모드 ──────────────────────────────────────────────────────────

def cmd_generate(args) -> None:
    cfg = GeneratorConfig(seed=args.seed if hasattr(args, "seed") else None)
    gen = DocumentGenerator(cfg)

    if args.stdout:
        doc = gen.generate()
        print(render(doc))
        return

    out_dir = Path(args.output)
    out_dir.mkdir(parents=True, exist_ok=True)

    for i in range(args.n):
        doc = gen.generate()
        html = render(doc)
        out_path = out_dir / f"sample_{i:04d}.html"
        out_path.write_text(html, encoding="utf-8")
        print(f"[generate] {out_path}", file=sys.stderr)


# ── serve 모드 ────────────────────────────────────────────────────────────

def cmd_serve() -> None:
    """stdin 으로 JSON 명령을 읽고 stdout 으로 JSON 응답을 쓴다.

    프로토콜:
      → {"cmd": "generate"}
      ← {"html": "<!DOCTYPE html>..."}

      → {"cmd": "load_corpus", "id": "CVE-2025-8882"}
      ← {"ok": true}

      → {"cmd": "mutate", "id": "CVE-2025-8882", "ops": ["mutate_attr", ...]}
      ← {"html": "<!DOCTYPE html>..."}

      → {"cmd": "reset", "id": "CVE-2025-8882"}
      ← {"ok": true}

      → {"cmd": "list_corpus"}
      ← {"corpus": ["CVE-2025-8882", ...]}
    """
    gen = DocumentGenerator()
    mutator = Mutator()

    # stderr 로 준비 완료 신호
    print("[serve] ready", file=sys.stderr, flush=True)

    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue

        try:
            req = json.loads(line)
        except json.JSONDecodeError as e:
            _respond({"error": f"JSON parse error: {e}"})
            continue

        if req.get("cmd") == "shutdown":
            _respond({"status": "ok"})
            break

        try:
            resp = _handle(req, gen, mutator)
        except Exception as e:
            resp = {"error": str(e)}

        _respond(resp)


def _handle(req: dict, gen: DocumentGenerator, mutator: Mutator) -> dict:
    cmd = req.get("cmd")

    if cmd == "generate_document":
        budget = req.get("budget")
        local_gen = DocumentGenerator(_config_from_budget(budget)) if budget else gen
        doc = local_gen.generate()
        output_fdir = req.get("output_fdir")
        if output_fdir:
            _save_document_path(doc, output_fdir)
        return _document_response(doc)

    elif cmd == "load_document":
        doc = _load_document_path(req.get("path", ""))
        return _document_response(doc)

    elif cmd == "mutate_document":
        source_path = req.get("source_path", "")
        output_path = req.get("output_path", "")
        ops = req.get("ops", [])
        doc = _load_document_path(source_path)
        mutator.apply_ops(doc, ops)
        if hasattr(doc, "rebuild_context"):
            doc.rebuild_context()
        if output_path:
            _save_document_path(doc, output_path)
        return _document_response(doc)

    elif cmd == "render_document":
        doc = _load_document_path(req.get("path", ""))
        return {"html": render(doc)}

    elif cmd == "extract_metadata":
        doc = _load_document_path(req.get("path", ""))
        return {
            "interactables": _extract_interactables(doc),
            "action_hints": _infer_action_hints(doc, _extract_interactables(doc)),
        }

    elif cmd == "generate":
        doc = gen.generate()
        return _document_response(doc)

    elif cmd == "discover_corpus":
        return {"corpus": _discover_corpus()}

    elif cmd == "get_corpus":
        corpus_id = req.get("id", "")
        doc = _load_corpus(corpus_id)
        return _document_response(doc, corpus_id=corpus_id)

    elif cmd == "load_corpus":
        corpus_id = req.get("id", "")
        _load_corpus(corpus_id)
        return {"ok": True}

    elif cmd == "mutate":
        corpus_id = req.get("id", "")
        ops = req.get("ops", [])
        doc = _get_corpus_doc(corpus_id)
        if doc is None:
            return {"error": f"corpus not loaded: {corpus_id!r}"}
        mutator.apply_ops(doc, ops)
        return {"html": render(doc)}

    elif cmd == "reset":
        corpus_id = req.get("id", "")
        if corpus_id not in _CORPUS_ORIGINALS:
            return {"error": f"corpus not loaded: {corpus_id!r}"}
        original = _CORPUS_ORIGINALS[corpus_id]
        _CORPUS_CACHE[corpus_id] = original.clone()
        return {"ok": True}

    elif cmd == "list_corpus":
        return {"corpus": list(_CORPUS_CACHE.keys())}

    else:
        return {"error": f"unknown cmd: {cmd!r}"}


def _document_response(doc, corpus_id: str | None = None) -> dict:
    interactables = _extract_interactables(doc)
    action_hints = (
        _load_action_hints(corpus_id) if corpus_id is not None else None
    ) or _infer_action_hints(doc, interactables)
    return {
        "id": corpus_id,
        "html": render(doc),
        "interactables": interactables,
        "action_hints": action_hints,
        "stats": _document_stats(doc),
    }


def _config_from_budget(budget: dict) -> GeneratorConfig:
    tree = TreeConfig(
        min_elements=_int_budget(budget, "min_elements", 3),
        max_elements=_int_budget(budget, "max_elements", 5),
        max_depth=_int_budget(budget, "max_depth", 2),
        max_attributes=_int_budget(budget, "max_attributes", 2),
        svg_prob=0.0,
    )
    css = CSSConfig(
        max_rules=_int_budget(budget, "max_css_rules", 0),
        min_rules=0,
        max_keyframes=_int_budget(budget, "max_keyframes", 0),
        num_css_variables=_int_budget(budget, "max_css_variables", 0),
    )
    js = JSConfig(
        num_handlers=_int_budget(budget, "max_handlers", 2),
        min_api_calls_per_handler=_int_budget(budget, "min_handler_statements", 3),
        max_api_calls_per_handler=_int_budget(budget, "max_handler_statements", 5),
    )
    return GeneratorConfig(tree=tree, css=css, js=js)


def _int_budget(budget: dict, key: str, default: int) -> int:
    try:
        return max(0, int(budget.get(key, default)))
    except (TypeError, ValueError):
        return default


def _document_stats(doc) -> dict:
    handlers = list(getattr(doc, "event_handlers", []))
    return {
        "element_count": len(list(doc.dom_tree.walk())) if getattr(doc, "dom_tree", None) else 0,
        "handler_count": len(handlers),
        "handler_statement_count": sum(len(getattr(h, "statements", [])) for h in handlers),
        "css_rule_count": len(getattr(doc, "css_rules", [])),
        "keyframe_count": len(getattr(doc, "css_keyframes", [])),
    }


def _respond(data: dict) -> None:
    print(json.dumps(data, ensure_ascii=False), flush=True)


def _save_document_path(doc, raw_path: str) -> None:
    path = Path(raw_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "wb") as f:
        pickle.dump(doc, f)


def _load_document_path(raw_path: str):
    if not raw_path:
        raise ValueError("missing document path")
    path = Path(raw_path)
    if not path.exists():
        raise FileNotFoundError(f"Document not found: {path}")
    with open(path, "rb") as f:
        return pickle.load(f)


def _load_corpus(corpus_id: str):
    """corpus/ 디렉토리에서 ID에 해당하는 문서를 로드한다.

    .fdir (pickle) 파일이 있으면 그것을 사용하고,
    없으면 .py 변환 스크립트를 실행한다.
    """
    fdir_path = _CORPUS_DIR / f"{corpus_id}.fdir"
    py_path = _CORPUS_DIR / f"{corpus_id}.py"

    if not corpus_id or any(ch in corpus_id for ch in ("/", "\\", ":", "..")):
        raise ValueError(f"Invalid corpus id: {corpus_id!r}")

    if fdir_path.exists():
        try:
            with open(fdir_path, "rb") as f:
                doc = pickle.load(f)
        except Exception:
            if not py_path.exists():
                raise
            doc = _build_corpus_from_py(corpus_id, py_path)
    elif py_path.exists():
        doc = _build_corpus_from_py(corpus_id, py_path)
        # .fdir 로 캐싱
        with open(fdir_path, "wb") as f:
            pickle.dump(doc, f)
    else:
        raise FileNotFoundError(
            f"Corpus not found: {corpus_id!r} "
            f"(expected {fdir_path} or {py_path})"
        )

    _CORPUS_ORIGINALS[corpus_id] = doc
    _CORPUS_CACHE[corpus_id] = doc.clone()
    return _CORPUS_CACHE[corpus_id]


def _get_corpus_doc(corpus_id: str):
    return _CORPUS_CACHE.get(corpus_id)


def _build_corpus_from_py(corpus_id: str, py_path: Path):
    import importlib.util
    spec = importlib.util.spec_from_file_location(corpus_id, py_path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.build()  # 변환 스크립트는 build() 함수를 정의해야 함


def _discover_corpus() -> list[str]:
    ids = set()
    if not _CORPUS_DIR.exists():
        return []
    for path in _CORPUS_DIR.iterdir():
        if path.suffix in {".fdir", ".py"} and not path.name.startswith("__"):
            ids.add(path.stem)
    return sorted(ids)


def _extract_interactables(doc) -> list[dict]:
    handler_events = {}
    for handler in getattr(doc, "event_handlers", []):
        handler_events.setdefault(handler.target_element_id, set()).add(handler.event)

    items = []
    for elem in doc.dom_tree.walk():
        events = set()
        for attr in elem.event_attrs:
            if attr.startswith("on") and len(attr) > 2:
                events.add(attr[2:].lower())
        events.update(handler_events.get(elem.id, set()))

        tag = elem.tag.lower()
        attrs = {k.lower(): str(v).lower() for k, v in elem.attributes.items()}
        is_text_input = tag in {"input", "textarea", "select"} or "contenteditable" in attrs
        is_draggable = attrs.get("draggable") == "true" or "dragstart" in events
        is_drop_target = "drop" in events or "dragover" in events
        is_focusable = (
            tag in {"a", "button", "input", "textarea", "select"}
            or "tabindex" in attrs
            or is_text_input
        )
        has_handler = bool(events) or bool(elem.event_attrs)
        is_interactable = (
            has_handler
            or is_text_input
            or is_draggable
            or is_drop_target
            or is_focusable
            or tag in {"details", "summary", "dialog", "iframe", "canvas", "video", "audio"}
        )
        if not is_interactable:
            continue

        items.append({
            "selector": f"#{elem.id}",
            "tag": elem.tag,
            "events": sorted(events),
            "is_text_input": is_text_input,
            "is_draggable": is_draggable,
            "is_drop_target": is_drop_target,
            "is_focusable": is_focusable,
            "has_handler": has_handler,
        })
    return items


def _infer_action_hints(doc, interactables: list[dict]) -> list[dict]:
    hints = []
    by_event = {}
    for item in interactables:
        for event in item.get("events", []):
            by_event.setdefault(event, []).append(item)

    drag_sources = [i for i in interactables if i.get("is_draggable")]
    drop_targets = [i for i in interactables if i.get("is_drop_target")]
    if drag_sources and drop_targets:
        hints.append({
            "kind": "drag_drop",
            "target": {"space": "dom", "selector": drag_sources[0]["selector"]},
            "to": {"space": "dom", "selector": drop_targets[0]["selector"]},
        })

    for item in interactables:
        selector = item["selector"]
        target = {"space": "dom", "selector": selector}
        events = set(item.get("events", []))
        if events & {"click", "mousedown", "mouseup", "pointerdown", "pointerup", "contextmenu"}:
            hints.append({"kind": "click", "target": target})
        if events & {"mouseover", "mouseenter", "pointerover"}:
            hints.append({"kind": "hover", "target": target})
        if item.get("is_text_input") or events & {"input", "change"}:
            hints.append({"kind": "type_text", "target": target, "text": "fuzz"})
        if item.get("is_focusable") or events & {"focus", "blur"}:
            hints.append({"kind": "focus", "target": target})

    if _document_has_timer(doc):
        hints.append({"kind": "sleep", "millis": 50})

    return _dedupe_actions(hints)


def _document_has_timer(doc) -> bool:
    def walk_statements(statements):
        for stmt in statements:
            tag = getattr(stmt, "tag", None)
            code = getattr(stmt, "code", "")
            if tag == "timer" or "setTimeout" in code or "requestAnimationFrame" in code:
                return True
            for branch_name in ("then_branch", "else_branch"):
                branch = getattr(stmt, branch_name, None)
                if branch and walk_statements(branch):
                    return True
        return False

    for handler in getattr(doc, "event_handlers", []):
        if walk_statements(handler.statements):
            return True
    for func in getattr(doc, "script_functions", []):
        if walk_statements(func.statements):
            return True
    for script in getattr(doc, "inline_scripts", []):
        if walk_statements(script.statements):
            return True
    return False


def _load_action_hints(corpus_id: str) -> list[dict] | None:
    sidecar = _CORPUS_DIR / f"{corpus_id}.actions.json"
    if not sidecar.exists():
        return None
    with open(sidecar, "r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, list):
        raise ValueError(f"{sidecar.name} must contain a JSON array")
    for action in data:
        if not isinstance(action, dict) or not isinstance(action.get("type"), str):
            raise ValueError(f"Invalid action in {sidecar.name}: {action!r}")
    return data


def _dedupe_actions(actions: list[dict]) -> list[dict]:
    seen = set()
    out = []
    for action in actions:
        key = json.dumps(action, sort_keys=True)
        if key in seen:
            continue
        seen.add(key)
        out.append(action)
    return out


# ── CLI ───────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="DOM Generator")
    sub = parser.add_subparsers(dest="mode", required=True)

    # generate 서브커맨드
    gen_p = sub.add_parser("generate", help="샘플 HTML 생성")
    gen_p.add_argument("-n", type=int, default=1, help="생성할 파일 수 (기본: 1)")
    gen_p.add_argument("-o", "--output", default="output", help="출력 디렉토리 (기본: output/)")
    gen_p.add_argument("--stdout", action="store_true", help="파일 대신 stdout 으로 출력")
    gen_p.add_argument("--seed", type=int, default=None, help="랜덤 시드 (재현용)")

    # serve 서브커맨드
    sub.add_parser("serve", help="Rust 퍼저와 JSON IPC 통신")

    args = parser.parse_args()

    if args.mode == "generate":
        cmd_generate(args)
    elif args.mode == "serve":
        cmd_serve()


if __name__ == "__main__":
    main()
