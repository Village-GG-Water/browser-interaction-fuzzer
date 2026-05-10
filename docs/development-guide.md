# 개발 가이드

이 문서는 `browser-interaction-fuzzer`의 협업용 개발 문서입니다. 특히 user interaction simulator를 맡는 개발자가 Rust engine과 맞춰 구현해야 하는 경계를 설명합니다.

## 전체 구조

```text
fuzzing_engine (Rust + LibAFL)
  - LibAFL StdFuzzer/QueueScheduler 기반 fuzz loop
  - seed/corpus 선택
  - mutation strategy 선택
  - DOM mutation op sequence 선택
  - action sequence 생성/변이
  - SanCov coverage feedback, crash objective, metrics 관리

dom-generator (Python)
  - DOM IR 생성
  - .fdir 로드/저장
  - Rust가 요청한 DOM/CSS/JS mutation op 적용
  - HTML render
  - interactable metadata 추출

user-interaction-simulator (Python)
  - 브라우저 실행
  - DOM action 실행
  - 향후 browser UI action 실행
  - action 실행 결과, timing, crash signal 반환
```

## Seed 포맷

seed 디렉토리 하나가 재현 가능한 브라우저 testcase 하나입니다.

```text
corpus/seeds/seed_000001/
  testcase.json
  document.fdir
  actions.json
  metadata.json
  snapshot.html
```

`testcase.json`은 실행 명세입니다.

```json
{
  "schema_version": 1,
  "seed_id": "seed_000001",
  "document": {
    "kind": "fdir",
    "path": "document.fdir"
  },
  "interaction_scope": ["dom", "browser_ui"],
  "actions_path": "actions.json"
}
```

UI-only seed는 문서가 없습니다.

```json
{
  "schema_version": 1,
  "seed_id": "seed_ui_000001",
  "document": {
    "kind": "none",
    "initial_url": "about:blank"
  },
  "interaction_scope": ["browser_ui"],
  "actions_path": "actions.json"
}
```

v1에서 실제 구현하는 `document.kind`는 `fdir`와 `none`입니다.

## Action 모델

모든 action은 `kind`와 optional target을 가집니다.

DOM action:

```json
{
  "kind": "click",
  "target": {
    "space": "dom",
    "selector": "#x1"
  }
}
```

Browser UI action:

```json
{
  "kind": "click",
  "target": {
    "space": "browser_ui",
    "role": "button",
    "name": "Reload"
  }
}
```

`browser_ui` target은 v1에서 protocol과 타입만 준비되어 있습니다. 실제 구현은 접근성 API backend를 추가하면서 연결합니다.

## Engine ↔ dom-generator protocol

JSON-lines stdin/stdout을 사용합니다. stdout은 JSON response 전용이어야 합니다.

요청 종류:

- `generate_document`: 새 DOM 문서를 만들고 optional `.fdir` 경로에 저장합니다.
- `load_document`: `.fdir`을 열어 HTML과 metadata를 반환합니다.
- `mutate_document`: `.fdir`을 열고 Rust가 선택한 mutation op를 적용한 뒤 새 `.fdir`로 저장합니다.
- `render_document`: `.fdir`을 HTML로 render합니다.
- `extract_metadata`: `.fdir`에서 interactable metadata와 action hint를 추출합니다.

`mutate_document` 예시:

```json
{
  "cmd": "mutate_document",
  "source_path": "corpus/seeds/seed_000001/document.fdir",
  "output_path": "out/iterations/000001/document.fdir",
  "ops": ["insert_element", "mutate_api_args"]
}
```

응답은 가능한 한 같은 shape을 유지합니다.

```json
{
  "id": null,
  "html": "<!DOCTYPE html>...",
  "interactables": [],
  "action_hints": []
}
```

## Engine ↔ simulator protocol

JSON-lines stdin/stdout을 사용합니다. 로그는 stderr로만 출력합니다.

초기화:

```json
{
  "cmd": "initialize",
  "protocol_version": 1,
  "browser_path": "D:\\programs\\chromium\\src\\out\\asan_cov\\chrome.exe",
  "browser_kind": "chromium",
  "sancov_dir": "out/sancov",
  "asan_dir": "out/asan",
  "out_dir": "out"
}
```

실행:

```json
{
  "cmd": "run_testcase",
  "protocol_version": 1,
  "iteration": 1,
  "seed_id": "seed_000001",
  "html_path": "out/iterations/000001/snapshot.html",
  "initial_url": null,
  "actions": []
}
```

UI-only testcase는 `html_path = null`이고 `initial_url`을 사용합니다.

응답:

```json
{
  "status": "ok",
  "actions_attempted": 6,
  "actions_succeeded": 4,
  "selector_fallbacks": 1,
  "slow_actions": 0,
  "timings": {
    "launch_ms": 100,
    "load_ms": 30,
    "actions_ms": 70,
    "close_ms": 20,
    "simulator_total_ms": 220
  }
}
```

`status` 값은 `ok`, `timeout`, `crash`, `error` 중 하나입니다.

## Rust 모듈 책임

- `actions.rs`: action data model과 JSON wire format.
- `input.rs`: LibAFL `Input`인 `FuzzInput`.
- `corpus.rs`: seed 디렉토리 읽기/쓰기.
- `mutation/`: 모든 mutation 정책.
- `mutation/libafl_mutator.rs`: mutation 정책을 LibAFL `Mutator`로 연결.
- `clients/dom_generator.rs`: dom-generator IPC.
- `clients/simulator.rs`: simulator IPC.
- `testcase_runner.rs`: testcase 실행, coverage/crash artifact 수집.
- `libafl_executor.rs`: simulator harness를 LibAFL `Executor`로 감싸는 adapter.
- `metrics.rs`: 수치 수집과 avg/p95 계산.
- `reporting.rs`: 사람이 읽는 실행 상태 출력.

## 향후 확장

### Browser UI backend

접근성 API 기반 backend를 추가하면 `target.space = "browser_ui"` action을 실제로 실행합니다. 이때 Rust action wire format은 유지하고, simulator 내부 backend만 확장합니다.

### Multi-page testcase

일부 취약점은 여러 페이지, 탭, popup, navigation 상태를 필요로 할 수 있습니다. v1에서는 구현하지 않지만 `testcase.json`은 다음 형태로 확장할 수 있어야 합니다.

```json
{
  "document": {
    "kind": "multi_page",
    "pages": [
      {"id": "page_0", "path": "page_0.fdir", "snapshot": "page_0.html"},
      {"id": "page_1", "path": "page_1.fdir", "snapshot": "page_1.html"}
    ],
    "entry_page": "page_0"
  }
}
```

이 확장이 들어오면 action target에도 page/tab context가 필요합니다.

### Corpus 장기 포맷

`.fdir`은 Python pickle입니다. 구현은 빠르지만 dom-generator IR 변경에 취약합니다. 장기적으로는 replay 가능한 manifest 또는 JSON IR 포맷을 검토합니다.

### Mutation history

mutation history를 저장하면 coverage/crash에 기여한 mutation 전략을 분석할 수 있습니다. v1에서는 구현 복잡도를 줄이기 위해 저장하지 않고, 향후 개선 항목으로 남깁니다.
