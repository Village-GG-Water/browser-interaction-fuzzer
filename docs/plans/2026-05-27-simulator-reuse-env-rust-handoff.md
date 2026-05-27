# Rust-side handoff: forward `SIMULATOR_REUSE_BROWSER` through IPC

## 배경

Python simulator는 더 이상 `os.environ["SIMULATOR_REUSE_BROWSER"]`를 직접 읽지 않는다 (`src/user-interaction-simulator/browser_env.py`). 대신 `initialize` IPC 메시지의 `reuse_browser` 키를 사용한다.

다른 simulator 설정과 동일한 경로 (`.env` → Rust `AppConfig` → `SimulatorConfig` → JSON IPC → Python config dict) 를 완성하기 위해 Rust 쪽 변경이 필요하다. 이 변경이 머지되기 전까지는 `.env`나 inline env 의 `SIMULATOR_REUSE_BROWSER`가 무시되고 Python은 항상 `reuse_browser=false` 로 동작한다.

## 필요한 Rust 변경

### 1. `src/fuzzing_engine/config.rs`

(a) `AppConfig` 구조체 (현재 line 9-36) 에 필드 추가:

```rust
pub disable_breakpad: bool,
pub reuse_browser: bool,           // 추가
pub asan_symbolizer_path: Option<String>,
```

(b) `AppConfig::load()` (현재 line 68-104) 의 struct 리터럴에서 파싱:

```rust
disable_breakpad: bool_var(&vars, "DISABLE_BREAKPAD", true),
reuse_browser: bool_var(&vars, "SIMULATOR_REUSE_BROWSER", false),   // 추가
asan_symbolizer_path: optional_var(&vars, "ASAN_SYMBOLIZER_PATH"),
```

기존 `bool_var` 헬퍼 (config.rs:246-256) 가 `1/true/yes/on` 등을 이미 처리하므로 새 파서 불필요.

(c) `overlay_environment` whitelist (현재 line 158-189) 에 키 추가:

```rust
"DISABLE_BREAKPAD",
"SIMULATOR_REUSE_BROWSER",   // 추가
"ASAN_SYMBOLIZER_PATH",
```

이로써 `$env:SIMULATOR_REUSE_BROWSER=1; cargo run …` 같은 inline 사용도 `.env` 값을 override 하면서 계속 작동한다.

### 2. `src/fuzzing_engine/clients/simulator.rs`

(a) `SimulatorConfig` (현재 line 14-29) 에 필드 추가:

```rust
pub disable_breakpad: bool,
pub reuse_browser: bool,           // 추가
pub asan_symbolizer_path: Option<String>,
```

(b) `SimulatorConfig::from_app_config` (현재 line 31-50) 에서 복사:

```rust
disable_breakpad: config.disable_breakpad,
reuse_browser: config.reuse_browser,   // 추가
asan_symbolizer_path: config.asan_symbolizer_path.clone(),
```

(c) `initialize` JSON 메시지 (현재 line 166-184) 에 키 추가:

```rust
"inter_action_delay_ms": config.inter_action_delay_ms,
"reuse_browser": config.reuse_browser,   // 추가
```

## `.env.example`

이미 갱신되어 있음 (`SIMULATOR_REUSE_BROWSER=false`).

## 검증

1. `cargo build` — 새 필드가 컴파일 통과하는지.
2. `.env`에 `SIMULATOR_REUSE_BROWSER=true` 추가 후 `cargo run --release` — 여러 iteration 동안 chromium PID가 유지되는지 작업관리자로 확인.
3. `.env`에서 제거 후 `$env:SIMULATOR_REUSE_BROWSER='1'; cargo run --release` — `overlay_environment` whitelist 가 inline override 를 적용하는지 확인.
4. `.env`/inline 둘 다 없을 때 — 매 iteration 마다 새 chromium 프로세스가 뜨는 기본 동작 유지.

## Python 쪽 참고 (이미 적용됨)

- `src/user-interaction-simulator/browser_env.py`: `BrowserSession.__init__` 이 `bool(config.get("reuse_browser"))` 로 변경됨. `bool_env` 헬퍼는 삭제됨.
- `src/user-interaction-simulator/tests/test_browser_env.py`: `os.environ` patching 대신 config dict 로 reuse 모드를 전달하도록 갱신됨.
