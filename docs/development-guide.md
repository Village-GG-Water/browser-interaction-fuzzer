# 개발 가이드

이 문서는 `browser-interaction-fuzzer`의 협업용 개발 문서입니다. 특히 user interaction simulator를 맡는 개발자가 Rust engine과 맞춰 구현해야 하는 경계를 설명합니다.

## 전체 구조

```text
fuzzing_engine (Rust + LibAFL)
  - LibAFL StdFuzzer/QueueScheduler 기반 fuzz loop
  - 초기 seed 생성/로드
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

v1의 기본 fuzzing 실행은 filesystem corpus를 계속 읽고 쓰지 않습니다. 시작 시 dom-generator로 seed를 만들고 LibAFL `InMemoryCorpus`에 올립니다. 고정된 시작 seed가 필요할 때만 `.env`의 `INITIAL_SEED_DIR`로 아래 형식의 디렉토리를 지정합니다.

managed multi-worker 실행에서는 각 worker가 같은 `INITIAL_SEED_DIR`을 읽은 뒤 정렬된 seed 목록을 `index % WORKER_COUNT == WORKER_ID` 규칙으로 나눕니다. worker에 배정된 초기 seed가 `SEED_INPUTS`보다 적으면 기존처럼 부족분을 dom-generator로 생성합니다.

```text
INITIAL_SEED_DIR/
  seed_000001/
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
  "edge_id": "dom.click.event",
  "target": {
    "space": "dom",
    "selector": "#x1",
    "resolution": "live_selector",
    "fallback": true
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

`edge_id`는 optional field입니다. Rust mutation policy가 FSA 기반 interaction sequence를 만들 때 어떤 transition이 선택되었는지 기록하기 위한 trace이며, simulator는 이 값을 실행 조건으로 사용하지 않습니다. 기존 seed처럼 `edge_id`가 없는 action JSON도 유효합니다.

DOM target의 `resolution`과 `fallback`도 optional입니다. 값이 없으면 기존 동작처럼 실행 시점에 selector를 다시 찾고 selector miss 시 fallback 후보를 고릅니다. stale-reuse mutation은 `resolution = "cached_point"`와 `fallback = false`를 사용해 이전 bounding box 중심을 다시 조작하고, target miss를 임의 fallback으로 숨기지 않습니다.

### FSA 기반 interaction 생성

Rust engine은 user-interaction sequence를 finite state automaton 기반으로 생성하고 변이합니다. FSA는 실행 결과를 관측하는 runtime checker가 아니라 generation/mutation-time guide입니다. simulator는 계속 action sequence를 순서대로 실행만 합니다.

공통 state는 `PageReady`, `ElementPrimed`, `PointerOver`, `FocusedElement`, `TextFocused`, `AfterEvent`, `AfterInvalidation`, `AsyncPending`입니다. state는 DOM 전체 상태가 아니라 다음 interaction이 의미 있으려면 필요한 최소 전제를 나타냅니다. 예를 들어 `TextFocused`에서만 `type_text`와 `clear`를 만들고, `FocusedElement` 또는 `TextFocused`에서만 `press_key`를 만듭니다.

공통 state machine은 모든 DOM에 공유되고, `dom-generator`가 반환한 interactable metadata로 edge를 materialize합니다.

- `is_text_input`: `focus -> TextFocused`, `type_text`, `clear`
- `is_focusable`: `focus -> FocusedElement`
- `events`와 `has_handler`: click/hover/focus/input 계열 edge 가중치 증가
- `is_draggable`와 `is_drop_target`: drag/drop pair edge
- `invalidates_self`, `invalidates_dom`, `has_async_boundary`: stale-reuse suffix와 lifecycle hazard boundary feedback

`AfterEvent`는 실제 handler 실행을 보장하는 상태가 아닙니다. metadata상 event handler가 있거나 event-triggering action을 방금 생성했으므로, 짧은 `sleep`, follow-up click/focus, scroll 같은 후속 action을 붙일 수 있다는 generation state입니다.

Lifecycle hazard mutation은 `insert_self_invalidate_handler`, `insert_cross_invalidate_handler`, `wrap_invalidation_async`, `insert_focus_invalidate_handler` 같은 dom-generator op와 `dom.stale_reuse.*` action suffix를 조합합니다. coarse boundary는 `invalidated_to_async`, `async_to_stale_reuse`, `restored_to_stale_reuse`만 corpus/reward 후보로 사용하고, selector별 detail은 metrics와 crash artifact에만 둡니다.

현재 단일 `snapshot.html` 실행 모델에서는 `back`과 `forward`를 공통 DOM FSA에서 생성하지 않습니다. multi-page testcase가 구현되면 navigation 상태는 별도 FSA로 확장합니다.

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
  "source_path": "out/seed_build/seed_generated_000001/document.fdir",
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
  "action_hints": [],
  "stats": {}
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
  "action_trace": [
    {
      "index": 0,
      "kind": "click",
      "target": {"space": "dom", "selector": "#x1"},
      "ok": true,
      "fallback_used": false,
      "elapsed_ms": 12,
      "exists_before": true,
      "exists_after": false,
      "url_before": "file:///...",
      "url_after": "file:///..."
    }
  ],
  "timings": {
    "launch_ms": 100,
    "load_ms": 30,
    "actions_ms": 70,
    "close_ms": 20,
    "simulator_total_ms": 220
  }
}
```

`status` 값은 `ok`, `timeout`, `crash`, `error` 중 하나입니다. simulator `status="timeout"`만으로는 Rust crash objective에 들어가지 않고 timeout telemetry로 집계됩니다. 개별 action의 Playwright wait timeout은 가능한 경우 해당 action의 `ok=false`, `elapsed_ms`, `slow_actions` 신호로 남기고 testcase timeout으로 승격하지 않습니다. ASAN report가 있거나 simulator가 `status="crash"`를 반환한 경우에만 crash objective로 연결됩니다.

Rust `clients/simulator.rs`는 `run_testcase` 요청 전체에 `SIMULATOR_RESPONSE_TIMEOUT_MS` watchdog을 적용합니다. 기본값은 `ITERATION_TIMEOUT_MS + 5000`입니다. 이 watchdog은 `browser.close()`, `new_context()`, `page.evaluate()` 같은 Playwright sync 호출이 반환하지 않아 JSON-lines 응답이 멈추는 infrastructure stall을 복구하기 위한 장치입니다. timeout이 발생하면 해당 worker는 simulator process tree를 종료하고 새 simulator를 initialize한 뒤, 그 iteration을 crash가 아니라 infra error로 기록합니다.

## Rust 모듈 책임

- `actions.rs`: action data model과 JSON wire format.
- `input.rs`: LibAFL `Input`인 `FuzzInput`.
- `seed_store.rs`: 선택적으로 지정된 초기 seed 디렉토리 읽기. fuzzing 중 새 corpus를 파일로 누적하지 않습니다.
- `mutation/`: 모든 mutation 정책.
- `mutation/libafl_mutator.rs`: mutation 정책을 LibAFL `Mutator`로 연결.
- `clients/dom_generator.rs`: dom-generator IPC.
- `clients/simulator.rs`: simulator IPC.
- `testcase_runner.rs`: testcase 실행, coverage/crash artifact 수집.
- `lifecycle.rs`: simulator action trace와 generator metadata로 lifecycle hazard boundary를 계산합니다.
- `libafl_executor.rs`: simulator harness를 LibAFL `Executor`로 감싸는 adapter.
- `metrics.rs`: 수치 수집과 avg/p95 계산.
- `reporting.rs`: 사람이 읽는 실행 상태 출력.

## 병렬 실행 모델

`PARALLEL_WORKERS=1`은 기존 단일 LibAFL 실행입니다. `PARALLEL_WORKERS>1`이면 parent process가 같은 binary를 worker child process로 실행하고, 각 worker는 기존 `StdFuzzer`/`QueueScheduler`/`StdMutationalStage`/`PlainExecutor` 흐름을 그대로 사용합니다. worker 내부의 `fuzz_one`은 동기 실행이지만 여러 worker가 동시에 브라우저 testcase를 실행하므로 전체 throughput이 올라갑니다.

parent는 worker마다 `WORKER_ID`, `WORKER_COUNT`, worker-local `OUT_DIR`, worker-local `CRASH_DIR`를 환경변수로 주입합니다. 따라서 SanCov, ASAN, browser profile, generated mutation artifact, crash artifact는 worker별 디렉토리 아래에 저장됩니다.

v1 병렬화는 raw coverage map을 실시간 공유하지 않습니다. 각 worker는 worker-local runtime corpus, coverage map, lifecycle hazard map을 갖습니다. 공유 단위는 향후 LibAFL event manager/LLMP로 전파할 interesting testcase/event이며, 전역 coverage bitmap이 source of truth가 아닙니다.

managed parallel 실행에서 `MAX_ITERATIONS`는 전체 예산으로 해석하고 parent가 worker별로 `ceil(MAX_ITERATIONS / PARALLEL_WORKERS)`를 내려줍니다. `MAX_ITERATIONS=0`이면 모든 worker가 기존처럼 중지 요청 전까지 실행합니다.

## Crash artifact

fuzzing engine은 시작할 때마다 session id를 하나 부여합니다. crash objective에 걸린 입력은 같은 세션 안에 저장합니다. ASAN report나 simulator crash 없이 timeout만 발생한 입력은 crash artifact로 저장하지 않고 run summary의 timeout count로 남깁니다.

```text
crashes/
  session_1778191810093_12345/
    crash_000001/
      metadata.json
      actions.json
      simulator-response.json
      hazard-summary.json
      snapshot.html
      document.fdir
      asan.txt
