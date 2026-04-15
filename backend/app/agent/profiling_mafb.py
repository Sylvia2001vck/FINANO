"""MAFB 专用画像：可选纳入 FBTI + 用户风险偏好；不含八字五行流年等演示字段。"""

from __future__ import annotations

from typing import Any

from app.services.fbti_engine import match_archetype

_FBTI_RISK_NUM: dict[str, int] = {
    "低风险": 2,
    "中低风险": 2,
    "中风险": 3,
    "中高风险": 4,
    "高风险": 5,
}


def _risk_numeric_from_fbti_label(label: str) -> int:
    s = (label or "").strip()
    return _FBTI_RISK_NUM.get(s, 3)


def build_user_profile_mafb(
    include_fbti: bool,
    fbti_code: str | None,
    risk_preference: int | None,
) -> dict[str, Any]:
    """
    include_fbti=False：不纳入 FBTI，risk_level 仅来自账户风险偏好（无则默认 3）。
    include_fbti=True：使用已保存 FBTI 码（无则按引擎默认归档）与风险偏好融合 risk_level。
    """
    if not include_fbti:
        rp = 3 if risk_preference is None else max(1, min(5, int(risk_preference)))
        return {
            "profile_mode": "no_fbti",
            "mbti": "",
            "fbti_code": "",
            "fbti_name": "",
            "fbti_archetype": None,
            "risk_level": rp,
            "liquidity_preference": "中",
            "fund_preference_summary": "未纳入 FBTI：无人格-赛道偏好摘要，仅风险档位参与后续规则演示。",
            "style_tags": [],
            "layout_sector_tilt": {},
        }

    arch = match_archetype((fbti_code or "").strip() or "RLDC")
    risk_from_fbti = _risk_numeric_from_fbti_label(str(arch.get("risk_level") or "中风险"))

    if risk_preference is not None:
        rp = max(1, min(5, int(risk_preference)))
        risk_level = max(1, min(5, int(round(0.55 * risk_from_fbti + 0.45 * rp))))
    else:
        risk_level = risk_from_fbti

    tags = list(arch.get("tags") or arch.get("style_tags") or [])
    liq = "高" if any(x in tags for x in ("激进", "短线")) else ("中" if "均衡" in tags else "中")

    return {
        "profile_mode": "fbti_only",
        "mbti": "",
        "fbti_code": str(arch.get("matched_code") or arch.get("code") or ""),
        "fbti_name": str(arch.get("name") or ""),
        "fbti_archetype": arch,
        "risk_level": risk_level,
        "liquidity_preference": liq,
        "fund_preference_summary": str(arch.get("fund_preference") or ""),
        "style_tags": tags,
        "layout_sector_tilt": {},
    }
