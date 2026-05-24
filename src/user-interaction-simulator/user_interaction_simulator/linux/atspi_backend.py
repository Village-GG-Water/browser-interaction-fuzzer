import logging
import time
from typing import Any, Dict, Optional
from ..base import BaseBackend

try:
    import gi
    gi.require_version('Atspi', '2.0')
    from gi.repository import Atspi
    HAS_ATSPI = True
except (ImportError, ValueError):
    HAS_ATSPI = False

class AtspiBackend(BaseBackend):
    def __init__(self):
        self.desktop = None
        if HAS_ATSPI:
            try:
                self.desktop = Atspi.get_desktop(0)
            except Exception as e:
                logging.error(f"AT-SPI initialization failed: {e}")

    def refresh_context(self) -> bool:
        if not self.desktop: return False
        for i in range(self.desktop.get_child_count()):
            try:
                app = self.desktop.get_child_at_index(i)
                if app and app.get_name() in ["Google Chrome", "Chromium"]:
                    return True
            except IndexError:
                continue
            except Exception as e:
                logging.debug(f"AT-SPI error in refresh_context reading child {i}: {e}")
                continue
        return False

    def find_element(self, role_name: str, element_name: str, timeout: float) -> Optional[Any]:
        if not HAS_ATSPI or not self.desktop: return None
        role = self._get_atspi_role(role_name)
        if role is None: return None

        start_time = time.time()
        while time.time() - start_time < timeout:
            app = self._get_browser_app()
            if app:
                for i in range(app.get_child_count()):
                    window = app.get_child_at_index(i)
                    found = self._dfs(window, role, element_name)
                    if found: return found
            time.sleep(0.5)
        return None

    def get_element_state(self, element: Any) -> Dict[str, bool]:
        try:
            state_set = element.get_state_set()
            return {
                "visible": state_set.contains(Atspi.StateType.VISIBLE),
                "enabled": state_set.contains(Atspi.StateType.ENABLED),
                "focusable": state_set.contains(Atspi.StateType.FOCUSABLE),
            }
        except Exception as e:
            logging.debug(f"AT-SPI get_element_state failed: {e}")
            return {"visible": False}

    def click(self, element: Any) -> bool:
        try:
            action = element.get_action_iface()
            return action.do_action(0) if action and action.get_n_actions() > 0 else False
        except Exception as e:
            logging.debug(f"AT-SPI click failed: {e}")
            return False

    def focus(self, element: Any) -> bool:
        try:
            component = element.get_component_iface()
            return component.grab_focus() if component else False
        except Exception as e:
            logging.debug(f"AT-SPI focus failed: {e}")
            return False

    def type_text(self, element: Any, text: str) -> bool:
        # AT-SPI level typing is complex; keeping it False for now as per design
        return False

    def drag_drop(self, src_element: Any, dst_element: Any) -> bool:
        return False

    def _get_atspi_role(self, role_name: str):
        mapping = {
            "push button": Atspi.Role.PUSH_BUTTON,
            "entry": Atspi.Role.ENTRY,
            "page tab": Atspi.Role.PAGE_TAB,
            "frame": Atspi.Role.FRAME,
            "image map": Atspi.Role.IMAGE_MAP,
        }
        return mapping.get(role_name.lower())

    def _get_browser_app(self):
        if not self.desktop: return None
        for i in range(self.desktop.get_child_count()):
            try:
                app = self.desktop.get_child_at_index(i)
                if app and app.get_name() in ["Google Chrome", "Chromium"]:
                    return app
            except IndexError:
                continue
            except Exception as e:
                logging.debug(f"AT-SPI error in _get_browser_app reading child {i}: {e}")
                continue
        return None

    def _dfs(self, node, role, name):
        try:
            if node.get_role() == role and (not name or node.get_name() == name):
                return node
            if node.get_role() in [Atspi.Role.DOCUMENT_WEB, Atspi.Role.DOCUMENT_FRAME]:
                return None
            for i in range(node.get_child_count()):
                found = self._dfs(node.get_child_at_index(i), role, name)
                if found: return found
        except Exception as e:
            logging.debug(f"AT-SPI error in _dfs: {e}")
        return None
