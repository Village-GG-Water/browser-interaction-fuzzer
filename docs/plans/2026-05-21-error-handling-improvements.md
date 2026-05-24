# 시뮬레이터 예외 처리(Error Handling) 개선

**작성일**: 2026-05-21
**대상 모듈**: `user-interaction-simulator` (Python 백엔드)

## 1. 개선 배경

기존 시뮬레이터 코드(`dom_utils.py`, `executor.py`, `atspi_backend.py`)에서는 `try-except Exception` 블록을 광범위하게 사용하여, 발생하는 모든 예외를 조용히 무시(`pass` 또는 `return False`)하는 안티 패턴(Anti-pattern)이 존재했습니다.

### 문제점
1. **치명적인 버그 은닉**: 파이썬 코드 내의 오타(Typo), 잘못된 메서드 호출(`AttributeError`), 타입 오류(`TypeError`) 등 개발자가 반드시 인지하고 수정해야 할 코드 레벨의 결함까지 무시되어 버립니다.
2. **디버깅의 어려움**: 브라우저 연결이 끊긴 것인지, 단순히 DOM 요소를 찾지 못한 것인지, 타임아웃이 발생한 것인지 그 원인을 알 수 없어 문제 해결이 어렵습니다. 퍼저(Fuzzer)의 특성상 테스트가 실패한 원인을 명확히 파악하는 것은 매우 중요합니다.

---

## 2. 구체적인 수정 사항

이러한 문제점을 해결하기 위해 **예외 타입을 최대한 좁히고(Narrow down), 디버깅 로그를 남기는 방식**으로 리팩토링을 진행했습니다.

### 2.1. `dom_utils.py` (DOM 탐색 예외 처리 개선)

*   **이전**: `page.query_selector` 등에서 발생하는 모든 예외를 `except Exception:`으로 무시했습니다.
*   **개선**: Playwright의 전용 예외 클래스인 `PlaywrightError`를 import하여 사용합니다. 요소 탐색 실패 시 `PlaywrightError`만 명확히 잡아서 `logging.debug`로 남겼습니다. 만약 코드 문법 에러가 발생한다면 `PlaywrightError`가 아니므로 상위로 예외가 전파(Propagate)되어 즉각적으로 버그를 발견할 수 있습니다.

### 2.2. `executor.py` (타임아웃과 예상치 못한 런타임 오류의 분리)

*   **이전**: `execute_action` 함수의 전체 흐름을 감싸는 `except Exception:`이 있었으며, 에러 발생 시 무조건 `False, 0`을 반환했습니다.
*   **개선**:
    *   `PlaywrightTimeoutError`: 퍼징 시뮬레이션 중 흔하게 발생할 수 있는 정상적인 현상이므로 조용히 실패(`False, 0`) 처리합니다.
    *   `PlaywrightError`: 브라우저 내부 에러나 연결 끊김 등을 추적하기 위해 `logging.debug`를 남기고 실패 처리합니다.
    *   `Exception`: 그 외 예상치 못한 파이썬 런타임 에러(버그 등)는 **`logging.error`로 스택 트레이스(`exc_info=True`)와 함께 강력하게 경고**하도록 변경했습니다.
    *   `page.wait_for_function`, `page.evaluate`, `page.url` 접근(safe_url) 부분도 동일하게 `PlaywrightError`만 구체적으로 잡도록 수정했습니다.

### 2.3. `atspi_backend.py` (AT-SPI 순회 예외 처리 개선)

*   **이전**: 자식 노드 순회 중 발생하는 모든 에러를 `except Exception: continue`로 넘겼습니다.
*   **개선**: 
    *   노드가 타이밍 이슈로 순회 도중 사라져 발생하는 `IndexError`는 무시하고 계속 진행(`continue`)하도록 처리했습니다.
    *   기타 AT-SPI 라이브러리 내부나 통신 문제로 발생한 `Exception`은 원인 파악을 위해 `logging.debug`를 통해 로그로 남기고 계속 진행하도록 수정했습니다.

---

## 3. 기대 효과

*   **안정성 향상**: 코드 수정 중 발생할 수 있는 오타나 논리적 오류가 더 이상 숨겨지지 않으므로 시뮬레이터 자체의 안정성이 크게 올라갑니다.
*   **퍼징 결과 신뢰성**: 타임아웃(정상)과 브라우저 통신 장애(비정상)를 명확히 구분할 수 있게 되어, 퍼저가 반환하는 크래시 및 에러 상태의 신뢰도가 상승합니다.
*   **신속한 원인 파악**: 디버그 모드로 시뮬레이터를 실행할 때 남겨지는 로그를 통해 왜 특정 액션이 실패했는지 즉각적으로 확인할 수 있습니다.
