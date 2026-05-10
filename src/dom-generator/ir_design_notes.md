# IR 설계 참고사항 (Freedom 코드 분석 기반)

plan.md의 구현 순서 2번(generator/ir/) 작업 시 참고할 문서.
Freedom 코드에서 추출한 설계 패턴과 새 IR에 반영할 차이점을 정리한다.

---

## 1. Freedom의 핵심 설계 패턴

### 1.1 Value 시스템 (Context-Dependent Values)

Freedom의 핵심 혁신. 값을 생성할 때 현재 문서 상태(context)를 참조한다.

```python
# Freedom의 Value 클래스 구조 (참고용)
class Value:
    def generate(self, context):  # context에서 현재 상태를 읽어 값 생성
        pass

class ElementValue(Value):
    def generate(self, context):
        return random.choice(context.elements)  # 트리에 실제 존재하는 엘리먼트 참조

class ClassValue(Value):
    def generate(self, context):
        return random.choice(context.classes)  # 실제 사용 중인 CSS 클래스 참조

class CSSVariableValue(Value):
    def generate(self, context):
        return "var({})".format(random.choice(context.css_variables))
```

**새 IR 반영사항:**
- CSS 셀렉터가 트리에 실제 존재하는 id/class를 참조해야 한다
- JS API의 element 인자가 트리에 있는 실제 엘리먼트를 참조해야 한다
- CSS 변수가 실제 정의된 변수를 참조해야 한다
- filter/clip-path가 실제 존재하는 SVG 엘리먼트를 참조해야 한다

### 1.2 Context 구조

Freedom은 두 레벨의 context를 관리한다.

**GlobalContext (문서 전체):**
- `elements`: 트리 내 모든 엘리먼트 (id → Element 매핑)
- `classes`: 사용 중인 CSS 클래스 이름
- `keyframe_names`: 정의된 @keyframes 이름
- `css_variables`: 정의된 CSS 변수 이름
- `counter_names`: CSS counter 이름
- `filter_ids`: SVG filter 엘리먼트 id
- `clippath_ids`: SVG clipPath 엘리먼트 id

**JSContext (이벤트 핸들러 내부):**
- `variables`: 로컬 변수 목록 (타입 정보 포함)
- `line_count`: 현재 줄 위치
- `available_types`: 현재 스코프에서 사용 가능한 객체 타입

**새 IR 반영사항:**
- GlobalContext는 거의 그대로 유지
- JSContext는 Freedom의 main() 함수가 없으므로 이벤트 핸들러 단위로만 관리
- Freedom은 main()에서 getElementById로 변수를 만드는데, 우리는 이벤트 핸들러 내에서 직접 DOM 접근

### 1.3 엘리먼트 ID 체계

Freedom은 `x0`, `x1`, `x2`, ... 형태의 순차 ID를 사용한다.
- 생성 시 자동 할당
- JS API에서 `document.getElementById("x3")` 형태로 참조
- Mutation 시 새 엘리먼트에도 순차 할당

**새 IR 반영사항:** 동일한 체계 사용. 단, corpus 변환 시 원본 id는 보존하고 별도 내부 id 부여.

---

## 2. Freedom의 IR 클래스 구조

### 2.1 Document

```
Document
├── dom_tree: DOMTree (root = <html>)
│   ├── head
│   │   ├── <style> (css rules)
│   │   ├── <style> (keyframes)
│   │   ├── <style> (css variables)
│   │   └── <script> (functions)
│   └── body
│       └── ... (엘리먼트 트리)
├── css_rules: list[CSSRule]
├── css_keyframes: list[CSSKeyframesRule]
├── css_variables: dict
├── callbacks: list[EventHandler]  # f0~f4
├── main: Function                 # ← 제거
└── context: GlobalContext
```

**새 IR 반영사항:**
- `main` 필드 제거
- `callbacks` → `event_handlers` 이름 변경
- `raw_scripts`: list[RawScript] 필드 추가 (corpus JS 보존용)

### 2.2 Element

Freedom의 Element 구조:
- `name`: 인터페이스 이름 (예: "HTMLDivElement")
- `tag`: 태그 이름 (예: "div")
- `id`: 순차 ID (예: "x0")
- `attributes`: dict[str, Value] — 값이 Value 인스턴스
- `children`: list[Element]
- `text`: str | None
- `tree_depth`: int — 생성 시 제한용

