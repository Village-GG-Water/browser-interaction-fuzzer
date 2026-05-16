# Browser UI Traversal and Action Execution Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement UI element discovery and action execution using AT-SPI for browser automation.

**Architecture:** Add traversal and execution methods to `BrowserUIBackend`. Use DFS to find nodes by role and name while skipping DOM areas. Implement click and focus actions.

**Tech Stack:** Python, AT-SPI (via GObject Introspection).

---

### Task 1: Implement Browser Discovery and Node Traversal

**Files:**
- Modify: `src/user-interaction-simulator/user_interaction_simulator/browser_ui.py`

- [ ] **Step 1: Add `_refresh_app` and `_find_node_dfs` methods**

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
```

- [ ] **Step 2: Update `execute` and add `_perform_action`**

```python
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

- [ ] **Step 3: Verify syntax**

Run: `python3 -m py_compile src/user-interaction-simulator/user_interaction_simulator/browser_ui.py`
Expected: No errors.

- [ ] **Step 4: Commit**

```bash
git add src/user-interaction-simulator/user_interaction_simulator/browser_ui.py
git commit -m "feat: implement Atspi node traversal and action execution"
```
