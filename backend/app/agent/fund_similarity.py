"""
K 线 / 净值序列相似度：近 N 日日收益率对齐后，余弦相似度或轻量 DTW（纯 NumPy，无 scipy/fastdtw 依赖）。
"""

from __future__ import annotations

import hashlib
import logging
import random
from datetime import date, timedelta
from typing import Any, Literal

import numpy as np

from app.agent.fund_catalog import list_funds_catalog_only
from app.core.config import settings
from app.services.fund_data import fetch_fund_nav_history
from app.services.similar_funds import similar_funds

logger = logging.getLogger(__name__)

Method = Literal["cosine", "dtw"]


def _returns_by_date(history: list[dict[str, Any]]) -> dict[str, float]:
    return {str(h["date"]): float(h["daily_return"]) for h in history if "date" in h and "daily_return" in h}


def _align_returns(
    target: dict[str, float], other: dict[str, float]
) -> tuple[np.ndarray, np.ndarray] | None:
    dates = sorted(set(target) & set(other))
    if len(dates) < 10:
        return None
    a = np.array([target[d] for d in dates], dtype=float)
    b = np.array([other[d] for d in dates], dtype=float)
    return a, b


def _zscore(x: np.ndarray) -> np.ndarray:
    x = np.nan_to_num(x.astype(float))
    return (x - np.mean(x)) / (np.std(x) + 1e-9)


def similarity_cosine(a: np.ndarray, b: np.ndarray) -> float:
    """标准化后余弦相似度，约 [-1, 1]，越大越相似。"""
    za, zb = _zscore(a), _zscore(b)
    denom = np.linalg.norm(za) * np.linalg.norm(zb) + 1e-9
    return float(np.dot(za, zb) / denom)


def _dtw_distance(a: np.ndarray, b: np.ndarray) -> float:
    """经典 DTW，O(nm)，n,m≤120 可接受。"""
    n, m = len(a), len(b)
    inf = float("inf")
    dtw = np.full((n + 1, m + 1), inf)
    dtw[0, 0] = 0.0
    for i in range(1, n + 1):
        for j in range(1, m + 1):
            cost = (a[i - 1] - b[j - 1]) ** 2
            dtw[i, j] = cost + min(dtw[i - 1, j], dtw[i, j - 1], dtw[i - 1, j - 1])
    return float(np.sqrt(dtw[n, m]))


def similarity_dtw(a: np.ndarray, b: np.ndarray) -> float:
    """DTW 距离转相似度 (0,1]，越大越相似。"""
    za, zb = _zscore(a), _zscore(b)
    d = _dtw_distance(za, zb)
    return float(1.0 / (1.0 + d))


def calc_series_similarity(
    a: np.ndarray,
    b: np.ndarray,
    method: Method = "cosine",
) -> float:
    if method == "dtw":
        return similarity_dtw(a, b)
    return similarity_cosine(a, b)


def _synthetic_nav_history(code: str, days: int) -> list[dict[str, Any]]:
    """
    东方财富未返回足够净值时：用基金代码种子生成确定性日收益序列，使 K 线余弦在演示池/失败降级下仍可计算。
    非真实行情，仅用于课堂演示对齐算法。
    """
    n_days = max(30, int(days))
    seed = int(hashlib.sha256(f"kline-synth:{code}".encode()).hexdigest()[:12], 16)
    rng = np.random.default_rng(seed % (2**32 - 1))
    base = date.today()
    rows: list[dict[str, Any]] = []
    nav = 1.0
    for i in range(n_days):
        d = base - timedelta(days=n_days - 1 - i)
        dr = float(rng.normal(0.0004, 0.011))
        nav = float(nav * (1.0 + dr))
        rows.append(
            {
                "date": d.isoformat(),
                "nav": nav,
                "daily_return": dr,
                "daily_pct_display": f"{dr * 100:.2f}%",
            }
        )
    return rows


def _peer_pool(catalog: list[dict[str, Any]], target_code: str, track: str, max_n: int) -> list[dict[str, Any]]:
    pool = [r for r in catalog if str(r.get("code")) != target_code]
    if len(pool) <= max_n:
        return pool
    same = [r for r in pool if (r.get("track") or "") == track]
    rnd = random.Random(int(hashlib.sha256(target_code.encode()).hexdigest()[:8], 16))
    out: list[dict[str, Any]] = []
    codes: set[str] = set()
    half = max_n // 2
    if len(same) >= 40:
        rnd.shuffle(same)
        for r in same:
            c = str(r.get("code"))
            if c in codes:
                continue
            out.append(r)
            codes.add(c)
            if len(out) >= half:
                break
    else:
        for r in same:
            c = str(r.get("code"))
            if c not in codes:
                out.append(r)
                codes.add(c)
    rest = [r for r in pool if str(r.get("code")) not in codes]
    rnd.shuffle(rest)
    for r in rest:
        if len(out) >= max_n:
            break
        out.append(r)
    return out[:max_n]


