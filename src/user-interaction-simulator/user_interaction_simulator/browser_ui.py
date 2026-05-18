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
        if not HAS_ATSPI or role_name is None: return None
        mapping = {
            "push button": Atspi.Role.PUSH_BUTTON,
            "entry": Atspi.Role.ENTRY,
            "page tab": Atspi.Role.PAGE_TAB,
            "frame": Atspi.Role.FRAME,
            "image map": Atspi.Role.IMAGE_MAP,
        }
        return mapping.get(role_name.lower())

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
