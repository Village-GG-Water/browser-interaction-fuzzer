# browser-interaction-fuzzer

`browser-interaction-fuzzer`는 브라우저 취약점을 찾기 위한 새로운 fuzzing 프로젝트입니다.

```text
Rust fuzzing engine (LibAFL)
  -> dom-generator에 DOM 문서 생성/변이 요청
  -> user-interaction-simulator에 문서와 action sequence 실행 요청
  -> SanCov/ASAN 결과를 LibAFL feedback과 crash objective에 연결
```

## 구성

```text
src/fuzzing_engine/              Rust/LibAFL fuzzing engine
src/dom-generator/               Python DOM/HTML/CSS/JS generator
src/user-interaction-simulator/  Python browser interaction runner
docs/development-guide.md        협업용 개발 문서
corpus/seeds/                    seed 단위 testcase 저장소
crashes/                         crash 재현 artifact 저장소
```

## 환경 설정

이 프로젝트는 `.env`로 실행 환경을 관리합니다.

```env
BROWSER_PATH=D:\programs\chromium\src\out\asan_cov\chrome.exe
BROWSER_KIND=chromium
```

필요한 값은 `.env.example`에 정리되어 있습니다.

## Seed 구조

seed 하나는 HTML 파일 하나가 아니라 “브라우저 테스트케이스 하나”입니다. 그래서 DOM 문서가 있는 seed와 browser UI만 조작하는 seed를 같은 구조에 넣을 수 있습니다.

```text
corpus/seeds/seed_000001/
  testcase.json
  document.fdir
  actions.json
  metadata.json
  snapshot.html
```

- `testcase.json`: 실행 명세입니다. DOM seed인지 UI-only seed인지 구분합니다.
- `document.fdir`: dom-generator의 Python `Document` pickle입니다. Rust는 내용을 해석하지 않습니다.
- `actions.json`: DOM action과 browser UI action을 같은 모델로 저장합니다.
- `metadata.json`: seed 관리용 설명 정보입니다.
- `snapshot.html`: 사람이 확인하기 위한 HTML 산출물입니다.

## Fuzzing Engine

Rust engine은 LibAFL 기반입니다.

- `FuzzInput`: LibAFL `Input`입니다. seed 디렉토리의 testcase/actions/document 경로를 한 번 실행할 입력으로 들고 있습니다.
- `LibAflMutationAdapter`: LibAFL `Mutator`입니다. mutation policy는 Rust가 선택하고, DOM op 적용은 dom-generator에 위임합니다.
- `PlainExecutor`: simulator 실행 함수를 LibAFL `Executor`로 감쌉니다.
- `TestcaseRunner`: simulator 실행 결과에서 ASAN/SanCov artifact, timing, crash 정보를 수집합니다.
- `MaxMapFeedback`: SanCov PC를 Rust coverage map에 반영해서 새로운 coverage를 판단합니다.
- `CrashFeedback`: simulator timeout/crash와 ASAN 결과를 crash objective로 연결합니다.

## 자주 쓰는 명령

Rust 확인:

```powershell
cargo check
cargo test
cargo check --release
```

Python workspace 준비:

```powershell
uv sync
```

dom-generator smoke check:

```powershell
$env:UV_CACHE_DIR='target\uv-cache'
uv run --directory src\dom-generator python main.py generate -n 1 --stdout
```

simulator CLI 확인:

```powershell
$env:UV_CACHE_DIR='target\uv-cache'
uv run --directory src\user-interaction-simulator python -m user_interaction_simulator --help
```

## 주의

`.fdir`은 Python pickle이므로 dom-generator IR 구조가 크게 바뀌면 이전 seed를 다시 열 수 없을 수 있습니다. v1에서는 구현 복잡도를 줄이기 위해 그대로 사용하되, 장기적으로는 replay 가능한 manifest 또는 JSON IR 포맷을 검토합니다.