def _pool_from_feature_then_random(
    catalog: list[dict[str, Any]],
    target_code: str,
    track: str,
    max_n: int,
) -> list[dict[str, Any]]:
    """
    先用与 /agent/funds/similar 同源的特征余弦筛一批代码，再只对这批拉 lsjz；
    不足时用 _peer_pool 补齐，避免对数百只基金顺序 HTTP。
    """
    code = target_code.strip()
    code_to_row = {str(c.get("code")): c for c in catalog if str(c.get("code", "")) != code}
    if not code_to_row:
        return []
    want = max(1, min(max_n, len(code_to_row)))
    feat_top_k = min(len(code_to_row), max(want * 3, 96))
    ranked = similar_funds(code, top_k=feat_top_k)
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for r in ranked:
        c = str(r.get("code") or "")
        if not c or c in seen:
            continue
        row = code_to_row.get(c)
        if row is None:
            continue
        out.append(row)
        seen.add(c)
        if len(out) >= want:
            return out[:max_n]
    extra = _peer_pool(catalog, code, track or "宽基", max_n=max(0, want - len(out)))
    for row in extra:
        c = str(row.get("code") or "")
        if c in seen:
            continue
        out.append(row)
        seen.add(c)
        if len(out) >= want:
            break
    return out[:max_n]


def find_similar_kline_funds(
    target_code: str,
    top_n: int = 5,
    days: int = 60,
    method: Method = "cosine",
    *,
    max_nav_fetches: int | None = None,
) -> list[dict[str, Any]]:
    """
    在基金目录内（除目标外）比较近 N 日对齐日收益率序列，返回相似度最高的 top_n。
    目录很大时先用统计特征相似预筛候选，再拉净值，避免数百次顺序 lsjz 请求。
    任一步失败则跳过该基金；目标无历史则返回 []。
    """
    cap = int(max_nav_fetches or settings.mafb_kline_similar_max_nav_fetches)
    cap = max(16, min(cap, 400))

    code = target_code.strip()
    nav_timeout = 8.0
    tgt_hist = fetch_fund_nav_history(code, days=days, timeout=nav_timeout)
    tgt_map = _returns_by_date(tgt_hist)
    tgt_synth = False
    if len(tgt_map) < 10:
        tgt_hist = _synthetic_nav_history(code, max(days, 60))
        tgt_map = _returns_by_date(tgt_hist)
        tgt_synth = True
        logger.info("kline target using synthetic series (short/missing live nav): %s", code)

    catalog = list_funds_catalog_only()
    target_meta = next((r for r in catalog if str(r["code"]) == code), None)
    track = (target_meta or {}).get("track") or ""
    pool = _pool_from_feature_then_random(catalog, code, track or "宽基", cap)
    if len(pool) < 8:
        pool = _peer_pool(catalog, code, track or "宽基", min(cap, 48))

    scored: list[tuple[float, str, dict[str, Any]]] = []
    for row in pool:
        oc = str(row["code"])
        oh = fetch_fund_nav_history(oc, days=days, timeout=nav_timeout)
        omap = _returns_by_date(oh)
        peer_synth = False
        if len(omap) < 10:
            oh = _synthetic_nav_history(oc, max(days, 60))
            omap = _returns_by_date(oh)
            peer_synth = True
        aligned = _align_returns(tgt_map, omap)
        if aligned is None:
            continue
        va, vb = aligned
        try:
            sim = calc_series_similarity(va, vb, method=method)
        except Exception:
            logger.debug("similarity calc failed: %s vs %s", code, oc, exc_info=True)
            continue
        src_note = ""
        if tgt_synth or peer_synth:
            src_note = "（部分净值序列为演示合成，用于算法对齐演示）"
        scored.append(
            (
                sim,
                oc,
                {
                    "code": oc,
                    "name": row.get("name", ""),
                    "track": row.get("track", ""),
                    "similarity": round(float(sim), 4),
                    "method": method,
                    "window_days": days,
                    "aligned_points": int(len(va)),
                    "nav_series": "synthetic" if (tgt_synth or peer_synth) else "live",
                    "rationale": (
                        f"近 {days} 个交易日对齐日收益率序列的{('余弦' if method == 'cosine' else 'DTW')}相似度"
                        f"（演示用，历史不代表未来）{src_note}"
                    ),
                },
            )
        )

    scored.sort(key=lambda x: x[0], reverse=True)
    return [x[2] for x in scored[:top_n]]
