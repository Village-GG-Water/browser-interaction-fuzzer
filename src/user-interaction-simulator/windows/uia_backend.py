import logging
import time
from typing import Any, Dict, Optional
from ..base import BaseBackend

try:
    import uiautomation as auto
    HAS_UIA = True
except (ImportError, Exception):
    HAS_UIA = False


_CHROME_CLASS_NAMES = {"Chrome_WidgetWin_1"}
_CHROME_PROCESS_NAMES = {"chrome.exe", "chromium.exe"}


class UiaBackend(BaseBackend):
    def __init__(self):
        self.root = None
        if HAS_UIA:
            try:
                self.root = auto.GetRootControl()
            except Exception as e:
                logging.error(f"UIA initialization failed: {e}")

    def refresh_context(self) -> bool:
        return self._get_browser_window() is not None

    def find_element(self, role_name: str, element_name: str, timeout: float) -> Optional[Any]:
        if not HAS_UIA or not self.root:
            return None
        control_type = self._get_uia_control_type(role_name)
        if control_type is None:
            return None

        start_time = time.time()
        while time.time() - start_time < timeout:
            window = self._get_browser_window()
            if window:
                found = self._dfs(window, control_type, element_name)
                if found:
                    return found
            time.sleep(0.5)
        return None

    def get_element_state(self, element: Any) -> Dict[str, bool]:
        try:
            return {
                "visible": not bool(element.IsOffscreen),
                "enabled": bool(element.IsEnabled),
                "focusable": bool(element.IsKeyboardFocusable),
            }
        except Exception as e:
            logging.debug(f"UIA get_element_state failed: {e}")
            return {"visible": False}

    def click(self, element: Any) -> bool:
        try:
            pattern = element.GetInvokePattern()
            if pattern:
                pattern.Invoke()
                return True
        except Exception as e:
            logging.debug(f"UIA InvokePattern failed: {e}")
        try:
            element.Click(simulateMove=False)
            return True
        except Exception as e:
            logging.debug(f"UIA click failed: {e}")
            return False

    def focus(self, element: Any) -> bool:
        try:
            element.SetFocus()
            return True
        except Exception as e:
            logging.debug(f"UIA focus failed: {e}")
            return False

    def type_text(self, element: Any, text: str) -> bool:
        return False

    def drag_drop(self, src_element: Any, dst_element: Any) -> bool:
        return False

    def _get_uia_control_type(self, role_name: str):
        if not HAS_UIA:
            return None
        mapping = {
            "push button": auto.ControlType.ButtonControl,
            "entry": auto.ControlType.EditControl,
            "page tab": auto.ControlType.TabItemControl,
            "frame": auto.ControlType.WindowControl,
            "image map": auto.ControlType.ImageControl,
        }
        return mapping.get(role_name.lower())

    def _get_browser_window(self):
        if not self.root:
            return None
        try:
            for child in self.root.GetChildren():
                if self._is_chrome_window(child):
                    return child
        except Exception as e:
            logging.debug(f"UIA error in _get_browser_window: {e}")
        return None

    def _is_chrome_window(self, node) -> bool:
        try:
            if node.ClassName not in _CHROME_CLASS_NAMES:
                return False
            process_name = self._process_name_for(node)
            return process_name in _CHROME_PROCESS_NAMES
        except Exception as e:
            logging.debug(f"UIA error in _is_chrome_window: {e}")
            return False

    def _process_name_for(self, node) -> str:
        try:
            import psutil  # optional; uiautomation lists it as a dependency
            pid = node.ProcessId
            if pid:
                return psutil.Process(pid).name().lower()
        except Exception:
            pass
        try:
            import ctypes
            from ctypes import wintypes
            pid = wintypes.DWORD(node.ProcessId)
            PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
            handle = ctypes.windll.kernel32.OpenProcess(
                PROCESS_QUERY_LIMITED_INFORMATION, False, pid
            )
            if not handle:
                return ""
            try:
                buf = ctypes.create_unicode_buffer(260)
                size = wintypes.DWORD(len(buf))
                if ctypes.windll.kernel32.QueryFullProcessImageNameW(
                    handle, 0, buf, ctypes.byref(size)
                ):
                    return buf.value.rsplit("\\", 1)[-1].lower()
            finally:
                ctypes.windll.kernel32.CloseHandle(handle)
        except Exception as e:
            logging.debug(f"UIA process name lookup failed: {e}")
        return ""

    def _dfs(self, node, control_type, name):
        try:
            if node.ControlType == control_type and (not name or node.Name == name):
                return node
            if node.ControlType == auto.ControlType.DocumentControl:
                return None
            for child in node.GetChildren():
                found = self._dfs(child, control_type, name)
                if found:
                    return found
        except Exception as e:
            logging.debug(f"UIA error in _dfs: {e}")
        return None
