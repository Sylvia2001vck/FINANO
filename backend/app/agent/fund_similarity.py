"""
K 线 / 净值序列相似度。

- cosine / dtw：与历史行为一致（全候选逐只算一种度量）。
- tiered（默认 API）：目标时间轴上对齐日收益 → PAA 降维 → L2 归一后 Faiss 内积粗排（≈余弦）
  → 仅对 Top-M 候选做 Sakoe-Chiba 带窗 DTW 精排，兼顾滞后形态与耗时。
"""

from __future__ import annotations

import hashlib
import logging
import random
import time
from datetime import date, timedelta
from typing import Any, Literal

import numpy as np
import pandas as pd

from app.agent.fund_catalog import list_funds_catalog_only
from app.core.config import settings
from app.services.fund_data import fetch_fund_nav_history
from app.services.similar_funds import similar_funds

logger = logging.getLogger(__name__)

try:
    import faiss  # type: ignore

    _FAISS_AVAILABLE = True
except Exception:  # pragma: no cover - optional in odd envs
    faiss = None
    _FAISS_AVAILABLE = False

Method = Literal["cosine", "dtw", "tiered"]


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


def _dtw_distance_sakoe_chiba(a: np.ndarray, b: np.ndarray, band_ratio: float) -> float:
    """Sakoe-Chiba 带窗 DTW，降低滞后对齐时的计算量。"""
    n, m = len(a), len(b)
    if n == 0 or m == 0:
        return float("inf")
    w = max(3, int(float(band_ratio) * max(n, m)))
    inf = float("inf")
    dtw = np.full((n + 1, m + 1), inf)
    dtw[0, 0] = 0.0
    for i in range(1, n + 1):
        j0 = max(1, i - w)
        j1 = min(m, i + w)
        for j in range(j0, j1 + 1):
            cost = (a[i - 1] - b[j - 1]) ** 2
            dtw[i, j] = cost + min(dtw[i - 1, j], dtw[i, j - 1], dtw[i - 1, j - 1])
    d = float(dtw[n, m])
    if not np.isfinite(d) or d == inf:
        return _dtw_distance(a, b)
    return float(np.sqrt(d))


def similarity_dtw(a: np.ndarray, b: np.ndarray) -> float:
    """DTW 距离转相似度 (0,1]，越大越相似。"""
    za, zb = _zscore(a), _zscore(b)
    d = _dtw_distance(za, zb)
    return float(1.0 / (1.0 + d))


def similarity_dtw_banded(a: np.ndarray, b: np.ndarray, band_ratio: float | None = None) -> float:
    br = float(band_ratio if band_ratio is not None else settings.mafb_kline_dtw_band_ratio)
    za, zb = _zscore(a), _zscore(b)
    d = _dtw_distance_sakoe_chiba(za, zb, br)
    return float(1.0 / (1.0 + d))


def _paa(x: np.ndarray, n_segments: int) -> np.ndarray:
    """分段聚合近似（PAA）：将序列压成固定长度均值向量。"""
    x = np.asarray(x, dtype=float).ravel()
    n = int(x.size)
    m = max(2, int(n_segments))
    if n == 0:
        return np.zeros(m, dtype=float)
    edges = np.linspace(0, n, m + 1, dtype=int)
    out = np.empty(m, dtype=float)
    for i in range(m):
        lo, hi = int(edges[i]), int(edges[i + 1])
        seg = x[lo:hi]
        out[i] = float(np.mean(seg)) if seg.size else 0.0
    return out


def _series_on_master_dates(peer_map: dict[str, float], master_dates: list[str]) -> np.ndarray:
    """按目标基金的日期轴对齐：缺失日收益前向填充，首尾再用反向填充，仍缺则 0。"""
    raw = [float(peer_map[d]) if d in peer_map else np.nan for d in master_dates]
    s = pd.Series(raw, dtype="float64").ffill().bfill().fillna(0.0)
    return s.to_numpy(dtype=float)


