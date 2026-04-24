"""趣味工程化：生日 + 北京时间时辰 → 单字五行偏好（规则表，无第三方库）。"""

from __future__ import annotations

from datetime import date, datetime

# 简化：公历日期的数字特征映射到「日主倾向」，再与时辰地支五行叠加
_DAY_STEM_ELEM = ["金", "木", "水", "火", "土"]  # 循环
_STEMS = ["甲", "乙", "丙", "丁", "戊", "己", "庚", "辛", "壬", "癸"]
_BRANCHES = ["子", "丑", "寅", "卯", "辰", "巳", "午", "未", "申", "酉", "戌", "亥"]

# 前端与后端共享的时段编码（演示规则）
BAZI_TIME_SLOT_TO_HOUR = {
    "ZI": 23,   # 子时 23:00-00:59
    "CHOU": 1,  # 丑时 01:00-02:59
    "YIN": 3,   # 寅时 03:00-04:59
    "MAO": 5,   # 卯时 05:00-06:59
    "CHEN": 7,  # 辰时 07:00-08:59
    "SI": 9,    # 巳时 09:00-10:59
    "WU": 11,   # 午时 11:00-12:59
    "WEI": 13,  # 未时 13:00-14:59
    "SHEN": 15, # 申时 15:00-16:59
    "YOU": 17,  # 酉时 17:00-18:59
    "XU": 19,   # 戌时 19:00-20:59
    "HAI": 21,  # 亥时 21:00-22:59
}


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


def _hour_branch_name(hour: int) -> str:
    idx = (hour + 1) // 2 % 12
    return _BRANCHES[idx]


def _pillar_from_index(idx: int) -> str:
    return f"{_STEMS[idx % 10]}{_BRANCHES[idx % 12]}"


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


def derive_bazi_text_from_birth(
    birth: date,
    birth_time_slot: str | None,
) -> str:
    """
    根据生日 + 出生时段推导演示版八字文本（非专业排盘）。
    格式示例：庚子年 丙午月 乙卯日 壬申时
    """
    slot = (birth_time_slot or "").strip().upper()
    hour = BAZI_TIME_SLOT_TO_HOUR.get(slot, 11)

    # 年柱：以 1984 甲子为锚点做 60 甲子循环
    year_idx = (birth.year - 1984) % 60
    year_pillar = _pillar_from_index(year_idx)

    # 月柱：演示近似（按公历月 + 年干偏移）
    year_stem_idx = year_idx % 10
    month_idx = (year_stem_idx * 2 + birth.month) % 60
    month_pillar = _pillar_from_index(month_idx)

    # 日柱：以 1984-02-02 为甲子锚点（演示规则）
    base_day = date(1984, 2, 2)
    day_idx = (birth.toordinal() - base_day.toordinal()) % 60
    day_pillar = _pillar_from_index(day_idx)

    # 时柱：按日干推时干，时支由出生时段决定
    hour_branch = _hour_branch_name(hour)
    hour_branch_idx = _BRANCHES.index(hour_branch)
    day_stem_idx = day_idx % 10
    hour_stem_idx = ((day_stem_idx % 5) * 2 + hour_branch_idx) % 10
    hour_pillar = f"{_STEMS[hour_stem_idx]}{hour_branch}"

    return f"{year_pillar}年 {month_pillar}月 {day_pillar}日 {hour_pillar}时"