**새 IR 반영사항:**
- 구조 거의 동일
- `attributes`: dict[str, str] — 값을 문자열로 확정 저장 (Value 인스턴스 대신)
  - 생성 시에만 Value 시스템 사용, IR 저장 시점엔 확정 값
- `event_attrs`: dict[str, str] — 이벤트 속성 분리 (예: {"onclick": "f0()"})

### 2.3 CSS 표현

Freedom의 CSS 구조:
```
CSSRule
├── selectors: list[CSSSelector]
└── declarations: list[CSSDeclaration]

CSSSelector
├── element_selector: str (태그/클래스/id)
├── pseudo_class: str | None
├── pseudo_element: str | None
└── combinator: str | None

CSSDeclaration
├── property: str
└── value: str (Value.generate() 결과)

CSSKeyframesRule
├── name: str
└── keyframes: list[CSSKeyframe]
    ├── stop: str ("from", "to", "50%")
    └── declarations: list[CSSDeclaration]
```

**새 IR 반영사항:**
- 구조 동일하게 가져감
- 셀렉터가 context의 실제 id/class를 참조하는 것이 핵심
- CSS 변수: `--css-color`, `--css-length` 등 Freedom 방식 유지

### 2.4 JS 표현

Freedom의 JS 표현:
```
Function (= main())
├── id: str ("main")
├── html_vars: list[HTMLVar]  # getElementById 바인딩
├── apis: list[APICall]       # DOM API 호출 시퀀스
└── is_callback: bool

EventHandler(Function)
├── id: str ("f0")
├── event: str ("click")
└── target_element: Element
```

Freedom의 main() 구조:
```javascript
function main() {
    var v0 = document.getElementById("x0");  // HTMLVar
    var v1 = document.getElementById("x1");  // HTMLVar
    ...
    try { v0.appendChild(v1); } catch(e) {}  // APICall
    try { v1.style.color = "red"; } catch(e) {}  // PropertyStore
    ...
    gc();
}
```

**새 IR 반영사항 (중요 변경):**
- main() 전체 제거, HTMLVar 바인딩도 제거
- EventHandler만 남김:
  ```
  EventHandler
  ├── id: str ("f0")
  ├── event: str ("click")
  ├── target_element: Element
  ├── apis: list[APICall]      # DOM API 호출 시퀀스
  └── context: JSContext
  ```
- 이벤트 핸들러 내부에서 직접 element 접근:
  ```javascript
  function f0() {
      try { document.getElementById("x3").appendChild(document.getElementById("x1")); } catch(e) {}
      try { document.getElementById("x5").style.color = "red"; } catch(e) {}
  }
  ```
- 또는 핸들러 시작 시 로컬 변수 바인딩 후 사용 (Freedom의 HTMLVar 패턴의 축소 버전)

- **RawFunction**: corpus JS 함수 원본 보존
  ```
  RawFunction
  ├── name: str ("drag")
  ├── params: list[str] (["event"])
  └── body: str (원본 JS 코드)
  ```

- **RawInlineScript**: corpus JS 인라인 코드 원본 보존
  ```
  RawInlineScript
  └── code: str (원본 JS 코드)
  ```

---

## 3. 생성 알고리즘 (Freedom → 새 IR)

### 3.1 DOM Tree 생성

| 단계 | Freedom | 새 구현 |
|------|---------|---------|
| Gt1 | 랜덤 위치에 child_rules 준수하며 엘리먼트 삽입 | 동일 |
| Gt2 | attributes.json 기반 속성 추가 (Value 시스템으로 값 생성) | 동일, 값은 즉시 확정 |
| Gt3 | 텍스트 노드 삽입 | 동일 |

핵심 파라미터 (Freedom config.py 기준):
- max_elements: 80, min_elements: 40
- max_depth: 3
- max_attributes: 10

### 3.2 CSS 생성

| 단계 | Freedom | 새 구현 |
|------|---------|---------|
| Gc1 | selector + declarations로 규칙 생성 | 동일 |
| Gc2 | 추가 셀렉터 | 동일 |
| Gc3 | 추가 프로퍼티 | 동일 |

핵심: 셀렉터가 context 내 실제 존재하는 id/class를 참조.

### 3.3 JS 생성

| 단계 | Freedom | 새 구현 |
|------|---------|---------|
| Gf (main) | 1000개 API 호출 시퀀스 생성 | **제거** |
| Gf (handler) | 5개 이벤트 핸들러, 각 수십 API | 유지, API 수 조정 가능 |

