"""FBTI（Finance MBTI）：8 题二选一 → 四维代码 → 8 种高频人格归档。"""

from __future__ import annotations

from typing import Any

# 8 种答辩用归档：代码、名称、五行标签、简述
_ARCHETYPES: list[dict[str, Any]] = [
    {"code": "RLDC", "name": "守财金牛", "wuxing": "金", "tags": ["稳健", "长线", "数据", "集中"], "blurb": "偏好稳健蓝筹与固收+"},
    {"code": "SLTA", "name": "赛道猎手", "wuxing": "木", "tags": ["激进", "长线", "直觉", "分散"], "blurb": "成长赛道、新能源等主题"},
    {"code": "RTFC", "name": "波段王者", "wuxing": "火", "tags": ["激进", "短线", "直觉", "集中"], "blurb": "高弹性、热点轮动"},
    {"code": "LFDA", "name": "价值信徒", "wuxing": "土", "tags": ["稳健", "长线", "数据", "分散"], "blurb": "宽基指数、核心资产"},
    {"code": "RSLC", "name": "平衡大师", "wuxing": "水", "tags": ["稳健", "短线", "数据", "集中"], "blurb": "混合均衡、全天候思路"},
    {"code": "STFA", "name": "情绪交易员", "wuxing": "火木", "tags": ["激进", "短线", "直觉", "分散"], "blurb": "科技小盘、题材博弈"},
    {"code": "RLDA", "name": "养老配置", "wuxing": "金土", "tags": ["稳健", "长线", "数据", "分散"], "blurb": "低波动、分红与价值"},
    {"code": "SLDC", "name": "成长龙头", "wuxing": "木水", "tags": ["激进", "长线", "数据", "集中"], "blurb": "行业龙头、核心成长"},
]


def score_fbti_code(answers: list[str]) -> str:
    """
    answers: 长度 8，每项 'A' 或 'B'，顺序对应题目 1–8。
    维度顺序：R/S → L/T → D/F → C/A，输出四位代码如 RLDC。
    """
    if len(answers) != 8:
        raise ValueError("需要恰好 8 道题答案")
    a = [x.strip().upper() for x in answers]
    for x in a:
        if x not in ("A", "B"):
            raise ValueError("每题仅能为 A 或 B")

    def pick_rs() -> str:
        r = sum(1 for i in (0, 4) if a[i] == "A")
        s = sum(1 for i in (0, 4) if a[i] == "B")
        return "R" if r >= s else "S"

    def pick_lt() -> str:
        l_ = sum(1 for i in (1, 5) if a[i] == "A")
        t_ = sum(1 for i in (1, 5) if a[i] == "B")
        return "L" if l_ >= t_ else "T"

    def pick_df() -> str:
        d_ = sum(1 for i in (2, 6) if a[i] == "A")
        f_ = sum(1 for i in (2, 6) if a[i] == "B")
        return "D" if d_ >= f_ else "F"

    def pick_ca() -> str:
        c_ = sum(1 for i in (3, 7) if a[i] == "A")
        a_ = sum(1 for i in (3, 7) if a[i] == "B")
        return "C" if c_ >= a_ else "A"

    return pick_rs() + pick_lt() + pick_df() + pick_ca()


def match_archetype(code: str) -> dict[str, Any]:
    """精确匹配优先，否则按汉明距离取最近归档。"""
    code = code.upper().strip()
    for row in _ARCHETYPES:
        if row["code"] == code:
            out = dict(row)
            out["matched_code"] = code
            out["nearest_archetype"] = False
            return out
    best = min(_ARCHETYPES, key=lambda r: sum(1 for i in range(4) if r["code"][i] != code[i]))
    out = dict(best)
    out["matched_code"] = code
    out["nearest_archetype"] = True
    return out


def list_archetypes() -> list[dict[str, Any]]:
    return [dict(x) for x in _ARCHETYPES]
