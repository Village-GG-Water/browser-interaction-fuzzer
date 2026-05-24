from abc import ABC, abstractmethod
from typing import Any, Dict, Optional

class BaseBackend(ABC):
    @abstractmethod
    def refresh_context(self) -> bool:
        """애플리케이션 노드 또는 루트 컨텍스트를 갱신합니다."""
        pass

    @abstractmethod
    def find_element(self, role: str, name: str, timeout: float) -> Optional[Any]:
        """역할과 이름을 기반으로 UI 요소를 검색합니다."""
        pass

    @abstractmethod
    def get_element_state(self, element: Any) -> Dict[str, bool]:
        """요소의 가시성, 활성화 상태 등을 반환합니다."""
        pass

    @abstractmethod
    def click(self, element: Any) -> bool:
        """요소를 클릭합니다."""
        pass

    @abstractmethod
    def focus(self, element: Any) -> bool:
        """요소에 포커스를 줍니다."""
        pass

    @abstractmethod
    def type_text(self, element: Any, text: str) -> bool:
        """텍스트를 입력합니다."""
        pass

    @abstractmethod
    def drag_drop(self, src_element: Any, dst_element: Any) -> bool:
        """드래그 앤 드롭을 수행합니다."""
        pass

class NullBackend(BaseBackend):
    """지원이 안 되는 플랫폼을 위한 기본 백엔드"""
    def refresh_context(self) -> bool: return False
    def find_element(self, role, name, timeout) -> Optional[Any]: return None
    def get_element_state(self, element) -> Dict[str, bool]: return {"visible": False}
    def click(self, element) -> bool: return False
    def focus(self, element) -> bool: return False
    def type_text(self, element, text) -> bool: return False
    def drag_drop(self, src, dst) -> bool: return False
