# src/user-interaction-simulator 디렉토리에서 실행 권장
import sys
import os
sys.path.append(os.path.join(os.getcwd(), "src/user-interaction-simulator"))
from user_interaction_simulator.browser_ui import BrowserUIBackend

backend = BrowserUIBackend()
print("새로고침(Reload) 버튼 클릭 시도...")
# 실제 브라우저가 떠있어야 함 (없으면 False 반환 예정)
res = backend.execute("click", "push button", "Reload", timeout=2)
print(f"결과: {res}")
