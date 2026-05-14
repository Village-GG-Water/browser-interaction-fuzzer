"""
생성 파라미터 설정.

Freedom의 TreeConfig/JSConfig/CSSConfig 를 하나로 통합한다.
"""

from __future__ import annotations
from dataclasses import dataclass


@dataclass
class TreeConfig:
    max_elements: int = 80
    min_elements: int = 40
    max_depth: int = 3
    max_attributes: int = 10
    # SVG 엘리먼트를 포함할 확률 (0.0 ~ 1.0)
    svg_prob: float = 0.2


@dataclass
class CSSConfig:
    max_rules: int = 50
    min_rules: int = 10
    max_selectors_per_rule: int = 3
    max_declarations_per_rule: int = 20
    max_keyframes: int = 5
    max_keyframe_stops: int = 4
    # CSS 변수 개수
    num_css_variables: int = 4


@dataclass
class JSConfig:
    # 이벤트 핸들러 개수 (f0 ~ f{n-1})
    num_handlers: int = 5
    # 핸들러당 최소 API 호출 수
    min_api_calls_per_handler: int = 5
    # 핸들러당 최대 API 호출 수
    max_api_calls_per_handler: int = 30
    # 로컬 변수 바인딩 최대 개수 (핸들러당)
    max_local_vars: int = 5


@dataclass
class GeneratorConfig:
    tree: TreeConfig = None
    css: CSSConfig = None
    js: JSConfig = None
    # 재현 가능한 생성을 위한 시드 (None 이면 무작위)
    seed: int | None = None

    def __post_init__(self):
        if self.tree is None:
            self.tree = TreeConfig()
        if self.css is None:
            self.css = CSSConfig()
        if self.js is None:
            self.js = JSConfig()


# 기본 설정
DEFAULT_CONFIG = GeneratorConfig()
