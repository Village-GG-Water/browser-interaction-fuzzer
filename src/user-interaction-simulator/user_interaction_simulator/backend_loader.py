import sys
import logging
from .base import BaseBackend, NullBackend

def load_backend(backend_name: str = None) -> BaseBackend:
    if backend_name:
        # 명시적으로 이름이 주어졌을 때
        if backend_name == "linux":
            return _load_linux_atspi()
        elif backend_name == "null":
            return NullBackend()

    # 자동 감지
    platform = sys.platform
    if platform.startswith("linux"):
        return _load_linux_atspi()
    
    logging.warning(f"Unsupported platform: {platform}. Using NullBackend.")
    return NullBackend()

def _load_linux_atspi() -> BaseBackend:
    try:
        from .linux.atspi_backend import AtspiBackend
        return AtspiBackend()
    except (ImportError, Exception) as e:
        logging.error(f"Failed to load Linux AtspiBackend: {e}")
        return NullBackend()
