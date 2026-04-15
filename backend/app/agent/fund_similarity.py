"""
K 线 / 净值序列相似度：近 N 日日收益率对齐后，余弦相似度或轻量 DTW（纯 NumPy，无 scipy/fastdtw 依赖）。
"""

from __future__ import annotations

import logging
from typing import Any, Literal

import numpy as np

from app.agent.fund_catalog import list_funds_catalog_only
from app.services.fund_data import fetch_fund_nav_history

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


def find_similar_kline_funds(
    target_code: str,
    top_n: int = 5,
    days: int = 60,
    method: Method = "cosine",
) -> list[dict[str, Any]]:
    """
    在演示池内（除目标外）比较近 N 日对齐日收益率序列，返回相似度最高的 top_n。
    任一步失败则跳过该基金；目标无历史则返回 []。
    """
    code = target_code.strip()
    tgt_hist = fetch_fund_nav_history(code, days=days)
    tgt_map = _returns_by_date(tgt_hist)
    if len(tgt_map) < 10:
        logger.debug("target kline too short: %s", code)
        return []

    scored: list[tuple[float, str, dict[str, Any]]] = []
    for row in list_funds_catalog_only():
        oc = str(row["code"])
        if oc == code:
            continue
        oh = fetch_fund_nav_history(oc, days=days)
        omap = _returns_by_date(oh)
        aligned = _align_returns(tgt_map, omap)
        if aligned is None:
            continue
        va, vb = aligned
        try:
            sim = calc_series_similarity(va, vb, method=method)
        except Exception:
            logger.debug("similarity calc failed: %s vs %s", code, oc, exc_info=True)
            continue
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
                    "rationale": (
                        f"近 {days} 个交易日对齐日收益率序列的{('余弦' if method == 'cosine' else 'DTW')}相似度"
                        f"（演示用，历史不代表未来）。"
                    ),
                },
            )
        )

    scored.sort(key=lambda x: x[0], reverse=True)
    return [x[2] for x in scored[:top_n]]