def _coarse_paa_normalized(vec: np.ndarray, paa_bins: int) -> np.ndarray:
    z = _zscore(vec)
    p = _paa(z, paa_bins)
    p = np.nan_to_num(p.astype(float))
    nrm = np.linalg.norm(p) + 1e-9
    return (p / nrm).astype(np.float32)


def _faiss_topk_ip(
    query: np.ndarray, corpus: np.ndarray, k: int
) -> tuple[np.ndarray, np.ndarray]:
    """
    corpus: (N, D) float32, 行已 L2 归一；query: (D,) 已归一。
    返回 (scores, indices) 长度 min(k,N)，scores 为内积≈余弦。
    """
    n = int(corpus.shape[0])
    if n == 0:
        return np.array([], dtype=np.float32), np.array([], dtype=np.int64)
    kk = max(1, min(int(k), n))
    q = query.reshape(1, -1).astype(np.float32, copy=False)
    if _FAISS_AVAILABLE and faiss is not None:
        d = int(corpus.shape[1])
        index = faiss.IndexFlatIP(d)
        index.add(corpus.astype(np.float32, copy=False))
        scores, idx = index.search(q, kk)
        return scores[0][:kk].astype(np.float32), idx[0][:kk].astype(np.int64)
    sims = corpus @ query.astype(np.float32)
    idx = np.argsort(-sims)[:kk]
    return sims[idx].astype(np.float32), idx.astype(np.int64)


