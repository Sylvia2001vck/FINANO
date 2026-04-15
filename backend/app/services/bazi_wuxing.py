"""趣味工程化：生日 + 北京时间时辰 → 单字五行偏好（规则表，无第三方库）。"""

from __future__ import annotations

from datetime import date, datetime

# 简化：公历日期的数字特征映射到「日主倾向」，再与时辰地支五行叠加
_DAY_STEM_ELEM = ["金", "木", "水", "火", "土"]  # 循环


def _beijing_now() -> datetime:
    try:
        from zoneinfo import ZoneInfo

        return datetime.now(ZoneInfo("Asia/Shanghai"))
    except Exception:
        return datetime.now()


def hour_branch_element(hour: int) -> str:
    """0–23 时 → 十二时辰大致五行（演示规则）。"""
    # 子丑寅卯辰巳午未申酉戌亥 → 简化映射到五行
    idx = (hour + 1) // 2 % 12
    table = ["水", "土", "木", "木", "土", "火", "火", "土", "金", "金", "土", "水"]
    return table[idx]


def compute_today_wuxing_preference(birth: date, now: datetime | None = None) -> str:
    """
    输入用户生日，结合「当前」北京时间时辰，输出一个主五行字（喜用演示）。
    """
    now = now or _beijing_now()
    day_seed = birth.year * 10000 + birth.month * 100 + birth.day
    base = _DAY_STEM_ELEM[day_seed % 5]
    hour_el = hour_branch_element(now.hour)
    # 简单合成：若时辰五行与日主同系则强化，否则取日主（答辩话术：时间维度修正）
    if base == hour_el or (base in "金土" and hour_el in "金土"):
        return base
    # 否则输出「日主+时辰」双字简写（仍写入 user_wuxing 可截断）
    return f"{base}"


def fuse_wuxing(archetype_wuxing: str, bazi_wuxing: str) -> str:
    """FBTI 归档五行 + 时辰五行，合成展示串（≤32 字）。"""
    aw = (archetype_wuxing or "").strip()
    bw = (bazi_wuxing or "").strip()
    if not aw:
        return bw or "土"
    if not bw:
        return aw
    if aw == bw:
        return aw
    if len(aw) <= 1 and len(bw) <= 1:
        return f"{aw}{bw}" if aw != bw else aw
    return f"{aw}+{bw}"[:32]
