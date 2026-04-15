"""FBTI 16 型人格字典与四维编码计算（与 MAFB 解耦，供路由与 AI 选股读取）。"""

from __future__ import annotations

from typing import Any

# 四维：R/S 稳健·激进 → L/T 长线·短线 → D/F 数据·直觉 → C/A 集中·分散
_FBTI_PROFILES_RAW: dict[str, dict[str, Any]] = {
    "RLDC": {
        "name": "持重者",
        "risk_level": "低风险",
        "description": "数据驱动重仓核心，长期稳健持有",
        "style_tags": ["稳健", "长线", "数据", "集中"],
        "fund_preference": "价值蓝筹、宽基指数",
    },
    "RLDA": {
        "name": "均衡者",
        "risk_level": "中低风险",
        "description": "分散均衡配置，佛系躺平不焦虑",
        "style_tags": ["稳健", "长线", "数据", "分散"],
        "fund_preference": "固收+、混合均衡",
    },
    "RLFC": {
        "name": "笃行者",
        "risk_level": "中低风险",
        "description": "直觉信仰驱动，坚定长期持有",
        "style_tags": ["稳健", "长线", "直觉", "集中"],
        "fund_preference": "明星经理、长期赛道",
    },
    "RLFA": {
        "name": "温润者",
        "risk_level": "中低风险",
        "description": "温和广撒布局，情绪稳定慢养收益",
        "style_tags": ["稳健", "长线", "直觉", "分散"],
        "fund_preference": "全天候、均衡混合",
    },
    "RTDC": {
        "name": "波段者",
        "risk_level": "中风险",
        "description": "数据择时做波段，落袋为安",
        "style_tags": ["稳健", "短线", "数据", "集中"],
        "fund_preference": "ETF、指数增强",
    },
    "RTDA": {
        "name": "套利者",
        "risk_level": "中风险",
        "description": "网格分散交易，稳健套利复利",
        "style_tags": ["稳健", "短线", "数据", "分散"],
        "fund_preference": "短债、套利策略",
    },
    "RTFC": {
        "name": "敏锐者",
        "risk_level": "中风险",
        "description": "盘感敏锐博弈，轻仓短线操作",
        "style_tags": ["稳健", "短线", "直觉", "集中"],
        "fund_preference": "行业主题、轮动",
    },
    "RTFA": {
        "name": "浅尝者",
        "risk_level": "中风险",
        "description": "多只小额试水，享受理财过程",
        "style_tags": ["稳健", "短线", "直觉", "分散"],
        "fund_preference": "新基、轻仓体验",
    },
    "SLDC": {
        "name": "掌舵者",
        "risk_level": "中高风险",
        "description": "数据精选赛道，重仓成长龙头",
        "style_tags": ["激进", "长线", "数据", "集中"],
        "fund_preference": "成长龙头、新能源/AI",
    },
    "SLDA": {
        "name": "拓界者",
        "risk_level": "中高风险",
        "description": "多线成长布局，稳中带攻",
        "style_tags": ["激进", "长线", "数据", "分散"],
        "fund_preference": "多赛道成长组合",
    },
    "SLFC": {
        "name": "孤勇者",
        "risk_level": "高风险",
        "description": "信仰重仓赛道，坚定 all in",
        "style_tags": ["激进", "长线", "直觉", "集中"],
        "fund_preference": "单一赛道、主题重仓",
    },
    "SLFA": {
        "name": "探路者",
        "risk_level": "高风险",
        "description": "广押新兴风口，探索超额收益",
        "style_tags": ["激进", "长线", "直觉", "分散"],
        "fund_preference": "创新主题、新兴产业",
    },
    "STDC": {
        "name": "破局者",
        "risk_level": "高风险",
        "description": "数据驱动打板，短线快进快出",
        "style_tags": ["激进", "短线", "数据", "集中"],
        "fund_preference": "热门题材、短线龙头",
    },
    "STDA": {
        "name": "疾行者",
        "risk_level": "高风险",
        "description": "量化高频交易，纪律性冲锋",
        "style_tags": ["激进", "短线", "数据", "分散"],
        "fund_preference": "量化策略、高频",
    },
    "STFC": {
        "name": "逐风者",
        "risk_level": "高风险",
        "description": "追随市场情绪，狙击热点龙头",
        "style_tags": ["激进", "短线", "直觉", "集中"],
        "fund_preference": "情绪龙头、热点",
    },
    "STFA": {
        "name": "游牧者",
        "risk_level": "高风险",
        "description": "游牧式轮动，高频切换热点",
        "style_tags": ["激进", "短线", "直觉", "分散"],
        "fund_preference": "题材轮动、短线博弈",
    },
}


def _wuxing_for_code(code: str) -> str:
    """与八字融合用的演示五行标签（RL/RT/SL/ST 四象）。"""
    prefix = (code or "RL")[:2].upper()
    return {"RL": "金土", "RT": "水", "SL": "木", "ST": "火"}.get(prefix, "土")


FBTI_PROFILES: dict[str, dict[str, Any]] = {
    k: {**v, "wuxing": _wuxing_for_code(k)} for k, v in _FBTI_PROFILES_RAW.items()
}


def calculate_fbti(answers: list[str]) -> str:
    """
    8 题二选一 → 四维代码（R/S, L/T, D/F, C/A），共 16 型之一。
    answers: 长度 8，每项 'A' 或 'B'，顺序对应题目 1–8。
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


def get_fbti_profile(code: str) -> dict[str, Any] | None:
    """按四位码返回完整画像字典（含 wuxing）；未知码返回 None。"""
    key = (code or "").strip().upper()
    if len(key) != 4:
        return None
    row = FBTI_PROFILES.get(key)
    if not row:
        return None
    return {"code": key, **row}
