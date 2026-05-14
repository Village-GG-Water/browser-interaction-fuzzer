# AGENTS.md

이 저장소에서 AI agent가 작업할 때 지켜야 할 프로젝트 규칙입니다. 이 문서는 agent catalog가 아니라, 실제 코드 변경 시 따라야 할 아키텍처 경계와 검증 기준입니다.

## 프로젝트 개요

`browser-interaction-fuzzer`는 브라우저 취약점 탐색을 위한 fuzzing 프로젝트입니다. 핵심 구조는 Rust LibAFL fuzzing engine, Python `dom-generator`, Python `user-interaction-simulator`의 세 부분으로 나뉩니다.

현재 설계 원칙은 다음입니다.

- Rust는 fuzzing 정책을 소유합니다.
- Python `dom-generator`는 DOM IR 생성, DOM/CSS/JS 변이 적용, HTML render를 소유합니다.
- Python `user-interaction-simulator`는 브라우저 실행과 사용자 상호작용 실행을 소유합니다.
- seed는 단순 HTML 파일이 아니라 재현 가능한 브라우저 testcase입니다.
- LibAFL runtime corpus와 filesystem seed/testcase artifact를 혼동하지 않습니다.

## 저장소 구조

- `src/main.rs`: Rust entry point입니다. 실행 흐름은 얇게 유지합니다.
- `src/fuzzing_engine/`: Rust/LibAFL engine입니다. corpus, scheduling, feedback, objective, mutation policy, coverage, crash classification, metrics, reporting을 담당합니다.
- `src/dom-generator/`: Python DOM/HTML/CSS/JS generator입니다. `.fdir` load/save, DOM mutation op 적용, HTML render, interactable metadata 추출을 담당합니다.
- `src/user-interaction-simulator/`: Python browser interaction runner입니다. v1은 Playwright DOM backend를 구현하고, browser UI backend는 확장 지점으로 둡니다.
- `docs/development-guide.md`: protocol, seed format, module responsibility, future extension을 설명하는 협업 문서입니다.
- `examples/`: 수동 smoke test나 simulator 예제용 자료입니다.
- `corpus/`, `out/`, `crashes/`, `target/`: runtime/generated artifact 영역입니다. 소스처럼 편집하지 않습니다.

## 자주 쓰는 명령

아래 명령은 저장소 루트에서 실행합니다.

Rust 검증:

```powershell
cargo check
cargo test
cargo check --release
```

Python workspace 준비:

```powershell
$env:UV_CACHE_DIR='target\uv-cache'
uv sync
```

DOM generator smoke check:

```powershell
$env:UV_CACHE_DIR='target\uv-cache'
uv run --directory src\dom-generator python main.py generate -n 1 --stdout
```

Simulator CLI 확인:

```powershell
$env:UV_CACHE_DIR='target\uv-cache'
uv run --directory src\user-interaction-simulator python -m user_interaction_simulator --help
```

Python 문법 확인용 fallback:

```powershell
python -m py_compile src\dom-generator\main.py src\user-interaction-simulator\user_interaction_simulator\main.py
```

프로젝트 Python 명령은 `UV_CACHE_DIR=target\uv-cache`를 지정한 `uv` 실행을 우선합니다. 네트워크가 필요한 dependency 설치는 먼저 사용자에게 확인합니다.

## 작업 모드

- Engine 작업: `src/fuzzing_engine/`를 수정합니다. LibAFL `StdFuzzer`, `QueueScheduler`, `StdMutationalStage`, feedback, objective, corpus, executor 경계를 유지합니다.
- Generator 작업: `src/dom-generator/`를 수정합니다. seed 선택과 mutation policy를 Python으로 옮기지 말고, 좁은 JSON protocol이나 CLI로 동작을 노출합니다.
- Simulator 작업: `src/user-interaction-simulator/`를 수정합니다. stdout은 JSON-lines protocol 응답 전용으로 유지하고, 로그는 stderr로 보냅니다.
- Integration 작업: testcase, action, generator, simulator protocol shape을 바꿀 때는 Rust와 Python을 함께 수정합니다.
- Documentation 작업: README, `docs/development-guide.md`, 이 파일이 실제 runtime split과 맞도록 유지합니다.

docs-agent, test-agent, api-agent 같은 역할별 agent catalog를 만들지 않습니다. 이 저장소에는 agent 목록이 아니라 프로젝트 규칙과 작업 모드가 필요합니다.

## 현재 구현 상태

현재 구현 형태는 다음과 같습니다.

- Rust engine은 LibAFL runtime corpus를 사용하며, 현재는 `InMemoryCorpus<FuzzInput>`입니다.
- `FuzzInput`은 raw HTML string이 아니라 browser testcase를 표현합니다.
- `LibAflMutationAdapter`는 Rust mutation policy를 LibAFL `Mutator`에 연결합니다.
- `PlainExecutor`는 testcase 실행을 LibAFL `Executor`에 맞게 감쌉니다.
- `TestcaseRunner`는 simulator 결과, ASAN/SanCov artifact, timing, crash 정보를 수집합니다.
- `MaxMapFeedback`은 Rust coverage map을 사용해 new coverage를 판단합니다.
- `CrashFeedback`은 simulator crash/timeout/ASAN 결과를 crash objective에 연결합니다.
- Browser UI action은 action model에는 포함되어 있지만, v1 browser UI 실행은 아직 확장 지점입니다.

