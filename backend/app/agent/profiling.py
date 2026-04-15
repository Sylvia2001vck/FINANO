"""
Structured user profiling: MBTI + birth features + optional layout + 2026 丙午流年规则表。

输出均为可审计的结构化特征，供 MAFB 各 Agent 共享状态使用；非专业命理结论。
"""

from __future__ import annotations

import hashlib
from datetime import date
from typing import Any

# MBTI -> baseline risk appetite (1 conservative .. 5 aggressive)
_MBTI_RISK: dict[str, int] = {
    "INTJ": 4,
    "INTP": 4,
    "ENTJ": 5,
    "ENTP": 5,
    "INFJ": 3,
    "INFP": 3,
    "ENFJ": 3,
    "ENFP": 4,
    "ISTJ": 2,
    "ISFJ": 2,
    "ESTJ": 3,
    "ESFJ": 2,
    "ISTP": 4,
    "ISFP": 2,
    "ESTP": 5,
    "ESFP": 4,
}

_STEM_ELEMENT = {
    "甲": "木",
    "乙": "木",
    "丙": "火",
    "丁": "火",
    "戊": "土",
    "己": "土",
    "庚": "金",
    "辛": "金",
    "壬": "水",
    "癸": "水",
}

_STEMS = list(_STEM_ELEMENT.keys())


def _year_stem(year: int) -> str:
    offset = (year - 1984) % 10
    return _STEMS[offset]


def _wuxing_vector_from_birth(birth: str) -> dict[str, float]:
    try:
        y, _, _ = birth.split("-")
        year = int(y)
    except ValueError:
        year = 1990
    stem = _year_stem(year)
    element = _STEM_ELEMENT[stem]
    base = {"金": 0.0, "木": 0.0, "水": 0.0, "火": 0.0, "土": 0.0}
    base[element] += 0.45
    h = int(hashlib.sha256(birth.encode("utf-8")).hexdigest(), 16)
    keys = list(base.keys())
    for i, k in enumerate(keys):
        base[k] += 0.11 + ((h >> (i * 3)) & 7) / 500.0
    total = sum(base.values()) or 1.0
    return {k: round(v / total, 4) for k, v in base.items()}


def day_master_demo(birth_iso: str) -> dict[str, Any]:
    """课程演示：由出生日确定性映射到「日主天干」规则特征，非专业排盘。"""
    h = int(hashlib.sha256(birth_iso.encode("utf-8")).hexdigest(), 16)
    stems = ["甲", "乙", "丙", "丁", "戊", "己", "庚", "辛", "壬", "癸"]
    sm = stems[h % 10]
    elem = _STEM_ELEMENT[sm]
    return {
        "day_master_stem_demo": sm,
        "day_master_element": elem,
        "note": "日主由演示规则生成，用于结构化风控特征，非专业八字排盘。",
    }


def wuxing_xiji_demo(wuxing_vector: dict[str, float]) -> dict[str, Any]:
    """喜忌：按五行向量强弱做的极简规则表（教学用）。"""
    ranked = sorted(wuxing_vector.keys(), key=lambda k: wuxing_vector[k], reverse=True)
    return {
        "xi_yong": ranked[-2:],
        "ji_shen": ranked[:2],
        "explain": "演示规则：向量偏弱者为喜用参考，偏强者为忌参考。",
    }


def liunian_2026_bingwu() -> dict[str, Any]:
    """2026 丙午流年：火象偏强场景下的行业倾斜与仓位上限（规则引擎，可写报告）。"""
    return {
        "ganzhi": "丙午",
        "year": 2026,
        "narrative": (
            "2026 丙午流年（规则化建模）：火元素权重上行，系统对科技、高端制造链条给予轻度正向行业倾斜，"
            "并设置单一权益合计上限，强调分散与再平衡。"
        ),
        "sector_bias": {"科技": 0.08, "消费": 0.04, "均衡": 0.02, "固收": -0.03, "宽基": 0.01},
        "max_equity_weight_cap": 0.68,
        "position_note": "建议核心宽基为底仓，卫星仓不超过画像风险等级对应上限；预留现金/短债缓冲。",
    }


def _sector_tilt_from_layout(facing: str | None) -> dict[str, float]:
    """无环境偏好时不注入赛道倾斜（空表）。"""
    if not facing or not str(facing).strip():
        return {}
    facing_u = facing.strip().upper()[:1]
    table = {
        "N": {"科技": 0.15, "消费": 0.1, "宽基": 0.05},
        "S": {"消费": 0.15, "固收": 0.1, "宽基": 0.05},
        "E": {"科技": 0.12, "均衡": 0.12, "宽基": 0.06},
        "W": {"固收": 0.18, "宽基": 0.1, "均衡": 0.04},
    }
    return dict(table.get(facing_u, table["N"]))


def build_user_profile(
    user_birth: str,
    user_mbti: str,
    layout_facing: str | None = None,
    risk_preference: int | None = None,
) -> dict[str, Any]:
    mbti = (user_mbti or "INTJ").upper()
    risk_from_mbti = _MBTI_RISK.get(mbti, 3)
    wuxing = _wuxing_vector_from_birth(user_birth)
    layout_tilt = _sector_tilt_from_layout(layout_facing)
    dominant = max(wuxing, key=wuxing.get)
    element_risk_map = {"火": 1, "木": 2, "土": 3, "金": 4, "水": 5}
    risk_from_element = element_risk_map.get(dominant, 3)
    risk_level = max(1, min(5, round(risk_from_mbti * 0.65 + risk_from_element * 0.35)))

    if risk_preference is not None:
        rp = max(1, min(5, int(risk_preference)))
        risk_level = max(1, min(5, round(0.5 * risk_level + 0.5 * rp)))

    liu26 = liunian_2026_bingwu()
    dm = day_master_demo(user_birth)
    xiji = wuxing_xiji_demo(wuxing)

    return {
        "mbti": mbti,
        "mbti_style": "偏稳健" if risk_from_mbti <= 2 else ("均衡" if risk_from_mbti <= 3 else "偏进取"),
        "birth": user_birth,
        "wuxing_vector": wuxing,
        "dominant_element": dominant,
        "day_master": dm,
        "wuxing_xiji": xiji,
        "layout_sector_tilt": layout_tilt,
        "fengshui_layout_facing": (layout_facing or "").strip().upper()[:1] or None,
        "risk_level": risk_level,
        "liquidity_preference": "高" if mbti in {"ENTP", "ESTP", "ENTJ"} else "中",
        "liunian_2026": liu26,
    }


def liunian_factor(as_of: date | None = None) -> float:
    """流年系数：2026 丙午略抬高权益容忍（有上限，在资产配置节点再截断）。"""
    as_of = as_of or date.today()
    base = 0.92 + (as_of.month % 6) * 0.02
    if as_of.year == 2026:
        base *= 1.02
    return min(base, 1.06)