def calc_series_similarity(
    a: np.ndarray,
    b: np.ndarray,
    method: Literal["cosine", "dtw"] = "cosine",
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


def _tiered_similarity_rows(
    code: str,
    pool: list[dict[str, Any]],
    tgt_map: dict[str, float],
    tgt_synth: bool,
    days: int,
    top_n: int,
    nav_timeout: float,
    paa_bins: int,
    fine_pool: int,
) -> list[dict[str, Any]]:
    master_dates = sorted(tgt_map.keys())
    if len(master_dates) < 10:
        return []
    tgt_master = np.array([tgt_map[d] for d in master_dates], dtype=float)
    tgt_c = _coarse_paa_normalized(tgt_master, paa_bins)

    cand: list[dict[str, Any]] = []
    for row in pool:
        oc = str(row["code"])
        oh = fetch_fund_nav_history(oc, days=days, timeout=nav_timeout)
        omap = _returns_by_date(oh)
        peer_synth = False
        if len(omap) < 10:
            oh = _synthetic_nav_history(oc, max(days, 60))
            omap = _returns_by_date(oh)
            peer_synth = True
        peer_vec = _series_on_master_dates(omap, master_dates)
        if peer_vec.shape[0] != tgt_master.shape[0]:
            continue
        try:
            coarse_v = _coarse_paa_normalized(peer_vec, paa_bins)
            coarse_sim = float(np.dot(coarse_v.astype(float), tgt_c.astype(float)))
        except Exception:
            logger.debug("coarse paa failed: %s vs %s", code, oc, exc_info=True)
            continue
        cand.append(
            {
                "row": row,
                "code": oc,
                "peer_vec": peer_vec,
                "peer_synth": peer_synth,
                "coarse_sim": coarse_sim,
                "coarse_v": coarse_v,
            }
        )

    if not cand:
        return []

    feats = np.stack([c["coarse_v"] for c in cand], axis=0)
    m_take = max(1, min(int(fine_pool), len(cand)))
    _, top_idx = _faiss_topk_ip(tgt_c, feats, m_take)

    dtw_rows: list[tuple[float, dict[str, Any]]] = []
    fine_timeout_sec = float(settings.mafb_kline_fine_timeout_sec)
    fine_t0 = time.monotonic()
    degraded_fast_mode = False
    for ii in top_idx.tolist():
        i = int(ii)
        if i < 0 or i >= len(cand):
            continue
        item = cand[i]
        oc = item["code"]
        row = item["row"]
        peer_vec = item["peer_vec"]
        peer_synth = item["peer_synth"]
        coarse_sim = float(item["coarse_sim"])
        fine_budget_exceeded = fine_timeout_sec > 0 and (time.monotonic() - fine_t0) > fine_timeout_sec
        if fine_budget_exceeded:
            degraded_fast_mode = True
            fine_sim = float(max(0.0, min(1.0, (coarse_sim + 1) / 2)))
        else:
            try:
                fine_sim = similarity_dtw_banded(tgt_master, peer_vec, settings.mafb_kline_dtw_band_ratio)
            except Exception:
                logger.debug("banded dtw failed: %s vs %s", code, oc, exc_info=True)
                fine_sim = float(max(0.0, min(1.0, (coarse_sim + 1) / 2)))

        src_note = ""
        if tgt_synth or peer_synth:
            src_note = "（部分净值序列为演示合成，用于算法对齐演示）"
        rationale = (
            f"近 {days} 日：PAA({paa_bins}) 降维 + {'Faiss IP' if _FAISS_AVAILABLE else '归一向量内积'}粗排，"
            f"再对粗排前 {m_take} 只做带窗 DTW 精排（历史形态，非预测）"
            f"{'；本次触发快速降级（返回粗排近似）' if fine_budget_exceeded else ''}{src_note}"
        )
        dtw_rows.append(
            (
                fine_sim,
                {
                    "code": oc,
                    "name": row.get("name", ""),
                    "track": row.get("track", ""),
                    "similarity": round(float(fine_sim), 4),
                    "coarse_similarity": round(float(coarse_sim), 4),
                    "method": "tiered",
                    "pipeline": "paa_ip_dtw_band",
                    "fast_mode": bool(fine_budget_exceeded),
                    "window_days": days,
                    "aligned_points": int(len(tgt_master)),
                    "nav_series": "synthetic" if (tgt_synth or peer_synth) else "live",
                    "rationale": rationale,
                },
            )
        )

    dtw_rows.sort(key=lambda x: x[0], reverse=True)
    out = [x[1] for x in dtw_rows[:top_n]]
    if degraded_fast_mode:
        logger.info("kline tiered fine phase timeout, fallback to coarse approx: target=%s days=%s", code, days)
    return out


def find_similar_kline_funds(
    target_code: str,
    top_n: int = 5,
    days: int = 60,
    method: Method = "tiered",
    *,
    max_nav_fetches: int | None = None,
) -> list[dict[str, Any]]:
    """
    在基金目录内（除目标外）比较近 N 日对齐日收益率序列，返回相似度最高的 top_n。
    目录很大时先用统计特征相似预筛候选，再拉净值，避免数百次顺序 lsjz 请求。
    tiered：PAA 粗排 + Faiss 内积 + 带窗 DTW 精排（仅精排子集）。
    """
    cap = int(max_nav_fetches or settings.mafb_kline_similar_max_nav_fetches)
    cap = max(16, min(cap, 400))
    paa_bins = int(settings.mafb_kline_paa_bins)
    fine_pool = int(settings.mafb_kline_fine_pool)

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

    if method == "tiered":
        return _tiered_similarity_rows(
            code, pool, tgt_map, tgt_synth, days, top_n, nav_timeout, paa_bins, fine_pool
        )

    scored: list[tuple[float, str, dict[str, Any]]] = []
    m: Literal["cosine", "dtw"] = "dtw" if method == "dtw" else "cosine"
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
            sim = calc_series_similarity(va, vb, method=m)
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
                    "method": m,
                    "window_days": days,
                    "aligned_points": int(len(va)),
                    "nav_series": "synthetic" if (tgt_synth or peer_synth) else "live",
                    "rationale": (
                        f"近 {days} 个交易日对齐日收益率序列的{('余弦' if m == 'cosine' else 'DTW')}相似度"
                        f"（演示用，历史不代表未来）{src_note}"
                    ),
                },
            )
        )

    scored.sort(key=lambda x: x[0], reverse=True)
    return [x[2] for x in scored[:top_n]]