오래된 주석, 예제, 문서가 다른 runtime model을 설명한다면 구현을 바꾸기 전에 현재 코드를 먼저 확인합니다.

## 중요 파일

- `src/fuzzing_engine/app.rs`: top-level LibAFL app wiring, seed 생성/로드, feedback/objective/executor 설정.
- `src/fuzzing_engine/config.rs`: `.env` 로딩과 runtime configuration.
- `src/fuzzing_engine/actions.rs`: action data model과 JSON wire format.
- `src/fuzzing_engine/input.rs`: LibAFL input/testcase 표현.
- `src/fuzzing_engine/seed_store.rs`: optional initial seed directory 로딩.
- `src/fuzzing_engine/mutation/`: mutation policy, scheduler, strategy, DOM/action mutation op, LibAFL mutator adapter.
- `src/fuzzing_engine/clients/dom_generator.rs`: `dom-generator` JSON-lines IPC의 Rust side.
- `src/fuzzing_engine/clients/simulator.rs`: simulator JSON-lines IPC의 Rust side.
- `src/fuzzing_engine/testcase_runner.rs`: testcase 실행, output 수집, crash artifact 생성.
- `src/fuzzing_engine/libafl_executor.rs`: LibAFL executor adapter.
- `src/fuzzing_engine/coverage.rs`: SanCov/coverage map 처리.
- `src/fuzzing_engine/crash.rs`: crash classification과 metadata.
- `src/fuzzing_engine/metrics.rs`: timing/action/fallback/throughput metrics.
- `src/fuzzing_engine/reporting.rs`: 사람이 읽는 run status 출력.
- `src/dom-generator/main.py`: generator CLI와 JSON-lines server.
- `src/user-interaction-simulator/user_interaction_simulator/main.py`: simulator CLI와 JSON-lines server.

## Rust/Python 경계

Rust가 소유하는 영역:

- fuzzing state와 scheduling
- corpus 관리
- mutation strategy 선택
- action sequence 생성과 변이
- coverage feedback과 crash objective 판단
- metrics와 reporting

`dom-generator`가 소유하는 영역:

- DOM IR 구성
- `.fdir` load/save
- DOM/CSS/JS mutation op 실행
- HTML render
- interactable metadata와 action hint 추출

`user-interaction-simulator`가 소유하는 영역:

- browser launch와 teardown
- page load 또는 initial URL 설정
- DOM action 실행
- 향후 browser UI action 실행
- action별 result, timing, crash, timeout, ASAN signal 보고

Rust side의 raw JSON protocol 세부사항은 `src/fuzzing_engine/clients/` 안에 가둡니다. protocol construction을 engine 전체로 퍼뜨리지 않습니다.

## 프로토콜 규칙

JSON-lines stdout은 기계가 읽는 protocol입니다. 로그는 반드시 stderr로 보냅니다.

`BrowserAction`, testcase JSON, generator request, simulator request를 바꿀 때는 다음을 함께 수정합니다.

- Rust type과 serialization 갱신
- Rust mutation/generation code 갱신
- 영향이 있다면 Rust artifact 저장 로직 갱신
- Python handler 구현 갱신
- wire format이 바뀌면 `docs/development-guide.md` 갱신
- 필요한 focused verification 추가 또는 조정

IPC boundary의 한쪽만 수정하지 않습니다.

## Seed와 Corpus 규칙

seed directory 하나는 재현 가능한 browser testcase 하나입니다.

수동/초기 seed 구조는 `README.md`와 `docs/development-guide.md`에 문서화되어 있습니다.

```text
seed_000001/
  testcase.json
  document.fdir
  actions.json
  metadata.json
  snapshot.html
```

규칙:

- `document.fdir`은 `dom-generator`가 소유하는 Python pickle입니다. Rust에서 직접 parse하지 않습니다.
- `snapshot.html`은 사람이 확인하고 simulator가 로드하기 위한 산출물이며, DOM mutation의 source of truth가 아닙니다.
- UI-only seed에는 DOM document가 없을 수 있습니다.
- LibAFL runtime corpus와 자동으로 증가하는 filesystem seed corpus는 같은 개념이 아닙니다.
- 새 seed format을 만들 때는 docs와 구현 양쪽을 함께 갱신합니다.

## Action과 Interaction 규칙

Action은 실제 browser-visible behavior를 겨냥해야 합니다.

- DOM action은 `target.space = "dom"`을 사용하며, generated content에 실제로 존재하는 selector/metadata를 우선해야 합니다.
- Browser UI action은 `target.space = "browser_ui"`를 사용하며, 실제 backend가 연결되기 전까지 protocol-level extension point입니다.
- 생성된 DOM에 없는 target을 자주 고르는 purely random selector는 피합니다.
- action success, fallback, slow action, timing metric을 보존합니다. 이 값들은 cosmetic log가 아니라 fuzzing signal과 bottleneck evidence입니다.
- action kind를 추가할 때는 generation, mutation, simulator execution, serialization, crash artifact, docs를 함께 갱신합니다.