이벤트 핸들러 생성 흐름:
1. config에서 핸들러 수 결정 (기본 5개)
2. 각 핸들러에 트리 내 랜덤 엘리먼트 배정
3. context 기반으로 호출 가능한 API 목록 필터
4. 인자 타입에 맞는 값 생성 (hierarchy 참조)

---

## 4. Mutation 알고리즘

### 4.1 DOM Tree Mutation

| op | 설명 | context 업데이트 |
|----|------|-----------------|
| insert_element | 새 엘리먼트 삽입 | elements에 추가 |
| append_attribute | 속성 추가 | class 추가 시 classes 업데이트 |
| mutate_attribute | 속성 값 변경 | - |
| replace_attribute | 속성 교체 | class 변경 시 classes 업데이트 |
| mutate_text | 텍스트 변경 | - |

### 4.2 CSS Mutation

| op | 설명 | context 업데이트 |
|----|------|-----------------|
| append_css_rule | 새 규칙 추가 | - |
| replace_css_rule | 규칙 교체 | - |
| mutate_css_rule | 셀렉터/프로퍼티 변이 | - |
| mutate_css_keyframes | 키프레임 변이 | keyframe_names 업데이트 |

### 4.3 JS Mutation (EventHandler만)

| op | 설명 | context 업데이트 |
|----|------|-----------------|
| append_api | API 호출 추가 | JSContext variables 업데이트 |
| insert_api | API 호출 삽입 | JSContext line_count 조정 |
| replace_api | API 호출 교체 | JSContext variables 업데이트 |
| mutate_api | API 인자 변이 | - |

**중요:** RawFunction/RawInlineScript는 mutation 대상이 아니다.

---

## 5. hierarchy 활용

Freedom은 `OFFSPRINGS`/`ANCESTORS` 딕셔너리로 타입 계층을 관리한다.

활용처:
- JS API 호출 시 "이 타입의 객체에 어떤 메서드가 호출 가능한가?" 결정
  - 예: `HTMLDivElement`는 `HTMLElement` → `Element` → `Node` → `EventTarget`의 모든 메서드 사용 가능
- 프로퍼티 접근 시 상위 타입의 프로퍼티도 포함
- 메서드 반환값 타입으로부터 체인 호출 가능한 메서드 결정

**새 IR 반영사항:**
- `keywords/js/functions.json`의 `hierarchy` 섹션에 포함됨
- IR의 JSContext에서 "현재 변수의 타입 → 호출 가능한 메서드/프로퍼티" 조회에 사용

---

## 6. HTML 출력 구조 (lower/)

```html
<!DOCTYPE html>
<html>
  <head>
    <style>
      /* css_rules */
      #x0 { color: red; }
      .cls0 > div:hover { opacity: 0.5; }
    </style>
    <style>
      /* keyframes */
      @keyframes kf0 { from { opacity: 0; } to { opacity: 1; } }
    </style>
    <style>
      /* css variables */
      :root { --css-color: red; --css-length: 10px; }
    </style>
    <script>
      /* 생성된 이벤트 핸들러 */
      function f0() {
        try { document.getElementById("x3").appendChild(document.getElementById("x1")); } catch(e) {}
      }
      function f1() {
        try { document.getElementById("x5").style.color = "blue"; } catch(e) {}
      }
      /* corpus: RawFunction */
      function drag(event) { ... }
      function drop(event) { ... }
    </script>
    <!-- corpus: RawInlineScript -->
    <script>
      if (window.location.hash=="") { ... }
    </script>
  </head>
  <body>
    <div id="x0" class="cls0" onclick="f0()">
      <span id="x1">text</span>
      <img id="x2" src="about:blank">
    </div>
  </body>
</html>
```

Freedom 대비 제거된 것:
- `<body onload="main()">`
- `function main() { ... }`
- `gc()`, `doNothing()`, `run_count`

---

## 7. 구현 시 주의사항

1. **child_rules 검증**: 엘리먼트 삽입/이동 시 항상 부모-자식 규칙 확인
2. **void 엘리먼트**: empty_elements.json에 있는 태그는 자식/텍스트 불가
3. **SVG namespace**: SVG 엘리먼트는 `xmlns` 처리 필요
4. **mandatory 속성**: svg/attributes.json의 mandatory 섹션 참조
5. **context 일관성**: mutation 후 context를 반드시 업데이트
6. **corpus 보존**: RawFunction/RawInlineScript 내부는 절대 수정하지 않음
7. **try-catch 래핑**: 생성된 API 호출은 모두 try-catch로 감싸서 하나가 실패해도 계속 실행
