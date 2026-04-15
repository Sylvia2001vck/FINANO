"""FBTI（Finance MBTI）：8 题二选一 → 四维代码 → 16 种金融人格归档。"""

from __future__ import annotations

from typing import Any

from app.services.fbti_calculator import FBTI_PROFILES, calculate_fbti


def score_fbti_code(answers: list[str]) -> str:
    """兼容旧名：等价于 fbti_calculator.calculate_fbti。"""
    return calculate_fbti(answers)


def _shape_archetype_row(*, canonical_code: str, matched_code: str, nearest: bool) -> dict[str, Any]:
    raw = FBTI_PROFILES[canonical_code]
    return {
        "code": canonical_code,
        "matched_code": matched_code,
        "nearest_archetype": nearest,
        "name": raw["name"],
        "wuxing": raw["wuxing"],
        "tags": list(raw["style_tags"]),
        "style_tags": list(raw["style_tags"]),
        "blurb": raw["description"],
        "description": raw["description"],
        "risk_level": raw["risk_level"],
        "fund_preference": raw["fund_preference"],
    }


def match_archetype(code: str) -> dict[str, Any]:
    """精确匹配 16 型之一；否则按汉明距离取最近归档（演示容错）。"""
    code = code.upper().strip()
    if len(code) != 4:
        code = "RLDC"
    if code in FBTI_PROFILES:
        return _shape_archetype_row(canonical_code=code, matched_code=code, nearest=False)
    codes = list(FBTI_PROFILES.keys())
    best = min(codes, key=lambda c: (sum(1 for i in range(4) if c[i] != code[i]), c))
    return _shape_archetype_row(canonical_code=best, matched_code=code, nearest=True)


def list_archetypes() -> list[dict[str, Any]]:
    """16 型列表（按代码排序），供管理端或答辩展示。"""
    return [_shape_archetype_row(canonical_code=c, matched_code=c, nearest=False) for c in sorted(FBTI_PROFILES)]