## Simulator와 Crash 규칙

simulator는 설정된 browser를 실행하고 testcase를 한 번에 하나씩 실행합니다. 현재 코드는 Chromium/Playwright 중심일 수 있지만, 새 설계에서는 browser/backend 가정을 명확히 드러냅니다.

Crash artifact는 재현 가능해야 합니다. crash objective에 걸린 입력은 아래 위치에 저장합니다.

```text
crashes/session_<session_id>/crash_<iteration>/
```

유용한 crash artifact에는 metadata, actions, simulator response, snapshot HTML, 존재하는 경우 `.fdir` document, 존재하는 경우 ASAN report가 포함됩니다. 사용자가 명시적으로 요청하고 대체 구조가 재현성을 보존하는 경우가 아니라면 이 artifact를 삭제하거나 단순화하지 않습니다.

## 실행 환경

이 프로젝트는 주로 Windows에서 개발됩니다.

필수 `.env`:

```env
BROWSER_PATH=C:\path\to\instrumented\browser.exe
```

자주 쓰는 optional 값:

```env
BROWSER_KIND=chromium
OUT_DIR=out
CRASH_DIR=crashes
INITIAL_SEED_DIR=...
ITERATION_TIMEOUT_MS=12000
MAX_ITERATIONS=...
```

명시적으로 요청받지 않았다면 `.env`를 편집하지 않습니다. 예시가 필요하면 `.env.example`을 수정합니다.

이 저장소에서는 `CHROME_PATH`를 선호 설정 이름으로 쓰지 않습니다. `BROWSER_PATH`와 `BROWSER_KIND`를 사용합니다.

## 항상 할 것

- 편집 전 `git status --short`를 확인합니다.
- 변경 범위를 요청된 작업에 맞게 제한합니다.
- 오래된 문서나 TODO 문구를 믿기 전에 현재 코드를 확인합니다.
- runtime split을 보존합니다. engine은 Rust, DOM generation은 `src/dom-generator/`, browser execution은 `src/user-interaction-simulator/`가 담당합니다.
- `src/main.rs`를 얇게 유지합니다.
- raw protocol code는 client/server boundary module 안에 유지합니다.
- coverage, crash, timing, action-result signal을 보존합니다.
- 실제 browser run을 수행했는지 명확히 밝히고, 수행했다면 browser/backend 이름을 적습니다.

## 먼저 확인할 것

- dependency 설치나 네트워크가 필요한 package command를 실행하기 전.
- Python package manager를 바꾸거나 `uv` workflow를 대체하기 전.
- `.env`나 machine-specific path를 편집하기 전.
- top-level module을 rename하거나 큰 architecture piece를 이동하기 전.
- corpus, crash, ASAN, SanCov, profile, generated runtime artifact를 삭제하기 전.
- `.fdir`을 새 장기 seed format으로 대체하기 전.
- LibAFL 구조를 custom while-loop fuzzer로 대체하기 전.

## 하지 말 것

- 관련 없는 사용자 변경을 되돌리지 않습니다.
- 명시적으로 요청받지 않았다면 `git reset --hard`, `git checkout --` 같은 destructive git command를 실행하지 않습니다.
- Rust에서 `.fdir`을 직접 parse하지 않습니다.
- seed 선택이나 fuzzing policy를 Python generator/simulator code로 옮기지 않습니다.
- JSON-lines server mode에서 simulator나 generator stdout에 로그를 쓰지 않습니다.
- `corpus/`, `out/`, `crashes/`, `target/`, ASAN/SanCov output, browser profile을 일반 source file처럼 취급하지 않습니다.
- 유효한 browser 설정으로 실제 실행하지 않았다면 end-to-end fuzzing이 통과했다고 말하지 않습니다.

## Fuzzing 우선순위

구현 방향을 고를 때는 다음을 우선합니다.

1. 유의미한 coverage growth.
2. realistic browser interaction.
3. Action-DOM correlation.
4. event handler/action interaction.
5. crash reproducibility와 classification quality.
6. corpus와 mutation quality.
7. throughput.

interaction, coverage, crash discovery를 개선하지 않으면서 generated HTML 크기만 키우는 변경은 피합니다.

## 검증 기준

Rust-only 변경 후:

```powershell
cargo check
```

mutation, executor, feedback, objective, config 변경 후에는 다음도 고려합니다.

```powershell
cargo test
cargo check --release
```

generator 변경 후:

```powershell
$env:UV_CACHE_DIR='target\uv-cache'
uv run --directory src\dom-generator python main.py generate -n 1 --stdout
```

simulator 변경 후:

```powershell
$env:UV_CACHE_DIR='target\uv-cache'
uv run --directory src\user-interaction-simulator python -m user_interaction_simulator --help
```

protocol 또는 end-to-end 변경 후에는 Rust/Python boundary를 검증하고, 실제 instrumented-browser fuzzing run을 수행했는지 명확히 보고합니다.
