# AT-SPI 브라우저 UI 통합 구현 계획 (v2)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `user-interaction-simulator`에 AT-SPI 기반의 브라우저 UI 상호작용 기능을 통합하여, 퍼저가 DOM 외부 요소(주소창, 버튼 등)를 조작할 수 있게 합니다.

**Architecture:** `BrowserUIBackend` 모듈을 신설하여 AT-SPI 통신을 전담하게 하고, 기존 `main.py`의 `execute_action`에서 `target.space == "browser_ui"`인 경우 이를 호출하도록 통합합니다.

**Tech Stack:** Python, `gi.repository.Atspi` (PyGObject), Playwright (기존)

---

### Task 1: BrowserUIBackend 기초 구현 및 역할 매핑

**Files:**
- Create: `src/user-interaction-simulator/user_interaction_simulator/browser_ui.py`

- [ ] **Step 1: BrowserUIBackend 클래스 및 Atspi 초기화 로직 작성**

```python
import logging
import time

try:
    import gi
    gi.require_version('Atspi', '2.0')
    from gi.repository import Atspi
    HAS_ATSPI = True
except (ImportError, ValueError):
    HAS_ATSPI = False

class BrowserUIBackend:
    def __init__(self):
        self.desktop = None
        if HAS_ATSPI:
            try:
                # Registry 대신 Atspi 직접 사용 (현대적 방식)
                self.desktop = Atspi.get_desktop(0)
            except Exception as e:
                logging.error(f"AT-SPI 초기화 실패: {e}")

    def _get_role(self, role_name):
        if not HAS_ATSPI: return None
        mapping = {
            "push button": Atspi.Role.PUSH_BUTTON,
            "entry": Atspi.Role.ENTRY,
            "page tab": Atspi.Role.PAGE_TAB,
            "frame": Atspi.Role.FRAME,
            "image map": Atspi.Role.IMAGE_MAP,
        }
        return mapping.get(role_name.lower())

    def execute(self, kind, role_name, element_name, timeout=5):
        if not HAS_ATSPI or not self.desktop:
            return False, "AT-SPI not available"
        return False, "Not implemented yet"
```

- [ ] **Step 2: 파일 저장 및 커밋**

```bash
git add src/user-interaction-simulator/user_interaction_simulator/browser_ui.py
git commit -m "feat: add BrowserUIBackend skeleton with modern Atspi"
```

---

### Task 2: 요소 탐색 및 액션 실행 로직 구현

**Files:**
- Modify: `src/user-interaction-simulator/user_interaction_simulator/browser_ui.py`

- [ ] **Step 1: 탐색 및 클릭/포커스 실행 메서드 추가**

```python
    def _refresh_app(self):
        for i in range(self.desktop.get_child_count()):
            try:
                app = self.desktop.get_child_at_index(i)
                if app and app.get_name() in ["Google Chrome", "Chromium"]:
                    return app
            except Exception:
                continue
        return None

    def _find_node_dfs(self, node, role, name):
        if not node: return None
        try:
            # GObject Introspection 방식의 메서드 호출
            if node.get_role() == role and (not name or node.get_name() == name):
                return node
            
            # DOM 영역 제외 (성능 최적화)
            if node.get_role() in [Atspi.Role.DOCUMENT_WEB, Atspi.Role.DOCUMENT_FRAME]:
                return None

            for i in range(node.get_child_count()):
                found = self._find_node_dfs(node.get_child_at_index(i), role, name)
                if found: return found
        except Exception:
            pass
        return None

    def execute(self, kind, role_name, element_name, timeout=5):
        if not HAS_ATSPI or not self.desktop:
            return False
        
        role = self._get_role(role_name)
        if role is None: return False

        start_time = time.time()
        while time.time() - start_time < timeout:
            app = self._refresh_app()
            if app:
                for i in range(app.get_child_count()):
                    window = app.get_child_at_index(i)
                    element = self._find_node_dfs(window, role, element_name)
                    if element:
                        return self._perform_action(element, kind)
            time.sleep(0.5)
        return False

    def _perform_action(self, element, kind):
        try:
            if kind == "click":
                action = element.get_action_iface()
                if action and action.get_n_actions() > 0:
                    return action.do_action(0)
            elif kind == "focus":
                component = element.get_component_iface()
                if component:
                    return component.grab_focus()
        except Exception:
            pass
        return False
```

- [ ] **Step 2: 커밋**

```bash
git add src/user-interaction-simulator/user_interaction_simulator/browser_ui.py
git commit -m "feat: implement Atspi node traversal and action execution"
```

---

### Task 3: 시뮬레이터 main.py 통합

**Files:**
- Modify: `src/user-interaction-simulator/user_interaction_simulator/main.py`

- [ ] **Step 1: BrowserUIBackend 통합**

```python
# 상단 임포트 추가
from .browser_ui import BrowserUIBackend

# 전역 또는 적절한 위치에 초기화 (기존 코드 흐름에 맞춤)
ui_backend = BrowserUIBackend()

# execute_action 함수 수정
def execute_action(page, action, timeout_ms, target_cache):
    kind = action.get("kind")
    target = action.get("target")

    # 브라우저 UI 액션 처리 분기 추가
    if target and target.get("space") == "browser_ui":
        role = target.get("role")
        name = target.get("name")
        ok = ui_backend.execute(kind, role, name, timeout=timeout_ms / 1000)
        return ok, 0
    
    # ... 기존 DOM 액션 처리 로직 ...
```

- [ ] **Step 2: 커밋**

```bash
git add src/user-interaction-simulator/user_interaction_simulator/main.py
git commit -m "feat: integrate BrowserUIBackend into simulator main loop"
```

---

### Task 4: 동작 검증

- [ ] **Step 1: 검증 스크립트 작성 및 실행 (`test_ui_interaction.py`)**

```python
# src/user-interaction-simulator 디렉토리에서 실행 권장
import sys
import os
sys.path.append(os.getcwd())
from user_interaction_simulator.browser_ui import BrowserUIBackend

backend = BrowserUIBackend()
print("새로고침(Reload) 버튼 클릭 시도...")
# 실제 브라우저가 떠있어야 함
res = backend.execute("click", "push button", "Reload")
print(f"결과: {res}")
```

- [ ] **Step 2: 결과 확인 및 필요 시 보정**
