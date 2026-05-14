# AGENTS.md

이 저장소에서 AI agent가 작업할 때 지켜야 할 규칙입니다.

## 프로젝트 목표

`browser-interaction-fuzzer`는 LibAFL 기반 Rust fuzzing engine, Python dom-generator, Python user-interaction-simulator를 분리해 협업하기 쉬운 브라우저 fuzzing 구조를 만드는 프로젝트입니다.

가장 중요한 설계 원칙은 다음입니다.

- fuzzing 정책은 Rust가 소유합니다.
- DOM IR 생성/변이 연산은 Python dom-generator가 수행합니다.
- 브라우저 실행과 사용자 상호작용은 Python user-interaction-simulator가 수행합니다.
- seed는 HTML 파일이 아니라 브라우저 testcase입니다.

## 주요 디렉토리

- `src/fuzzing_engine/`: Rust/LibAFL engine입니다. corpus, mutation strategy, coverage feedback, crash objective, metrics, reporting을 담당합니다.
- `src/dom-generator/`: Python DOM generator입니다. 기존 코드를 가능한 한 보존합니다.
- `src/user-interaction-simulator/`: Python simulator입니다. v1은 Playwright DOM backend를 구현하고, browser UI backend는 확장 지점으로 둡니다.
- `docs/development-guide.md`: protocol, seed format, 확장 계획을 설명하는 협업 문서입니다.

## Rust 작업 규칙

- `src/main.rs`는 얇게 유지합니다. 실행 흐름은 `AppConfig::load()`, `FuzzingApp::new()`, `app.run()` 수준만 보이게 둡니다.
- fuzz loop는 LibAFL `StdFuzzer`, `QueueScheduler`, `StdMutationalStage`, `Feedback`, `Objective` 경계 위에 유지합니다.
- raw JSON protocol은 client module 안에 가둡니다.
- action model은 `actions.rs`, testcase model은 `input.rs`, mutation 정책은 `mutation/`에 둡니다.
- simulator 실행은 `libafl_executor.rs`의 LibAFL `Executor` adapter를 통해 연결합니다. `testcase_runner.rs`는 한 testcase 실행 결과에서 ASAN/SanCov/timing을 수집하는 runner입니다. custom while-loop fuzzer로 되돌리지 마세요.
- 새 mutation 전략은 `mutation/strategy.rs`와 `mutation/scheduler.rs`를 통해 추가합니다.
- timing, action success, fallback, slow action 같은 병목 분석 값은 `metrics.rs`에 수집하고 `reporting.rs`에서 출력합니다.
- crash artifact는 반드시 `crashes/session_<session_id>/crash_<iteration>/` 아래에 저장합니다. 서로 다른 fuzzing 실행의 crash를 같은 디렉토리에 섞지 마세요.

## Python 작업 규칙

- Python 실행은 uv workspace를 기준으로 합니다.
- dom-generator는 Rust가 선택한 mutation op를 적용하는 실행자입니다. seed 선택이나 mutation 정책을 Python 쪽으로 옮기지 않습니다.
- simulator stdout은 JSON-lines protocol 전용입니다. 로그는 stderr로만 출력합니다.
- browser UI 조작은 `target.space = "browser_ui"` action을 통해 확장합니다.

## 환경 변수

- `BROWSER_PATH`가 필수입니다.

## 검증

Rust 변경 후:

```powershell
cargo check
cargo test
cargo check --release
```

Python 변경 후:

```powershell
python -m py_compile src\dom-generator\main.py src\user-interaction-simulator\user_interaction_simulator\main.py
```

uv 실행이 필요하면 기본 cache 대신 다음 형태를 우선 사용합니다.

```powershell
$env:UV_CACHE_DIR='target\uv-cache'
uv ...
```

## 하지 말 것

- `.fdir` 내부를 Rust에서 해석하지 마세요.
- simulator protocol을 바꿀 때 Rust/Python 한쪽만 수정하지 마세요.
- coverage나 timing 출력을 단순 로그로 취급해 제거하지 마세요. 병목 분석용 지표입니다.
