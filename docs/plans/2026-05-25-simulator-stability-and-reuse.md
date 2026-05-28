# Simulator 안정성 개선과 Browser 재사용

작성일: 2026-05-25

## 배경

`user-interaction-simulator`는 Rust fuzzing engine이 보낸 browser testcase를 JSON-lines IPC로 받아 실제 브라우저에서 실행하는 Python runtime이다.

이번 작업은 큰 throughput 최적화에 들어가기 전에 simulator 안정성을 먼저 보강하고, browser process 재사용을 실험 가능한 형태로 추가하는 데 초점을 맞췄다.

이 문서는 simulator 쪽에서 완료한 변경과 아직 남아 있는 검증 리스크를 기록한다. Rust 쪽 `SimulatorClient`의 IPC read timeout 개선은 이번 범위에서 제외했다.

## 완료한 변경

### `safe_url()` 예외 처리 수정

`safe_url()`이 Playwright 예외를 제대로 import하고 처리하도록 수정했다.

이전에는 page 또는 browser가 이미 닫힌 상태에서 URL 조회가 실패하면, 원래 원인 대신 `NameError`가 발생할 수 있었다. 이제 URL 조회 실패는 빈 문자열 `""`로 정리되고, 원래 testcase 분류 흐름을 방해하지 않는다.

검증:

```bash
python3 -m py_compile src/user-interaction-simulator/user_interaction_simulator/executor.py
UV_CACHE_DIR=target/uv-cache uv run --directory src/user-interaction-simulator python -m unittest user_interaction_simulator.tests.test_executor
```

### Action timeout/crash 예외 전파

`execute_action()`이 timeout 또는 browser crash로 볼 수 있는 Playwright 예외를 일반 action 실패로 바꾸지 않도록 수정했다.

timeout-like 또는 crash-like 예외는 다시 raise되어 `run_testcase()`의 testcase status 분류까지 전달된다. 그 결과 해당 testcase는 `timeout` 또는 `crash`로 분류될 수 있다.

일반적인 action 실패는 기존처럼 `(False, 0)`을 반환한다. 즉 selector miss, visible 상태 문제 등은 기존 action-result 흐름을 유지한다.

### Iteration deadline 적용

`iteration_timeout_ms`를 simulator 내부의 testcase 전체 deadline으로 적용했다.

deadline이 적용되는 위치는 다음과 같다.

- action 시작 전 deadline 확인
- Playwright action timeout 상한
- `sleep` action
- `inter_action_delay_ms`
- `post_actions_settle_ms`

이 변경으로 sleep이 많은 입력이나 긴 action sequence가 설정된 iteration budget을 초과하는 상황을 줄인다.

### 선택적 browser process 재사용

browser process 재사용 모드를 opt-in 기능으로 추가했다.

사용 방법 (`.env` 또는 inline env):

```bash
# .env
SIMULATOR_REUSE_BROWSER=true

# 또는 inline
SIMULATOR_REUSE_BROWSER=1 cargo run --release
```

설정값은 Rust `AppConfig` → `SimulatorConfig` → IPC `initialize` 메시지의 `reuse_browser` 키로 Python simulator에 전달된다. Rust 쪽 forwarding 세부 변경은 `docs/plans/2026-05-27-simulator-reuse-env-rust-handoff.md`에 기록되어 있다.

기본 동작은 바꾸지 않았다. 기본값에서는 기존처럼 testcase마다 browser process를 새로 띄우고 닫는다.

`SIMULATOR_REUSE_BROWSER=1`을 설정하면 simulator worker 하나가 browser process 하나를 유지하고, testcase마다 새 browser context를 만들어 실행한다. crash-like 예외가 발생하면 persistent browser를 폐기하고 다음 testcase에서 새 browser process를 띄운다.

## Browser 재사용을 기본값으로 켜지 않은 이유

SanCov와 ASAN artifact는 browser process 종료 시점에 flush될 수 있다. browser process를 계속 유지하면 throughput은 좋아질 수 있지만, coverage/crash artifact가 언제 기록되는지 달라질 수 있다.

따라서 browser 재사용은 기본값으로 켜지 않고, 성능 실험용 opt-in 기능으로 둔다. 실제 instrumented browser에서 SanCov/ASAN artifact가 정상적으로 생성되는지 확인한 뒤 기본 정책 변경을 검토해야 한다.

## 비교 실행 방법

기본 실행:

```bash
MAX_ITERATIONS=20 cargo run --release
```

browser 재사용 실행:

```bash
SIMULATOR_REUSE_BROWSER=1 MAX_ITERATIONS=20 cargo run --release
```

비교할 지표:

- `launch_ms`
- iteration throughput
- timeout 비율
- crash 비율
- new coverage event 수
- ASAN report 생성 여부
- crash artifact 완전성

## 현재 제한사항

- browser 재사용 모드는 아직 instrumented browser의 SanCov/ASAN artifact flush 동작과 함께 검증되지 않았다.

## 수행한 검증

Python 문법 확인과 simulator 단위 테스트:

```bash
python3 -m py_compile \
  src/user-interaction-simulator/user_interaction_simulator/main.py \
  src/user-interaction-simulator/user_interaction_simulator/browser_env.py \
  src/user-interaction-simulator/user_interaction_simulator/executor.py \
  src/user-interaction-simulator/user_interaction_simulator/tests/test_browser_env.py

UV_CACHE_DIR=target/uv-cache uv run --directory src/user-interaction-simulator \
  python -m unittest discover -s user_interaction_simulator/tests

UV_CACHE_DIR=target/uv-cache uv run --directory src/user-interaction-simulator \
  python -m user_interaction_simulator --help
```

이번 문서 작성 시점에는 실제 instrumented browser를 사용한 end-to-end fuzzing run은 수행하지 않았다.