```

- `metadata.json`: `session_id`, `iteration`, `seed_id`, simulator `status`, crash type, ASAN source/hash를 저장합니다.
- `actions.json`: crash 당시 실행한 action sequence입니다.
- `simulator-response.json`: simulator가 반환한 원본 실행 결과입니다.
- `hazard-summary.json`: coarse lifecycle boundary와 stale-reuse 후보 수를 저장합니다.
- `snapshot.html`, `document.fdir`: DOM seed일 때만 저장됩니다.
- `asan.txt`: ASAN report가 있을 때만 저장됩니다.

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

### Seed 장기 포맷

`.fdir`은 Python pickle입니다. 구현은 빠르지만 dom-generator IR 변경에 취약합니다. 장기적으로는 replay 가능한 manifest 또는 JSON IR 포맷을 검토합니다.

### Runtime corpus

LibAFL이 말하는 corpus는 실행 중 scheduler와 feedback이 관리하는 runtime corpus입니다. v1은 `InMemoryCorpus<FuzzInput>`를 사용합니다. 파일 seed 디렉토리는 협업, 수동 재현, 시작 seed 주입을 위한 포맷이고, fuzzing 중 자동으로 증가하는 저장소로 쓰지 않습니다.

### Mutation history

mutation history를 저장하면 coverage/crash에 기여한 mutation 전략을 분석할 수 있습니다. v1에서는 구현 복잡도를 줄이기 위해 저장하지 않고, 향후 개선 항목으로 남깁니다.
