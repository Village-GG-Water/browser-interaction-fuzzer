# dom-generator

LibAFL 기반 브라우저 퍼저의 Python 서브모듈. DOM 구조를 가진 HTML 문서를 생성하고 변이하여 퍼저에 공급한다.

[Freedom (CCS 2020)](https://dl.acm.org/doi/10.1145/3372297.3417876)의 FD-IR 방식을 기반으로, corpus JS를 Statement-level IR로 처리하도록 확장했다.

---

## 구조

```
dom-generator/
├── main.py                   # 진입점 (generate / serve 모드)
├── generator/
│   ├── config.py             # TreeConfig, CSSConfig, JSConfig
│   ├── keywords.py           # keywords/ JSON 로더 및 조회 헬퍼
│   ├── ir/                   # 중간 표현(IR) 클래스
│   │   ├── document.py       # Document (최상위 IR 객체)
│   │   ├── element.py        # Element, DOMTree
│   │   ├── css.py            # CSSRule, CSSKeyframesRule, CSSVariables
│   │   ├── js.py             # APICall, RawStatement, ConditionalBlock, ...
│   │   └── context.py        # GlobalContext, JSContext
│   ├── gen/                  # 생성 로직
│   │   ├── generator.py      # DocumentGenerator (진입점)
│   │   ├── dom_tree.py       # DOM 트리 생성
│   │   ├── css_gen.py        # CSS 규칙/키프레임/변수 생성
│   │   ├── js_gen.py         # 이벤트 핸들러 생성 (FD-IR)
│   │   └── value_gen.py      # 타입별 값 생성
│   ├── mutate/               # 변이 로직
│   │   ├── mutator.py        # Mutator 퍼사드 (op 이름 → 담당 mutator 라우팅)
│   │   ├── dom_tree.py       # DOM 변이
│   │   ├── css_mutate.py     # CSS 변이
│   │   └── js_mutate.py      # JS 변이 (Statement-level)
│   └── lower/
│       └── html_writer.py    # Document IR → HTML 문자열
├── keywords/                 # DOM API 명세 JSON
│   ├── html/                 # elements, child_rules, empty_elements, attributes
│   ├── css/                  # properties, selectors, values, at_rules
│   ├── js/                   # methods, properties, events, hierarchy
│   └── svg/                  # elements, attributes, filters
└── corpus/                   # 수동 변환된 PoC 문서
    └── CVE-2025-8882_POC.py  # drag-and-drop UAF PoC
```

---

## IR 개요

Document 하나가 HTML 파일 하나에 대응한다.

```
Document
├── dom_tree: DOMTree              # body 내부 엘리먼트 트리
├── css_rules: list[CSSRule]
├── css_keyframes: list[CSSKeyframesRule]
├── css_variables: CSSVariables
├── event_handlers: list[EventHandler]   # 생성된 핸들러 (f0~f4), 완전 mutation 가능
├── script_functions: list[ScriptFunction]  # corpus JS 함수, Statement-level 분해
├── inline_scripts: list[InlineScript]      # corpus 즉시 실행 코드, Statement-level 분해
└── context: GlobalContext
```

### JS IR — Statement 타입

| 타입 | 내용 변이 | 위치 이동/삭제 |
|------|-----------|----------------|
| `APICall` | 가능 (인자, 수신자) | 가능 |
| `PropertyStore` | 가능 (값) | 가능 |
| `PropertyLoad` | 가능 | 가능 |
| `RawStatement` | **불가** (원본 보존) | 가능 |
| `ConditionalBlock` | condition 불가, 내부 branch 가능 | 가능 |

corpus JS에서 `event.*`, `window.*`, `setTimeout` 등 FD-IR로 표현 불가능한 코드는 `RawStatement`로 보존되고, `document.getElementById` / `removeChild` 등 DOM 메서드는 `APICall`로 변환된다.

---

## Mutation ops

### DOM
| op | 설명 |
|----|------|
| `insert_element` | 엘리먼트 삽입 |
| `append_attribute` | 속성 추가 |
| `mutate_attribute` | 속성 값 변이 |
| `replace_attribute` | 속성 교체 |
| `mutate_text` | 텍스트 노드 변이 |

### CSS
| op | 설명 |
|----|------|
| `append_css_rule` | 규칙 추가 |
| `replace_css_rule` | 규칙 교체 |
| `mutate_css_rule` | 셀렉터/선언 변이 |
| `mutate_css_keyframes` | 키프레임 변이 |

### JS
| op | 대상 | 설명 |
|----|------|------|
| `append_api` | EventHandler | 핸들러 끝에 API 호출 추가 |
| `insert_api` | EventHandler | 핸들러 임의 위치에 API 호출 삽입 |
| `replace_api` | EventHandler | 핸들러 내 문장 교체 |
| `mutate_api` | EventHandler | API 호출 인자 변이 |
| `reorder_statement` | 전체 | 임의 statement 리스트에서 두 문장 순서 교환 |
| `remove_statement` | 전체 | 임의 문장 제거 (최소 1개 유지) |
| `insert_statement` | 전체 | 임의 위치에 새 APICall 삽입 |
| `mutate_api_args` | 전체 | 문서 전체에서 APICall 인자 하나 변이 |

"전체"는 EventHandler, ScriptFunction, InlineScript, ConditionalBlock 내부 branch까지 재귀적으로 대상이 됨을 의미한다.

---

## 사용법

### 독립 실행 (개발/디버깅)

```bash
# HTML 1개를 stdout으로 출력
python main.py generate -n 1 --stdout

# HTML 5개를 output/ 디렉토리에 저장
python main.py generate -n 5 -o output/

# 재현 가능한 생성 (시드 고정)
python main.py generate -n 1 --stdout --seed 42
```

### 퍼저 서버 모드

```bash
python main.py serve
```

Rust 퍼저와 stdin/stdout JSON 프로토콜로 통신한다.

```jsonc
// 새 문서 생성
→ {"cmd": "generate"}
← {"html": "<!DOCTYPE html>..."}

// corpus 로드
→ {"cmd": "load_corpus", "id": "CVE-2025-8882_POC"}
← {"ok": true}

// corpus 변이 후 HTML 반환
→ {"cmd": "mutate", "id": "CVE-2025-8882_POC", "ops": ["reorder_statement", "mutate_api_args"]}
← {"html": "<!DOCTYPE html>..."}

// corpus 원본으로 리셋
→ {"cmd": "reset", "id": "CVE-2025-8882_POC"}
← {"ok": true}

// 로드된 corpus 목록
→ {"cmd": "list_corpus"}
← {"corpus": ["CVE-2025-8882_POC"]}
```

corpus는 처음 로드 시 `.fdir` (pickle)로 캐싱되고, 이후에는 캐시에서 읽는다.

---

## Corpus 변환

`corpus/` 디렉토리에 `build() -> Document`를 반환하는 `.py` 파일을 추가하면 된다.

```python
# corpus/MY_CVE_POC.py
from generator.ir.js import APICall, RawStatement, ScriptFunction, InlineScript
from generator.ir.document import Document

def build() -> Document:
    ...
    return Document(
        script_functions=[ScriptFunction(name="vuln_func", ...)],
        inline_scripts=[InlineScript(...)],
        ...
    )
```

---

## 설정

`generator/config.py`에서 생성 파라미터를 조정한다.

```python
GeneratorConfig(
    tree=TreeConfig(
        min_elements=40, max_elements=80,
        max_depth=3, svg_prob=0.2,
    ),
    css=CSSConfig(
        max_rules=50, max_keyframes=5,
        num_css_variables=4,
    ),
    js=JSConfig(
        num_handlers=5,
        max_api_calls_per_handler=30,
        max_local_vars=5,
    ),
    seed=None,  # None이면 무작위
)
```

---

## 의존성

- Python 3.10+
- 표준 라이브러리만 사용 (외부 패키지 없음)
