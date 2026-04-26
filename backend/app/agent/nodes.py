from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import math
from typing import Any

from app.agent.fund_catalog import get_fund_by_code
from app.agent.kline_retriever import retrieve_technical_matches
from app.agent.llm_client import invoke_compliance_llm, invoke_finance_agent_score
from app.agent.profiling_mafb import build_user_profile_mafb
from app.agent.rag_faiss import rerank_by_profile, retrieve_fund_context
from app.agent.runtime_trace import emit_agent_event
from app.agent.state import MAFBState
from app.core.config import settings
from app.agent.top5 import (
    build_position_advice_mafb,
    build_reasoning_chain,
)
from app.modules.fund_nav.service import get_latest_fund_snapshot_cached
from app.services.fund_fundamental import fetch_fund_fundamental_snapshot
from app.services.fund_data import fetch_fund_live_quote, fetch_fund_nav_history
from app.services.news_signals import fetch_news_signals_for_fund

_FORBIDDEN = ("保证收益", "稳赚", "无风险", "内幕", "必涨", "只赚不赔")
_WEIGHTS = {
    "fundamental": 0.24,
    "technical": 0.24,
    "risk": 0.22,
    "attribution": 0.18,
    "profiling": 0.12,
}


def _clamp_score(value: float) -> int:
    return max(-2, min(2, int(round(value))))


def _fbti_track_alignment_score(state: MAFBState) -> tuple[int, str]:
    profile = state.get("user_profile") or {}
    if profile.get("profile_mode") == "no_fbti":
        return (
            0,
            "未纳入 FBTI：画像维度不包含人格-赛道偏好匹配，本项记为中性分（演示）。",
        )
    fund = state.get("fund_data") or {}
    track = str(fund.get("track") or "宽基")
    pref = str(profile.get("fund_preference_summary") or "")
    name_fb = str(profile.get("fbti_name") or "—")
    tags = profile.get("style_tags") or []
    blob = pref + " ".join(str(t) for t in tags)
    score = 0
    if track and track in blob:
        score = 2
    else:
        for piece in pref.replace("、", " ").replace("，", " ").replace(",", " ").split():
            p = piece.strip()
            if len(p) >= 2 and p in track:
                score = 1
                break
        if score == 0 and tags:
            if any(str(t) in track for t in tags if len(str(t)) >= 2):
                score = 1
    level = "高匹配" if score >= 2 else ("中性匹配" if score >= 0 else "低匹配")
    reason = (
        f"【核心结论】{level}；"
        f"【画像对撞数据】用户画像={name_fb}，偏好摘要={pref[:80] or '—'}，标的赛道={track}；"
        f"【逻辑推演】画像偏好与标的风格的一致性用于评估持有体验，错配时更易在波动中非理性赎回；"
        f"【适配打分】{score}"
    )
    return _clamp_score(score), reason


def _paa_segments_from_nav(nav_rows: list[dict[str, Any]], bins: int = 8) -> list[str]:
    nav_vals = [float(r.get("nav") or 0.0) for r in nav_rows if r.get("nav") is not None]
    if len(nav_vals) < 8:
        return []
    n = len(nav_vals)
    lo = min(nav_vals)
    hi = max(nav_vals)
    span = (hi - lo) or 1.0
    out: list[str] = []
    for i in range(bins):
        l = int(i * n / bins)
        r = int((i + 1) * n / bins)
        if r <= l:
            continue
        seg = nav_vals[l:r]
        if len(seg) < 2:
            continue
        s0 = seg[0]
        s1 = seg[-1]
        p0 = int(round(((s0 - lo) / span) * 9 + 1))
        p1 = int(round(((s1 - lo) / span) * 9 + 1))
        slope = s1 - s0
        if slope > 0.003:
            desc = "稳步爬升"
        elif slope < -0.003:
            desc = "加速下探" if abs(slope) > 0.012 else "震荡下行"
        else:
            desc = "高位横盘" if p0 >= 7 else ("低位盘整" if p0 <= 4 else "中位震荡")
        out.append(f"S{i + 1}: {p0}->{p1}, {desc}")
    return out


def _kline_feature_tags(nav_rows: list[dict[str, Any]]) -> dict[str, str]:
    nav_vals = [float(r.get("nav") or 0.0) for r in nav_rows if r.get("nav") is not None]
    if len(nav_vals) < 20:
        return {}
    last = nav_vals[-1]
    ma5 = sum(nav_vals[-5:]) / 5
    ma20 = sum(nav_vals[-20:]) / 20
    bias20 = (last / ma20 - 1.0) if ma20 else 0.0
    mom20 = (last / nav_vals[-20] - 1.0) if nav_vals[-20] else 0.0
    trend = "Bearish" if (last < ma5 < ma20) else ("Bullish" if (last > ma5 > ma20) else "Neutral")
    pattern = "Breakdown" if bias20 < -0.04 else ("Breakout" if bias20 > 0.04 else "Range")
    support = f"{min(nav_vals[-20:]):.4f}"
    return {
        "Trend": trend,
        "Bias20": f"{bias20:.2%}",
        "Momentum20": f"{mom20:.2%}",
        "Pattern": pattern,
        "Support_Level": support,
    }


def _build_kline_symbolic_chunks(code: str, rows: list[dict[str, Any]], days: int = 80) -> list[str]:
    nav_rows = fetch_fund_nav_history(code, days=days, timeout=8.0)
    segs = _paa_segments_from_nav(nav_rows, bins=8)
    tags = _kline_feature_tags(nav_rows)
    top = rows[0] if rows else {}
    dtw_sim = float(top.get("similarity") or 0.0)
    case_name = str(top.get("name") or top.get("code") or "N/A")
    chunks: list[str] = []
    if segs:
        chunks.append("K-Line Segments: " + "; ".join(f"[{s}]" for s in segs))
    if tags:
        chunks.append("Detected Patterns: " + str(tags).replace("'", '"'))
    chunks.append(
        f'Current DTW Match: {dtw_sim:.2f} similarity to "{case_name}". '
        "Historical outcome reference: short-term inertia may persist."
    )
    return chunks


def _calc_sharpe_from_returns(returns: list[float]) -> float | None:
    if len(returns) < 30:
        return None
    mean = sum(returns) / len(returns)
    var = sum((x - mean) ** 2 for x in returns) / max(1, (len(returns) - 1))
    std = math.sqrt(var)
    if std <= 1e-8:
        return None
    return float((mean / std) * math.sqrt(252.0))


def _calc_max_drawdown(nav_vals: list[float]) -> float | None:
    if len(nav_vals) < 10:
        return None
    peak = nav_vals[0]
    mdd = 0.0
    for v in nav_vals:
        if v > peak:
            peak = v
        if peak > 0:
            mdd = max(mdd, (peak - v) / peak)
    return float(mdd)


def _calc_volatility_from_returns(returns: list[float]) -> float | None:
    if len(returns) < 20:
        return None
    mean = sum(returns) / len(returns)
    var = sum((x - mean) ** 2 for x in returns) / max(1, (len(returns) - 1))
    return float(math.sqrt(var) * math.sqrt(252.0))


def _calc_sortino_from_returns(returns: list[float], target_daily: float = 0.0) -> float | None:
    if len(returns) < 40:
        return None
    downside = [(r - target_daily) for r in returns if r < target_daily]
    if not downside:
        return None
    downside_var = sum(d * d for d in downside) / max(1, len(downside) - 1)
    downside_dev = math.sqrt(downside_var)
    if downside_dev <= 1e-9:
        return None
    mean_excess = (sum(returns) / len(returns)) - target_daily
    return float((mean_excess / downside_dev) * math.sqrt(252.0))


def _calc_var_95_from_returns(returns: list[float]) -> float | None:
    if len(returns) < 40:
        return None
    vals = sorted(float(x) for x in returns)
    idx = max(0, min(len(vals) - 1, int(round(0.05 * (len(vals) - 1)))))
    q05 = vals[idx]
    # VaR95: 以正数表示潜在损失幅度
    return float(max(0.0, -q05))


def _returns_from_akshare_fund_daily(code: str, max_days: int = 320) -> list[float]:
    try:
        import akshare as ak  # type: ignore
    except Exception:
        return []
    df = None
    try:
        # 常见 open fund 历史净值接口（列名随版本有差异）
        df = ak.fund_open_fund_info_em(fund=code, indicator="单位净值走势")
    except Exception:
        return []
    if df is None or getattr(df, "empty", True):
        return []
    cols = list(df.columns)
    nav_col = next((c for c in cols if "单位净值" in str(c) or "净值" in str(c)), None)
    if not nav_col:
        return []
    vals: list[float] = []
    try:
        for v in df[nav_col].tolist()[-max_days:]:
            x = float(v)
            if x > 0:
                vals.append(x)
    except Exception:
        return []
    if len(vals) < 20:
        return []
    rets: list[float] = []
    for i in range(1, len(vals)):
        prev = vals[i - 1]
        if prev > 0:
            rets.append(vals[i] / prev - 1.0)
    return rets


def _calc_corr_by_daily_returns(rows_a: list[dict[str, Any]], rows_b: list[dict[str, Any]]) -> float | None:
    ra = {
        str(r.get("date") or ""): float(r.get("daily_return") or 0.0)
        for r in rows_a
        if r.get("date") is not None and r.get("daily_return") is not None
    }
    rb = {
        str(r.get("date") or ""): float(r.get("daily_return") or 0.0)
        for r in rows_b
        if r.get("date") is not None and r.get("daily_return") is not None
    }
    common = sorted(set(ra.keys()) & set(rb.keys()))
    if len(common) < 20:
        return None
    a = [ra[d] for d in common]
    b = [rb[d] for d in common]
    ma = sum(a) / len(a)
    mb = sum(b) / len(b)
    va = sum((x - ma) ** 2 for x in a) / max(1, len(a) - 1)
    vb = sum((y - mb) ** 2 for y in b) / max(1, len(b) - 1)
    if va <= 1e-12 or vb <= 1e-12:
        return None
    cov = sum((x - ma) * (y - mb) for x, y in zip(a, b)) / max(1, len(a) - 1)
    corr = cov / (math.sqrt(va) * math.sqrt(vb))
    return float(max(-1.0, min(1.0, corr)))


def _index_returns_akshare(symbol: str, max_days: int = 320) -> dict[str, float]:
    try:
        import akshare as ak  # type: ignore
    except Exception:
        return {}
    try:
        df = ak.stock_zh_index_daily(symbol=symbol)
    except Exception:
        return {}
    if df is None or getattr(df, "empty", True):
        return {}
    cols = list(df.columns)
    date_col = next((c for c in cols if str(c).lower() in {"date", "日期"}), None)
    close_col = next((c for c in cols if str(c).lower() in {"close", "收盘"}), None)
    if not date_col or not close_col:
        return {}
    try:
        work = df[[date_col, close_col]].dropna().tail(max_days)
        dates = [str(x)[:10] for x in work[date_col].tolist()]
        closes = [float(x) for x in work[close_col].tolist()]
    except Exception:
        return {}
    out: dict[str, float] = {}
    for i in range(1, len(closes)):
        prev = closes[i - 1]
        if prev > 0:
            out[dates[i]] = closes[i] / prev - 1.0
    return out


def _corr_with_index_map(nav_rows: list[dict[str, Any]], idx_ret: dict[str, float]) -> float | None:
    if not idx_ret:
        return None
    ra = {
        str(r.get("date") or ""): float(r.get("daily_return") or 0.0)
        for r in nav_rows
        if r.get("date") is not None and r.get("daily_return") is not None
    }
    common = sorted(set(ra.keys()) & set(idx_ret.keys()))
    if len(common) < 20:
        return None
    a = [ra[d] for d in common]
    b = [idx_ret[d] for d in common]
    ma = sum(a) / len(a)
    mb = sum(b) / len(b)
    va = sum((x - ma) ** 2 for x in a) / max(1, len(a) - 1)
    vb = sum((y - mb) ** 2 for y in b) / max(1, len(b) - 1)
    if va <= 1e-12 or vb <= 1e-12:
        return None
    cov = sum((x - ma) * (y - mb) for x, y in zip(a, b)) / max(1, len(a) - 1)
    return float(max(-1.0, min(1.0, cov / (math.sqrt(va) * math.sqrt(vb)))))


def _drawdown_recovery_profile(nav_vals: list[float]) -> dict[str, Any]:
    if len(nav_vals) < 30:
        return {"events": 0, "avg_recovery_days": None}
    peak = nav_vals[0]
    peak_idx = 0
    in_dd = False
    recover_days: list[int] = []
    for i, v in enumerate(nav_vals):
        if v >= peak:
            if in_dd:
                recover_days.append(i - peak_idx)
                in_dd = False
            peak = v
            peak_idx = i
            continue
        dd = (peak - v) / peak if peak > 0 else 0.0
        if dd >= 0.03:
            in_dd = True
    avg_rec = (sum(recover_days) / len(recover_days)) if recover_days else None
    return {"events": int(len(recover_days)), "avg_recovery_days": (float(avg_rec) if avg_rec is not None else None)}


def _liquidity_risk_tag(aum_billion: float | None, concentration: float | None, track: str) -> str:
    aum = float(aum_billion or 0.0)
    conc = float(concentration or 0.0)
    niche = any(k in (track or "") for k in ["半导体", "医药", "军工", "有色", "创业板", "科创"])
    if aum >= 120 and conc >= 0.6 and niche:
        return "high_crush_risk"
    if aum >= 80 and conc >= 0.5:
        return "medium_crush_risk"
    return "normal"


def _liquidity_risk_with_holdings(
    aum_billion: float | None,
    concentration_top5: float | None,
    top_holdings: list[dict[str, Any]] | None,
    track: str,
) -> tuple[str, float | None]:
    tag = _liquidity_risk_tag(aum_billion, concentration_top5, track)
    if not top_holdings:
        return tag, None
    try:
        import akshare as ak  # type: ignore
    except Exception:
        return tag, None
    amount_sum = 0.0
    n = 0
    for h in (top_holdings or [])[:5]:
        code = str(h.get("code") or "").strip()
        if not code or len(code) != 6:
            continue
        for prefix in ("sh", "sz"):
            symbol = f"{prefix}{code}"
            try:
                df = ak.stock_zh_a_hist(symbol=symbol, period="daily", adjust="")
                if df is None or getattr(df, "empty", True):
                    continue
                cols = list(df.columns)
                amt_col = next((c for c in cols if "成交额" in str(c) or str(c).lower() == "amount"), None)
                if not amt_col:
                    continue
                amt = float(df[amt_col].dropna().tail(1).iloc[0])
                if amt > 0:
                    amount_sum += amt
                    n += 1
                    break
            except Exception:
                continue
    avg_turnover = (amount_sum / n) if n > 0 else None
    aum = float(aum_billion or 0.0) * 1e8
    if avg_turnover and aum > 0:
        ratio = aum / max(avg_turnover, 1.0)
        if ratio > 50 and (concentration_top5 or 0.0) >= 0.5:
            return "high_crush_risk", avg_turnover
        if ratio > 20 and (concentration_top5 or 0.0) >= 0.4:
            return "medium_crush_risk", avg_turnover
    return tag, avg_turnover


def _build_risk_summary(
    fund: dict[str, Any],
    nav_vals: list[float],
    returns: list[float],
    nav_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    if len(nav_vals) < 40:
        return {}
    ak_rets = _returns_from_akshare_fund_daily(str(fund.get("code") or ""), max_days=320)
    sortino = _calc_sortino_from_returns(ak_rets if len(ak_rets) >= 40 else returns)
    var95 = _calc_var_95_from_returns(returns)
    profile = _drawdown_recovery_profile(nav_vals)
    idx_hs300 = _index_returns_akshare("sh000300", max_days=320)
    idx_nasdaq = _index_returns_akshare("sz399006", max_days=320)  # 国内可得指数代理；海外不可得时由 fallback 补
    corr_hs300 = _corr_with_index_map(nav_rows, idx_hs300)
    corr_ndq = _corr_with_index_map(nav_rows, idx_nasdaq)
    if corr_hs300 is None or corr_ndq is None:
        hs300_rows = fetch_fund_nav_history("510300", days=260, timeout=8.0)
        ndq_rows = fetch_fund_nav_history("513100", days=260, timeout=8.0)
        corr_hs300 = corr_hs300 if corr_hs300 is not None else _calc_corr_by_daily_returns(nav_rows, hs300_rows)
        corr_ndq = corr_ndq if corr_ndq is not None else _calc_corr_by_daily_returns(nav_rows, ndq_rows)
    concentration = fund.get("stock_top5_concentration")
    if concentration is None:
        concentration = fund.get("stock_top10_concentration")
    aum = fund.get("aum_billion")
    top_holdings = list(fund.get("top_holdings") or [])
    liq_tag, avg_turnover = _liquidity_risk_with_holdings(
        aum if isinstance(aum, (int, float)) else None,
        concentration if isinstance(concentration, (int, float)) else None,
        top_holdings,
        str(fund.get("track") or ""),
    )
    data_ready = bool(var95 is not None and (sortino is not None or fund.get("volatility_60d") is not None))
    return {
        "data_ready": data_ready,
        "sortino_ratio": sortino,
        "var_95_1d": var95,
        "drawdown_profile": profile,
        "concentration": concentration,
        "correlation": {"hs300": corr_hs300, "nasdaq100": corr_ndq},
        "liquidity_tag": liq_tag,
        "avg_top5_turnover": avg_turnover,
        "news_black_swan_score": 0.0,
        "news_policy_score": 0.0,
    }


def _ema_series(values: list[float], span: int) -> list[float]:
    if not values:
        return []
    k = 2.0 / (span + 1.0)
    out: list[float] = [float(values[0])]
    for v in values[1:]:
        out.append(float(v) * k + out[-1] * (1.0 - k))
    return out


def _calc_rsi(nav_vals: list[float], period: int = 14) -> float | None:
    if len(nav_vals) < period + 1:
        return None
    gains: list[float] = []
    losses: list[float] = []
    for i in range(1, len(nav_vals)):
        d = float(nav_vals[i] - nav_vals[i - 1])
        gains.append(max(d, 0.0))
        losses.append(max(-d, 0.0))
    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period
    for i in range(period, len(gains)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
    if avg_loss <= 1e-12:
        return 100.0
    rs = avg_gain / avg_loss
    return float(100.0 - (100.0 / (1.0 + rs)))


def _calc_macd_snapshot(nav_vals: list[float]) -> dict[str, Any]:
    if len(nav_vals) < 35:
        return {}
    ema12 = _ema_series(nav_vals, 12)
    ema26 = _ema_series(nav_vals, 26)
    dif = [a - b for a, b in zip(ema12, ema26)]
    dea = _ema_series(dif, 9)
    hist = [(d - e) * 2.0 for d, e in zip(dif, dea)]
    if len(hist) < 2:
        return {}
    last_hist = float(hist[-1])
    prev_hist = float(hist[-2])
    cross = "golden_cross" if (dif[-1] > dea[-1] and dif[-2] <= dea[-2]) else (
        "death_cross" if (dif[-1] < dea[-1] and dif[-2] >= dea[-2]) else "none"
    )
    hist_trend = "increasing" if last_hist > prev_hist else "decreasing"
    return {
        "dif": float(dif[-1]),
        "dea": float(dea[-1]),
        "hist": float(last_hist),
        "signal": cross,
        "hist_trend": hist_trend,
    }


def _calc_horizon_return(nav_vals: list[float], horizon: int) -> float | None:
    if len(nav_vals) <= horizon or horizon <= 0:
        return None
    base = float(nav_vals[-(horizon + 1)] or 0.0)
    if base <= 0:
        return None
    return float(nav_vals[-1] / base - 1.0)


def _dtw_outcome_snapshot(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for r in rows[:3]:
        code = str(r.get("code") or "").strip()
        if not code:
            continue
        # 极速模式：不再为 Top3 逐只二次拉净值，优先返回主流程速度
        h5 = r.get("historical_outcome_5d")
        h10 = r.get("historical_outcome_10d")
        h20 = r.get("historical_outcome_20d")
        out.append(
            {
                "code": code,
                "name": str(r.get("name") or code),
                "score": float(r.get("similarity") or 0.0),
                "historical_outcome_5d": h5,
                "historical_outcome_10d": h10,
                "historical_outcome_20d": h20,
            }
        )
    return out


def _build_technical_summary(fund: dict[str, Any], nav_vals: list[float], dtw_rows: list[dict[str, Any]]) -> dict[str, Any]:
    if len(nav_vals) < 35:
        return {}
    ema5 = _ema_series(nav_vals, 5)[-1]
    ema20 = _ema_series(nav_vals, 20)[-1]
    ema60 = _ema_series(nav_vals, 60)[-1] if len(nav_vals) >= 60 else _ema_series(nav_vals, max(24, len(nav_vals) // 2))[-1]
    last = float(nav_vals[-1])
    bias20 = (last - ema20) / ema20 if ema20 else 0.0
    bull = ema5 > ema20 > ema60
    bear = ema5 < ema20 < ema60
    trend = "Strong Bullish" if bull else ("Strong Bearish" if bear else "Range/Transition")
    bias_text = (
        "Overheat (pullback risk)"
        if bias20 > 0.05
        else ("Oversold (rebound watch)" if bias20 < -0.05 else "Healthy range")
    )
    rsi = _calc_rsi(nav_vals, 14)
    if rsi is None:
        rsi = 50.0
    rsi_status = "Overbought" if rsi >= 70 else ("Oversold" if rsi <= 30 else "Neutral")
    macd = _calc_macd_snapshot(nav_vals)
    dtw_top = _dtw_outcome_snapshot(dtw_rows)
    best = dtw_top[0] if dtw_top else None
    return {
        "trend": trend,
        "ema": {"ema_5": float(ema5), "ema_20": float(ema20), "ema_60": float(ema60)},
        "bias": {"value": float(bias20), "status": bias_text},
        "momentum": {
            "rsi": float(rsi),
            "status": rsi_status,
            "macd": macd or {},
        },
        "pattern_recognition": {
            "name": "DTW_shape_match",
            "similarity_match": best or {},
            "top3_matches": dtw_top,
        },
    }


def _technical_report_bundle(fund: dict[str, Any]) -> dict[str, Any]:
    tech = dict(fund.get("technical_summary") or {})
    if not tech:
        return {}
    patt = dict(tech.get("pattern_recognition") or {})
    top3 = list(patt.get("top3_matches") or [])
    projection = []
    for item in top3[:3]:
        projection.append(
            {
                "code": item.get("code"),
                "name": item.get("name"),
                "score": item.get("score"),
                "expected_5d": item.get("historical_outcome_5d"),
                "expected_10d": item.get("historical_outcome_10d"),
                "expected_20d": item.get("historical_outcome_20d"),
            }
        )
    tech["projection_candidates"] = projection
    tech["render_hints"] = {
        "base_layer": "use_nav_curve",
        "signal_layer": {
            "rsi": float(((tech.get("momentum") or {}).get("rsi") or 0.0)),
            "macd_signal": str((((tech.get("momentum") or {}).get("macd") or {}).get("signal") or "none")),
        },
        "projection_layer": "projection_candidates",
    }
    return tech


def _risk_report_bundle(fund: dict[str, Any]) -> dict[str, Any]:
    risk = dict(fund.get("risk_summary") or {})
    if not risk:
        return {}
    corr = dict(risk.get("correlation") or {})
    dd = dict(risk.get("drawdown_profile") or {})
    risk["render_hints"] = {
        "risk_particle_threshold": 1.0,
        "depth_field_by_var95": float(risk.get("var_95_1d") or 0.0),
        "liquidity_tag": str(risk.get("liquidity_tag") or "normal"),
        "correlation_heat": {
            "hs300": float(corr.get("hs300") or 0.0),
            "nasdaq100": float(corr.get("nasdaq100") or 0.0),
        },
        "recovery_profile": {
            "events": int(dd.get("events") or 0),
            "avg_recovery_days": dd.get("avg_recovery_days"),
        },
    }
    fund_risk = float(fund.get("risk_rating") or 3)
    dd = float(fund.get("max_drawdown_3y") or 0.0)
    vol = float(fund.get("volatility_60d") or 0.0)
    var95 = float(risk.get("var_95_1d") or 0.0)
    conc = float(risk.get("concentration") or fund.get("stock_top10_concentration") or 0.0)
    corr_hs300 = float((corr.get("hs300") or 0.0))
    liq_tag = str(risk.get("liquidity_tag") or "normal")
    liq_penalty = 0.45 if liq_tag == "high_crush_risk" else (0.2 if liq_tag == "medium_crush_risk" else 0.0)
    base_penalty = (
        0.7 * fund_risk
        + 4.0 * dd
        + 2.5 * vol
        + 3.2 * var95
        + 0.9 * conc
        + liq_penalty
        + 0.4 * max(0.0, corr_hs300)
    )
    news_black = float(risk.get("news_black_swan_score") or 0.0)
    news_policy = float(risk.get("news_policy_score") or 0.0)
    news_penalty = 0.55 * news_black + 0.12 * news_policy
    news_ratio = news_penalty / (base_penalty + news_penalty) if (base_penalty + news_penalty) > 1e-9 else 0.0
    risk["news_aux"] = {
        "black_swan_score": news_black,
        "policy_signal_score": news_policy,
        "penalty": float(news_penalty),
        "base_penalty": float(base_penalty),
        "contribution_ratio": float(max(0.0, min(1.0, news_ratio))),
        "note": "news_is_aux_factor",
    }
    return risk


def _clip01(v: float) -> float:
    return float(max(0.0, min(1.0, v)))


def _build_performance_style_attribution(fund: dict[str, Any]) -> dict[str, Any]:
    """
    业绩与风格归因（轻量规则版）：
    - 超额收益来源：选股、风格Beta、风格择时、风险控制（归一贡献）
    - 风格相似度/偏离度：大盘/小盘、价值/成长、质量
    """
    mom60 = float(fund.get("momentum_60d") or 0.0)
    sharpe = float(fund.get("sharpe_3y") or 0.0)
    mdd = float(fund.get("max_drawdown_3y") or 0.0)
    vol = float(fund.get("volatility_60d") or 0.0)
    mgr = float(fund.get("manager_score") or 0.0)
    aum = float(fund.get("aum_billion") or 0.0)
    top10 = float(fund.get("stock_top10_concentration") or 0.0)
    drift = float(fund.get("holding_drift") or 0.0)
    eq = float(fund.get("stock_equity_ratio") or 0.0)
    track = str(fund.get("track") or "")

    large_kw = any(k in track for k in ["沪深300", "中证100", "上证50", "大盘", "红利"])
    small_kw = any(k in track for k in ["中证1000", "中证500", "中小盘", "创业板", "科创"])
    value_kw = any(k in track for k in ["价值", "红利", "低波", "央企"])
    growth_kw = any(k in track for k in ["成长", "科技", "医药", "创新", "AI", "新能源"])
    quality_kw = any(k in track for k in ["质量", "龙头", "核心", "稳健"])

    large_sim = _clip01(0.62 + (0.22 if large_kw else 0.0) + (0.08 if aum >= 120 else 0.0) - (0.08 if vol >= 0.25 else 0.0))
    small_sim = _clip01(0.38 + (0.28 if small_kw else 0.0) + (0.08 if vol >= 0.25 else 0.0) - (0.08 if aum >= 120 else 0.0))
    value_sim = _clip01(0.48 + (0.24 if value_kw else 0.0) + (0.10 if mom60 <= 0.03 else 0.0) - (0.08 if drift >= 0.2 else 0.0))
    growth_sim = _clip01(0.52 + (0.24 if growth_kw else 0.0) + (0.10 if mom60 >= 0.08 else 0.0) - (0.08 if mdd >= 0.2 else 0.0))
    quality_sim = _clip01(0.5 + (0.2 if quality_kw else 0.0) + (0.08 if sharpe >= 1.0 else 0.0) + (0.06 if mdd <= 0.15 else 0.0))

    def _dev(x: float) -> float:
        return _clip01(abs(x - 0.5) * 2.0)

    style_similarity = {
        "large_cap": large_sim,
        "small_cap": small_sim,
        "value": value_sim,
        "growth": growth_sim,
        "quality": quality_sim,
    }
    style_deviation = {k: _dev(v) for k, v in style_similarity.items()}

    raw_sources = {
        "stock_selection_alpha": _clip01(0.45 + 0.35 * mgr + 0.08 * max(0.0, sharpe - 0.8)),
        "style_beta_premium": _clip01(0.4 + 0.3 * eq + 0.2 * max(0.0, top10 - 0.35)),
        "style_timing": _clip01(0.35 + 0.25 * max(0.0, mom60) + 0.15 * max(0.0, 0.22 - drift)),
        "risk_control": _clip01(0.35 + 0.25 * max(0.0, 0.22 - mdd) + 0.15 * max(0.0, 0.2 - vol)),
    }
    total = sum(raw_sources.values()) or 1.0
    src = {k: float(v / total) for k, v in raw_sources.items()}

    excess_proxy = mom60 + 0.15 * sharpe - 0.7 * mdd
    return {
        "excess_return_proxy": float(excess_proxy),
        "attribution_sources": src,
        "style_similarity": style_similarity,
        "style_deviation": style_deviation,
        "note": "rule_based_attribution_proxy",
    }


def _append_live_quote_as_t0(nav_rows: list[dict[str, Any]], live: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not live:
        return nav_rows
    gsz = live.get("gsz")
    gztime = str(live.get("gztime") or "").strip()
    if gsz is None or not gztime:
        return nav_rows
    day = gztime[:10]
    try:
        nav = float(gsz)
    except Exception:
        return nav_rows
    if not nav_rows:
        return [{"date": day, "nav": nav, "daily_return": 0.0, "daily_pct_display": "0.00%"}]
    if str(nav_rows[-1].get("date") or "") == day:
        prev_nav = float(nav_rows[-2].get("nav") or nav_rows[-1].get("nav") or nav) if len(nav_rows) >= 2 else nav
        ret = (nav / prev_nav - 1.0) if prev_nav > 0 else 0.0
        nav_rows[-1] = {
            "date": day,
            "nav": nav,
            "daily_return": float(ret),
            "daily_pct_display": f"{float(ret) * 100:.2f}%",
        }
        return nav_rows
    prev_nav = float(nav_rows[-1].get("nav") or nav)
    ret = (nav / prev_nav - 1.0) if prev_nav > 0 else 0.0
    return nav_rows + [{"date": day, "nav": nav, "daily_return": float(ret), "daily_pct_display": f"{float(ret) * 100:.2f}%"}]


def _data_not_ready_reason(agent_key: str, missing_fields: list[str]) -> str:
    missing = ",".join(missing_fields) if missing_fields else "unknown"
    return (
        f'{{"error":"数据源未就绪","code":"data_not_ready","agent":"{agent_key}","score":0,'
        f'"missing_fields":"{missing}"}}'
    )


def _missing_fields_for_agent(agent_key: str, fund: dict[str, Any], state: MAFBState) -> list[str]:
    nav_len = int(fund.get("nav_points_lookback") or 0)
    miss: list[str] = []

    if agent_key == "fundamental":
        # 基本面允许 ETF/指数基金缺失经理与持仓维度；核心统计项命中 1 项即可运行
        core_keys = [
            "max_drawdown_3y",
            "sharpe_3y",
            "momentum_60d",
            "volatility_60d",
            "stock_top10_concentration",
            "manager_score",
        ]
        valid = 0
        for k in core_keys:
            v = fund.get(k)
            if isinstance(v, (int, float)) and float(v) != 0.0:
                valid += 1
        if valid < 1:
            miss.append("fundamental_core_features")
        return miss

    if agent_key == "technical":
        if nav_len < 20:
            miss.append("nav_history_20d")
        if fund.get("technical_summary") is None:
            if fund.get("momentum_60d") is None and fund.get("volatility_60d") is None:
                miss.append("technical_summary_or_momentum_volatility")
        return miss

    if agent_key == "risk":
        if fund.get("risk_rating") is None:
            miss.append("risk_rating")
        risk_sum = fund.get("risk_summary") or {}
        if not risk_sum:
            miss.append("risk_summary")
        else:
            if not bool(risk_sum.get("data_ready")):
                miss.append("risk_data_gate_not_ready")
            if risk_sum.get("var_95_1d") is None:
                miss.append("var_95_1d")
            if risk_sum.get("sortino_ratio") is None and fund.get("volatility_60d") is None:
                miss.append("sortino_or_volatility")
        return miss

    if agent_key == "profiling":
        if fund.get("risk_rating") is None:
            miss.append("risk_rating")
        profile = state.get("user_profile") or {}
        if not profile:
            miss.append("user_profile")
        return miss

    if agent_key == "attribution":
        if nav_len < 40:
            miss.append("nav_history_40d")
        if fund.get("performance_style_attribution") is None:
            miss.append("performance_style_attribution")
        return miss
    return miss


def node_user_profiling(state: MAFBState) -> dict[str, Any]:
    include = bool(state.get("include_fbti", True))
    profile = build_user_profile_mafb(
        include,
        state.get("fbti_profile"),
        state.get("risk_preference"),
    )
    note = (
        "MAFB 用户画像：已纳入账户 FBTI 与风险偏好（不含八字五行流年）。"
        if include
        else "MAFB 用户画像：未纳入 FBTI，风险档位仅来自账户风险偏好（演示）。"
    )
    return {
        "user_profile": profile,
        "risk_level": int(profile["risk_level"]),
        "compliance_notes": [note],
    }


def node_data_preheat(state: MAFBState) -> dict[str, Any]:
    code = (state.get("fund_code") or "510300").strip()
    fund = get_fund_by_code(code, include_live=False)
    if not fund:
        code = "510300"
        fund = get_fund_by_code(code, include_live=False) or {}
    fund = dict(fund or {})
    # eastmoney_full 目录里若为 0，通常是占位而非真实值；先归空，避免被当成有效硬事实。
    for k in (
        "aum_billion",
        "manager_score",
        "manager_return_annual",
        "stock_top10_concentration",
        "stock_top5_concentration",
        "stock_equity_ratio",
    ):
        v0 = fund.get(k)
        if isinstance(v0, (int, float)) and float(v0) == 0.0:
            fund[k] = None
    # TOP10/持仓字段不再信任 eastmoney_full 目录值，统一由 akshare/snapshot 回填。
    if (settings.fund_catalog_mode or "").strip().lower() == "eastmoney_full":
        fund["stock_top10_concentration"] = None
        fund["stock_top5_concentration"] = None
        fund["stock_equity_ratio"] = None
        fund["top_holdings"] = []
    catalog_snapshot = dict(fund)
    computed_keys: set[str] = set()
    snap = get_latest_fund_snapshot_cached(code)
    if snap:
        for k, v in snap.items():
            if fund.get(k) is None or (isinstance(fund.get(k), (int, float)) and float(fund.get(k) or 0.0) == 0.0):
                fund[k] = v
        emit_agent_event(
            "snapshot_hit",
            f"命中基金日快照：code={code}, nav_points={int(snap.get('nav_points_lookback') or 0)}",
        )
    else:
        emit_agent_event("snapshot_miss", f"未命中基金日快照：code={code}")

    emit_agent_event("preheat_step", f"并行预热启动：code={code}")
    technical_dtw_rows: list[dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=3) as pool:
        fut_nav = pool.submit(fetch_fund_nav_history, code, 260, 8.0)
        fut_fundamental = pool.submit(fetch_fund_fundamental_snapshot, code)
        fut_live = pool.submit(fetch_fund_live_quote, code, 6.0)

        try:
            nav_rows = fut_nav.result()
        except Exception:
            nav_rows = []
        emit_agent_event("preheat_step", f"净值序列拉取完成：points={len(nav_rows)}")

        try:
            fundamental_snap = fut_fundamental.result()
        except Exception as e:
            err_cls = type(e).__name__
            err_msg = str(e).strip() or "unknown_error"
            err_low = err_msg.lower()
            if "timeout" in err_low:
                err_hint = "timeout"
            elif "schema" in err_low or "column" in err_low or "keyerror" in err_low:
                err_hint = "schema_error"
            else:
                err_hint = "runtime_error"
            err_detail = f"{err_cls}:{err_msg}"[:240]
            emit_agent_event(
                "fundamental_fetch_error",
                f"基本面快照异常：hint={err_hint}, detail={err_detail}",
            )
            fundamental_snap = {
                "source_notes": [
                    "fundamental_fetch_failed",
                    f"fundamental_fetch_error_hint={err_hint}",
                    f"fundamental_fetch_error={err_detail}",
                ],
                "fundamental_context_chunks": [],
            }
        emit_agent_event("preheat_step", f"基本面快照完成：code={code}")

        emit_agent_event("preheat_step", "技术指标快照采用轻量计算（不再依赖K线相似链路）")

        try:
            live = fut_live.result()
        except Exception:
            live = None
        emit_agent_event("preheat_step", f"实时估值拉取完成：live_quote={'yes' if live else 'no'}")

    if len(nav_rows) < 20:
        # 二次拉取更长窗口，降低接口偶发空窗对技术面链路的影响
        emit_agent_event("preheat_step", f"净值点位不足，重试拉取：code={code}, days=360")
        nav_rows = fetch_fund_nav_history(code, days=360, timeout=10.0)
        emit_agent_event("preheat_retry", f"nav_history retry for {code}: points={len(nav_rows)}")
    nav_vals = [float(r.get("nav") or 0.0) for r in nav_rows if r.get("nav") is not None]
    rets = [float(r.get("daily_return") or 0.0) for r in nav_rows if r.get("daily_return") is not None]

    if nav_rows:
        fund["nav_points_lookback"] = len(nav_rows)
        computed_keys.add("nav_points_lookback")
        if len(nav_rows) >= 12:
            lb = min(60, len(nav_rows) - 1)
            nav_now = float(nav_rows[-1].get("nav") or 0.0)
            nav_ref = float(nav_rows[-(lb + 1)].get("nav") or 0.0)
            if nav_ref > 0:
                fund["momentum_60d"] = (nav_now / nav_ref) - 1.0
                computed_keys.add("momentum_60d")
        sharpe = _calc_sharpe_from_returns(rets)
        if sharpe is not None:
            fund["sharpe_3y"] = sharpe
            computed_keys.add("sharpe_3y")
        mdd = _calc_max_drawdown(nav_vals)
        if mdd is not None:
            fund["max_drawdown_3y"] = mdd
            computed_keys.add("max_drawdown_3y")
        vol = _calc_volatility_from_returns(rets if len(rets) >= 20 else rets[-12:])
        if vol is not None:
            fund["volatility_60d"] = vol
            computed_keys.add("volatility_60d")
        if len(nav_vals) >= 35:
            ema5 = _ema_series(nav_vals, 5)[-1]
            ema20 = _ema_series(nav_vals, 20)[-1]
            ema60 = _ema_series(nav_vals, 60)[-1] if len(nav_vals) >= 60 else _ema_series(nav_vals, max(24, len(nav_vals) // 2))[-1]
            fund["ema_5"] = float(ema5)
            fund["ema_20"] = float(ema20)
            fund["ema_60"] = float(ema60)
            computed_keys.update({"ema_5", "ema_20", "ema_60"})
            if ema20:
                fund["bias_20"] = float((float(nav_vals[-1]) - ema20) / ema20)
                computed_keys.add("bias_20")
            rsi14 = _calc_rsi(nav_vals, 14)
            if rsi14 is not None:
                fund["rsi_14"] = float(rsi14)
                computed_keys.add("rsi_14")
            macd = _calc_macd_snapshot(nav_vals)
            if macd:
                fund["macd_dif"] = float(macd.get("dif") or 0.0)
                fund["macd_dea"] = float(macd.get("dea") or 0.0)
                fund["macd_hist"] = float(macd.get("hist") or 0.0)
                fund["macd_signal"] = str(macd.get("signal") or "none")
                computed_keys.update({"macd_dif", "macd_dea", "macd_hist", "macd_signal"})

    tech_summary = _build_technical_summary(fund, nav_vals, technical_dtw_rows)
    if tech_summary:
        fund["technical_summary"] = tech_summary
        computed_keys.add("technical_summary")
        emit_agent_event(
            "technical_snapshot",
            "技术面结构化快照已生成",
            trend=str((tech_summary.get("trend") or "")),
            rsi=float(((tech_summary.get("momentum") or {}).get("rsi") or 0.0)),
            dtw_top_score=float((((tech_summary.get("pattern_recognition") or {}).get("similarity_match") or {}).get("score") or 0.0)),
        )

    if live:
        fund["live_quote"] = live
        if not fund.get("name"):
            fund["name"] = str(live.get("name") or fund.get("name") or "")
        nav_rows = _append_live_quote_as_t0(nav_rows, live)
        nav_vals = [float(r.get("nav") or 0.0) for r in nav_rows if r.get("nav") is not None]
        rets = [float(r.get("daily_return") or 0.0) for r in nav_rows if r.get("daily_return") is not None]
        fund["nav_points_lookback"] = len(nav_rows)
    nav_rows_for_technical = [
        {
            "date": str(r.get("date") or "")[:10],
            "nav": float(r.get("nav") or 0.0),
            "daily_return": float(r.get("daily_return") or 0.0),
        }
        for r in nav_rows
        if r.get("date") is not None and r.get("nav") is not None
    ][-420:]

    # Only merge non-empty fundamental fields; keep snapshot/preheat values when akshare times out.
    if fundamental_snap:
        merged_notes = list(fund.get("source_notes") or [])
        for k, v in (fundamental_snap or {}).items():
            if k == "source_notes":
                for n in list(v or []):
                    s = str(n)
                    if s and s not in merged_notes:
                        merged_notes.append(s)
                continue
            if k == "fundamental_context_chunks":
                old_chunks = list(fund.get("fundamental_context_chunks") or [])
                for c in list(v or []):
                    cs = str(c)
                    if cs and cs not in old_chunks:
                        old_chunks.append(cs)
                if old_chunks:
                    fund["fundamental_context_chunks"] = old_chunks
                continue
            if v is None:
                continue
            if isinstance(v, str) and not v.strip():
                continue
            if isinstance(v, list) and not v:
                continue
            fund[k] = v
        if merged_notes:
            fund["source_notes"] = merged_notes
    emit_agent_event("preheat_step", f"并行计算启动：news+risk_summary，code={code}")
    news: dict[str, Any]
    risk_summary: dict[str, Any]
    with ThreadPoolExecutor(max_workers=2) as pool2:
        fut_news = pool2.submit(fetch_news_signals_for_fund, fund, timeout=6.0)
        fut_risk = pool2.submit(_build_risk_summary, fund, nav_vals, rets, nav_rows)
        try:
            news = fut_news.result()
        except Exception:
            news = {
                "source": "cls_telegraph",
                "fetched_at": None,
                "keywords": [],
                "fundamental_news": [],
                "risk_alerts": [],
                "policy_signal_score": 0.0,
                "black_swan_score": 0.0,
                "note": "fetch_failed",
            }
        try:
            risk_summary = fut_risk.result()
        except Exception:
            risk_summary = {}
    emit_agent_event(
        "preheat_step",
        f"并行计算完成：news(f={len(list(news.get('fundamental_news') or []))},r={len(list(news.get('risk_alerts') or []))}),"
        f"risk_summary={'yes' if bool(risk_summary) else 'no'}",
    )
    fund["news_signals"] = news
    fn = list(news.get("fundamental_news") or [])
    ra = list(news.get("risk_alerts") or [])
    if fn or ra:
        emit_agent_event(
            "news_snapshot",
            f"舆情已注入：fundamental_news={len(fn)}, risk_alerts={len(ra)}",
            policy_signal=float(news.get("policy_signal_score") or 0.0),
            black_swan=float(news.get("black_swan_score") or 0.0),
        )
    else:
        emit_agent_event("news_snapshot", f"舆情为空：note={news.get('note')}")

    if risk_summary:
        risk_summary["news_black_swan_score"] = float(news.get("black_swan_score") or 0.0)
        risk_summary["news_policy_score"] = float(news.get("policy_signal_score") or 0.0)
        fund["risk_summary"] = risk_summary
        computed_keys.add("risk_summary")
        emit_agent_event(
            "risk_snapshot",
            "风控结构化快照已生成（含舆情辅因子）",
            var95=float(risk_summary.get("var_95_1d") or 0.0),
            sortino=float(risk_summary.get("sortino_ratio") or 0.0),
            liquidity=str(risk_summary.get("liquidity_tag") or ""),
            black_swan=float(risk_summary.get("news_black_swan_score") or 0.0),
        )
        fund_risk = float(fund.get("risk_rating") or 3)
        dd = float(fund.get("max_drawdown_3y") or 0.0)
        vol = float(fund.get("volatility_60d") or 0.0)
        var95 = float(risk_summary.get("var_95_1d") or 0.0)
        conc = float(risk_summary.get("concentration") or fund.get("stock_top10_concentration") or 0.0)
        corr_hs300 = float(((risk_summary.get("correlation") or {}).get("hs300") or 0.0))
        liq_tag = str(risk_summary.get("liquidity_tag") or "normal")
        liq_penalty = 0.45 if liq_tag == "high_crush_risk" else (0.2 if liq_tag == "medium_crush_risk" else 0.0)
        base_penalty = (
            0.7 * fund_risk
            + 4.0 * dd
            + 2.5 * vol
            + 3.2 * var95
            + 0.9 * conc
            + liq_penalty
            + 0.4 * max(0.0, corr_hs300)
        )
        news_penalty = 0.55 * float(risk_summary.get("news_black_swan_score") or 0.0) + 0.12 * float(
            risk_summary.get("news_policy_score") or 0.0
        )
        aux_ratio = news_penalty / (base_penalty + news_penalty) if (base_penalty + news_penalty) > 1e-9 else 0.0
        emit_agent_event(
            "risk_news_aux",
            "Risk 新闻辅助贡献已计算（仅辅助，不主导）",
            contribution_ratio=float(max(0.0, min(1.0, aux_ratio))),
            news_penalty=float(news_penalty),
            base_penalty=float(base_penalty),
        )

    perf_attr = _build_performance_style_attribution(fund)
    if perf_attr:
        fund["performance_style_attribution"] = perf_attr
        computed_keys.add("performance_style_attribution")
        emit_agent_event(
            "attribution_snapshot",
            "业绩与风格归因快照已生成",
            excess_return_proxy=float(perf_attr.get("excess_return_proxy") or 0.0),
        )

    missing_all = _missing_fields_for_agent("fundamental", fund, state)
    inspect_keys = [
        "aum_billion",
        "sharpe_3y",
        "momentum_60d",
        "rsi_14",
        "macd_hist",
        "volatility_60d",
        "risk_summary",
        "max_drawdown_3y",
        "nav_points_lookback",
    ]
    source_parts: list[str] = []
    for key in inspect_keys:
        val = fund.get(key)
        if val is None:
            source_parts.append(f"{key}=missing")
            continue
        if key in computed_keys:
            source_parts.append(f"{key}=preheat_computed({val})")
            continue
        raw = catalog_snapshot.get(key)
        if isinstance(raw, (int, float)) and float(raw) == 0.0:
            source_parts.append(f"{key}=catalog_placeholder({val})")
            continue
        source_parts.append(f"{key}=catalog_value({val})")
    emit_agent_event("preheat_source", f"关键字段来源：{'; '.join(source_parts)}")
    note = (
        f"数据预热完成：code={code}, nav_points={int(fund.get('nav_points_lookback') or 0)}, "
        f"live_quote={'yes' if live else 'no'}, "
        f"manager_score={fund.get('manager_score')}, top10={fund.get('stock_top10_concentration')}。"
    )
    if missing_all:
        note += f" 关键字段待补齐：{','.join(missing_all)}。"
    return {
        "fund_data": fund,
        "nav_rows_for_technical": nav_rows_for_technical,
        "fund_code": code,
        "compliance_notes": [note],
    }


def node_load_fund_and_rag(state: MAFBState) -> dict[str, Any]:
    code = (state.get("fund_code") or "510300").strip()
    fund = dict(state.get("fund_data") or {})
    if not fund:
        fund = get_fund_by_code(code, include_live=False) or {}
    if not fund:
        fund = get_fund_by_code("510300", include_live=False) or {}
    query = f"{code} {fund.get('name', '')} {fund.get('track', '')}"
    chunks, metas = retrieve_fund_context(query, top_k=4)
    ranked = rerank_by_profile(metas, state.get("user_profile") or {})
    boost = [f"{r.get('code')} {r.get('name')} | {r.get('doc', '')}" for r in ranked[:2]]
    fs_chunks = list(fund.get("fundamental_context_chunks") or [])
    merged_chunks = (list(chunks) + boost + fs_chunks)[:12]
    return {
        "fund_data": fund,
        "rag_chunks": merged_chunks,
        "compliance_notes": [f"RAG 检索命中 {len(chunks)} 条基金事实片段（FAISS）。"],
    }


def _fundamental_rule(state: MAFBState) -> dict[str, Any]:
    fund = state.get("fund_data") or {}
    sharpe = float(fund.get("sharpe_3y") or 0)
    dd = float(fund.get("max_drawdown_3y") or 0.3)
    aum = float(fund.get("aum_billion") or 1)
    mgr = float(fund.get("manager_score") or 0)
    top10 = float(fund.get("stock_top10_concentration") or 0)
    drift = float(fund.get("holding_drift") or 0)
    news = fund.get("news_signals") or {}
    policy_sig = float(news.get("policy_signal_score") or 0.0)
    black_swan = float(news.get("black_swan_score") or 0.0)
    # 新闻仅作辅助因子，不主导评分
    news_aux = policy_sig * 0.28 - black_swan * 0.22
    score = _clamp_score(
        sharpe * 2.4 - dd * 3.2 + min(aum / 400, 1) + mgr * 0.25 - top10 * 1.1 - drift * 0.7 + news_aux
    )
    level = "基本面稳健" if score >= 1 else ("基本面中性" if score >= 0 else "基本面偏弱")
    reason = (
        f"【核心结论】{level}；"
        f"【硬事实数据】3年夏普={sharpe:.2f}，最大回撤={dd:.1%}，规模={aum:.2f}亿，"
        f"经理评分={mgr:.2f}，前十大集中度={top10:.1%}，风格漂移={drift:.1%}，政策扰动分={policy_sig:.2f}；"
        "【逻辑推演】经理能力、规模稳定性与持仓集中/漂移是主导因子；新闻仅用于识别短期政策逻辑变动，"
        "作为辅助修正而非主导判断，历史统计不代表未来表现；"
        f"【基本面打分】{score}"
    )
    return {"agent_scores": {"fundamental": score}, "agent_reasons": {"fundamental": reason}}


def _technical_rule(state: MAFBState) -> dict[str, Any]:
    fund = state.get("fund_data") or {}
    mom = float(fund.get("momentum_60d") or 0.0)
    vol = float(fund.get("volatility_60d") or 0.0)
    bias20 = float(fund.get("bias_20") or 0.0)
    rsi14 = float(fund.get("rsi_14") or 50.0)
    macd_hist = float(fund.get("macd_hist") or 0.0)
    ema5 = float(fund.get("ema_5") or 0.0)
    ema20 = float(fund.get("ema_20") or 0.0)
    ema60 = float(fund.get("ema_60") or 0.0)
    trend_bonus = 0.45 if (ema5 > ema20 > ema60) else (-0.45 if (ema5 < ema20 < ema60) else 0.0)
    rsi_penalty = -0.35 if rsi14 >= 72 else (0.2 if rsi14 <= 30 else 0.0)
    bias_penalty = -0.3 if abs(bias20) > 0.05 else 0.0
    macd_term = 0.25 if macd_hist > 0 else (-0.2 if macd_hist < 0 else 0.0)
    score = _clamp_score(mom * 8.0 - vol * 2.2 + trend_bonus + rsi_penalty + bias_penalty + macd_term)
    level = "趋势偏强" if score >= 1 else ("趋势中性" if score >= 0 else "趋势偏弱")
    tech = fund.get("technical_summary") or {}
    dtw_best = ((tech.get("pattern_recognition") or {}).get("similarity_match") or {})
    dtw_score = float(dtw_best.get("score") or 0.0)
    dtw_out5 = dtw_best.get("historical_outcome_5d")
    dtw_out5_text = f"{float(dtw_out5):.2%}" if isinstance(dtw_out5, (int, float)) else "N/A"
    reason = (
        f"【核心结论】{level}；"
        f"【硬事实数据】EMA5/20/60={ema5:.4f}/{ema20:.4f}/{ema60:.4f}，Bias20={bias20:.2%}，"
        f"RSI14={rsi14:.1f}，MACD_hist={macd_hist:.4f}，DTW_top1={dtw_score:.2f}，历史后5日={dtw_out5_text}；"
        "【逻辑推演】均线结构提供趋势方向，RSI与Bias识别过热/超卖，MACD衡量动能变化，"
        "DTW相似片段用于历史形态概率参考（非预测）；"
        f"【技术面打分】{score}"
    )
    return {"agent_scores": {"technical": score}, "agent_reasons": {"technical": reason}}


def _risk_rule(state: MAFBState) -> dict[str, Any]:
    fund = state.get("fund_data") or {}
    fund_risk = int(fund.get("risk_rating") or 3)
    dd = float(fund.get("max_drawdown_3y") or 0.0)
    vol = float(fund.get("volatility_60d") or 0.0)
    risk_sum = fund.get("risk_summary") or {}
    var95 = float(risk_sum.get("var_95_1d") or 0.0)
    sortino = risk_sum.get("sortino_ratio")
    sortino_v = float(sortino) if isinstance(sortino, (int, float)) else 0.0
    conc = float(risk_sum.get("concentration") or fund.get("stock_top10_concentration") or 0.0)
    corr_hs300 = float(((risk_sum.get("correlation") or {}).get("hs300") or 0.0))
    liq_tag = str(risk_sum.get("liquidity_tag") or "normal")
    liq_penalty = 0.45 if liq_tag == "high_crush_risk" else (0.2 if liq_tag == "medium_crush_risk" else 0.0)
    news_black = float(risk_sum.get("news_black_swan_score") or 0.0)
    news_policy = float(risk_sum.get("news_policy_score") or 0.0)
    # 新闻只占辅因子，避免覆盖量化风险主逻辑
    news_penalty = 0.55 * news_black + 0.12 * news_policy
    score = _clamp_score(
        2.2
        - 0.7 * fund_risk
        - 4.0 * dd
        - 2.5 * vol
        - 3.2 * var95
        - 0.9 * conc
        - liq_penalty
        + 0.3 * sortino_v
        - 0.4 * max(0.0, corr_hs300)
        - news_penalty
    )
    level = "风险可控" if score >= 1 else ("风险中性" if score >= 0 else "风险偏高")
    rec = (risk_sum.get("drawdown_profile") or {}).get("avg_recovery_days")
    rec_text = f"{float(rec):.0f}天" if isinstance(rec, (int, float)) else "N/A"
    var_text = f"{var95:.2%}" if var95 > 0 else "N/A"
    reason = (
        f"【核心结论】{level}；"
        f"【硬事实数据】风险评级={fund_risk}，最大回撤={dd:.1%}，波动率={vol:.1%}，VaR95(1d)={var_text}，"
        f"Sortino={sortino_v:.2f}，集中度={conc:.1%}，相关性(沪深300)={corr_hs300:.2f}，平均修复={rec_text}，"
        f"黑天鹅舆情分={news_black:.2f}；"
        "【逻辑推演】回撤/波动刻画风险底座，VaR识别尾部损失，Sortino仅惩罚坏波动，"
        "集中度与流动性标签反映踩踏风险，相关性高时系统性冲击传导更强；舆情信号仅作风险放大器，"
        "不替代量化主指标；"
        f"【风险评分】{score}"
    )
    return {"agent_scores": {"risk": score}, "agent_reasons": {"risk": reason}}


def _collect_risk_warnings(fund: dict[str, Any], risk_score: int) -> list[str]:
    risk_sum = fund.get("risk_summary") or {}
    warnings: list[str] = []
    fund_risk = int(fund.get("risk_rating") or 3)
    dd = float(fund.get("max_drawdown_3y") or 0.0)
    var95 = float(risk_sum.get("var_95_1d") or 0.0)
    conc = float(risk_sum.get("concentration") or fund.get("stock_top10_concentration") or 0.0)
    liq_tag = str(risk_sum.get("liquidity_tag") or "normal")
    news_black = float(risk_sum.get("news_black_swan_score") or 0.0)

    if risk_score <= 0:
        warnings.append("风控评分偏弱，建议降低仓位并设置止损纪律。")
    if fund_risk >= 4:
        warnings.append(f"基金风险评级较高（{fund_risk}/5），波动承受要求更高。")
    if dd >= 0.2:
        warnings.append(f"历史最大回撤偏大（{dd:.1%}），需关注回撤容忍度。")
    if var95 >= 0.02:
        warnings.append(f"VaR95(1d) 偏高（{var95:.2%}），尾部风险不可忽视。")
    if conc >= 0.55:
        warnings.append(f"持仓集中度偏高（{conc:.1%}），单一行业/个股冲击放大。")
    if liq_tag == "high_crush_risk":
        warnings.append("流动性风险高，可能出现拥挤交易与踩踏。")
    elif liq_tag == "medium_crush_risk":
        warnings.append("流动性风险中等，建议控制仓位与分批执行。")
    if news_black >= 0.6:
        warnings.append(f"黑天鹅舆情信号较强（{news_black:.2f}），建议提高防御。")

    return warnings


def _rewrite_reason_for_compliance(text: str) -> str:
    s = str(text or "").strip()
    if not s:
        return s
    replacements = {
        "建议买入": "可作为历史观察样本",
        "建议卖出": "需结合风险承受能力审慎观察",
        "强势多头": "历史区间内动量偏强",
        "中性偏多": "历史信号偏中性至偏强",
        "看多": "偏强信号",
        "看空": "偏弱信号",
        "牛市": "历史上行阶段",
        "熊市": "历史下行阶段",
        "适配打分": "匹配度参考",
        "技术面打分": "技术面观察",
        "基本面打分": "基本面观察",
        "风险评分": "风险观察",
    }
    out = s
    for src, dst in replacements.items():
        out = out.replace(src, dst)
    if "过往业绩不代表未来表现" not in out:
        out = out + "；过往业绩不代表未来表现，基金有风险，投资需谨慎。"
    return out


def _rewrite_agent_reasons_for_compliance(reasons: dict[str, str]) -> dict[str, str]:
    out: dict[str, str] = {}
    for k, v in (reasons or {}).items():
        out[k] = _rewrite_reason_for_compliance(v)
    return out


def node_fundamental(state: MAFBState) -> dict[str, Any]:
    fund = state.get("fund_data") or {}
    emit_agent_event("fundamental_start", "Fundamental 节点启动")
    missing = _missing_fields_for_agent("fundamental", fund, state)
    if missing:
        emit_agent_event("fundamental_data_not_ready", f"Fundamental 数据未就绪：missing={','.join(missing)}")
        return {
            "agent_scores": {"fundamental": 0},
            "agent_reasons": {"fundamental": _data_not_ready_reason("fundamental", missing)},
        }
    llm = invoke_finance_agent_score(
        "fundamental",
        "基金基本面分析师（持仓集中度、经理能力、规模与风险收益效率）",
        fund,
        list(state.get("rag_chunks") or []),
        int(state.get("risk_level") or 3),
    )
    if llm:
        emit_agent_event("fundamental_done", f"Fundamental LLM 完成：score={llm.score}")
        return {
            "agent_scores": {"fundamental": llm.score},
            "agent_reasons": {"fundamental": llm.reason},
        }
    out = _fundamental_rule(state)
    emit_agent_event("fundamental_fallback", "Fundamental 走规则引擎完成")
    return out


def node_technical(state: MAFBState) -> dict[str, Any]:
    fund = state.get("fund_data") or {}
    code = str(fund.get("code") or state.get("fund_code") or "").strip()
    retrieval = retrieve_technical_matches(
        code,
        top_k=int(settings.technical_retrieval_top_k),
        nav_rows=list(state.get("nav_rows_for_technical") or []),
    )
    if retrieval.get("ok"):
        fund["technical_retrieval"] = retrieval
        emit_agent_event(
            "technical_retrieval_ready",
            f"Technical 检索完成：matches={len(list(retrieval.get('matches') or []))}",
        )
    else:
        emit_agent_event("technical_retrieval_miss", f"Technical 检索未就绪：error={retrieval.get('error')}")
        emit_agent_event("offline_data_missing", f"technical retrieval unavailable, fallback to pure technical factors: code={code}")
        fund["technical_retrieval"] = {}
    missing = _missing_fields_for_agent("technical", fund, state)
    if missing:
        return {
            "technical_retrieval": retrieval,
            "agent_scores": {"technical": 0},
            "agent_reasons": {"technical": _data_not_ready_reason("technical", missing)},
        }
    llm = invoke_finance_agent_score(
        "technical",
        "基金技术面形态策略专家（EMA/Bias/RSI/MACD + DTW 历史形态匹配）",
        fund,
        list(state.get("rag_chunks") or []),
        int(state.get("risk_level") or 3),
    )
    if llm:
        return {
            "technical_retrieval": retrieval,
            "agent_scores": {"technical": llm.score},
            "agent_reasons": {"technical": llm.reason},
        }
    out = _technical_rule({**state, "fund_data": fund})
    out["technical_retrieval"] = retrieval
    return out


def node_risk(state: MAFBState) -> dict[str, Any]:
    fund = state.get("fund_data") or {}
    missing = _missing_fields_for_agent("risk", fund, state)
    if missing:
        return {
            "agent_scores": {"risk": 0},
            "agent_reasons": {"risk": _data_not_ready_reason("risk", missing)},
            "compliance_notes": [f"风控告警：风险数据未完全就绪（{','.join(missing)}），以下结论请谨慎参考。"],
        }
    llm = invoke_finance_agent_score(
        "risk",
        "基金风险与用户画像匹配分析师",
        fund,
        list(state.get("rag_chunks") or []),
        int(state.get("risk_level") or 3),
    )
    if llm:
        warnings = _collect_risk_warnings(fund, llm.score)
        notes = [f"风控告警：{w}" for w in warnings]
        if warnings:
            emit_agent_event("risk_warning", f"风控触发 {len(warnings)} 条告警（结果照常输出）")
        return {
            "agent_scores": {"risk": llm.score},
            "agent_reasons": {"risk": llm.reason},
            "compliance_notes": notes,
        }
    out = _risk_rule(state)
    warnings = _collect_risk_warnings(fund, int((out.get("agent_scores") or {}).get("risk") or 0))
    if warnings:
        emit_agent_event("risk_warning", f"风控触发 {len(warnings)} 条告警（结果照常输出）")
    out["compliance_notes"] = [f"风控告警：{w}" for w in warnings]
    return out


def node_profiling(state: MAFBState) -> dict[str, Any]:
    fund = state.get("fund_data") or {}
    missing = _missing_fields_for_agent("profiling", fund, state)
    if missing:
        return {
            "agent_scores": {"profiling": 0},
            "agent_reasons": {"profiling": _data_not_ready_reason("profiling", missing)},
        }
    llm = invoke_finance_agent_score(
        "profiling",
        "画像匹配分析师（标的风格与用户画像适配评估）",
        fund,
        list(state.get("rag_chunks") or []),
        int(state.get("risk_level") or 3),
        user_profile=dict(state.get("user_profile") or {}),
    )
    if llm:
        return {
            "agent_scores": {"profiling": llm.score},
            "agent_reasons": {"profiling": llm.reason},
        }
    score, reason = _fbti_track_alignment_score(state)
    return {"agent_scores": {"profiling": score}, "agent_reasons": {"profiling": reason}}


def _attribution_rule(state: MAFBState) -> dict[str, Any]:
    fund = state.get("fund_data") or {}
    summary = dict(fund.get("performance_style_attribution") or {})
    if not summary:
        return {
            "agent_scores": {"attribution": 0},
            "agent_reasons": {"attribution": _data_not_ready_reason("attribution", ["performance_style_attribution"])},
        }
    excess = float(summary.get("excess_return_proxy") or 0.0)
    src = dict(summary.get("attribution_sources") or {})
    style = dict(summary.get("style_similarity") or {})
    dev = dict(summary.get("style_deviation") or {})
    score = _clamp_score(excess * 3.5 + 1.6 * float(src.get("risk_control") or 0.0) - 0.8 * float(dev.get("growth") or 0.0))
    level = "归因清晰" if score >= 1 else ("归因中性" if score >= 0 else "归因偏弱")
    reason = (
        f"【核心结论】{level}；"
        f"【硬事实数据】超额收益代理={excess:.2%}，选股贡献={float(src.get('stock_selection_alpha') or 0):.1%}，"
        f"风格Beta贡献={float(src.get('style_beta_premium') or 0):.1%}，风格择时={float(src.get('style_timing') or 0):.1%}，"
        f"风控贡献={float(src.get('risk_control') or 0):.1%}；"
        f"风格相似度[大盘={float(style.get('large_cap') or 0):.2f},小盘={float(style.get('small_cap') or 0):.2f},"
        f"价值={float(style.get('value') or 0):.2f},成长={float(style.get('growth') or 0):.2f},质量={float(style.get('quality') or 0):.2f}]；"
        "【逻辑推演】从收益、波动、回撤与持仓稳定性拆解超额收益来源，并用风格相似度/偏离度评估组合风格暴露；"
        f"【归因打分】{score}"
    )
    return {"agent_scores": {"attribution": score}, "agent_reasons": {"attribution": reason}}


def node_attribution(state: MAFBState) -> dict[str, Any]:
    fund = state.get("fund_data") or {}
    missing = _missing_fields_for_agent("attribution", fund, state)
    if missing:
        return {
            "agent_scores": {"attribution": 0},
            "agent_reasons": {"attribution": _data_not_ready_reason("attribution", missing)},
            "compliance_notes": ["业绩与风格归因：数据未就绪，已降级中性分。"],
        }
    # 归因链路优先稳定可复现：直接使用规则结果，避免模型口径抖动导致 data_not_ready 干扰。
    return _attribution_rule(state)


def node_asset_allocation(state: MAFBState) -> dict[str, Any]:
    return {
        "proposed_portfolio": [],
        "compliance_notes": ["单基金分析模式：已关闭组合草案输出。"],
    }


def node_compliance(state: MAFBState) -> dict[str, Any]:
    reasons = state.get("agent_reasons") or {}
    text_blob = " ".join(reasons.values())
    notes: list[str] = []
    needs_rewrite = False

    for word in _FORBIDDEN:
        if word in text_blob:
            notes.append(f"合规提示：命中敏感词（{word}），请人工复核表达。")
            needs_rewrite = True

    fund = state.get("fund_data") or {}
    user_risk = int(state.get("risk_level") or 3)
    fund_risk = int(fund.get("risk_rating") or 3)
    if fund_risk - user_risk >= 3:
        notes.append("风控警告：基金风险等级显著高于用户画像可承受范围（继续输出，但请谨慎）。")

    scores = state.get("agent_scores") or {}
    raw_total = sum(scores.values())
    if raw_total <= -4:
        notes.append("风控警告：多智能体综合打分偏低（继续输出，仅供参考）。")

    llm = invoke_compliance_llm(text_blob, str(fund.get("code", "")))
    if llm:
        notes.append(f"大模型合规审查：compliance_score={llm.compliance_score}。")
        if llm.advisory_notes:
            notes.append(llm.advisory_notes[:500])
        if (not llm.allow_continue) or int(llm.compliance_score) < 0:
            notes.append("合规提示：大模型建议谨慎发布（当前为非拦截模式，结果继续输出）。")
            needs_rewrite = True

    if needs_rewrite:
        notes.append("合规编辑：仅对最终单基金分析输出执行术语中性化改写（中间流程保持原文）。")

    notes.append("合规审查：已完成禁宣词检测与风险等级错配检测（非拦截模式）。")
    return {
        "is_compliant": True,
        "blocked_reason": "",
        "compliance_notes": notes,
        "compliance_rewrite_needed": needs_rewrite,
    }


def node_voting(state: MAFBState) -> dict[str, Any]:
    scores = dict(state.get("agent_scores") or {})

    weighted = 0.0
    detail: dict[str, Any] = {}
    for key, weight in _WEIGHTS.items():
        s = float(scores.get(key, 0))
        weighted += s * weight
        detail[key] = {"score": scores.get(key, 0), "weight": weight}

    user_profile = state.get("user_profile") or {}
    disclaimer = (
        "本输出仅供教学演示，不构成投资建议。基金有风险，投资需谨慎。"
        " 历史业绩不预示未来表现。"
    )

    anchor = state.get("fund_data") or {}
    chain = build_reasoning_chain()
    position = build_position_advice_mafb(user_profile)
    reasons = state.get("agent_reasons") or {}
    rewrite_needed = bool(state.get("compliance_rewrite_needed"))
    single_fund_analysis = (
        "【单基金综合结论】\n"
        f"- 基本面：{str(reasons.get('fundamental') or '暂无')}\n"
        f"- 技术面：{str(reasons.get('technical') or '暂无')}\n"
        f"- 风控：{str(reasons.get('risk') or '暂无')}\n"
        f"- 业绩与风格归因：{str(reasons.get('attribution') or '暂无')}\n"
        f"- 画像匹配：{str(reasons.get('profiling') or '暂无')}\n"
        "【说明】以上由各子智能体（含大模型通道）并行结论聚合，不构成投资建议。"
    )
    if rewrite_needed:
        single_fund_analysis = _rewrite_reason_for_compliance(single_fund_analysis)

    final_report = {
        "verdict": "pass",
        "weighted_total": round(weighted, 3),
        "scores": scores,
        "score_breakdown": detail,
        "user_profile": user_profile,
        "fund": anchor,
        "rag_chunks": state.get("rag_chunks"),
        "proposed_portfolio": [],
        "performance_style_attribution": anchor.get("performance_style_attribution") or {},
        "top5_recommendations": [],
        "reasoning_chain": chain,
        "position_advice": position,
        "reasons": reasons,
        "single_fund_analysis": single_fund_analysis,
        "technical_summary": _technical_report_bundle(anchor),
        "technical_retrieval": state.get("technical_retrieval") or {},
        "risk_summary": _risk_report_bundle(anchor),
        "compliance": {
            "is_compliant": state.get("is_compliant"),
            "blocked_reason": state.get("blocked_reason"),
            "notes": state.get("compliance_notes"),
        },
        "disclaimer": disclaimer,
    }

    final_report["summary"] = (
        f"多智能体加权总分 {weighted:.2f}；已输出技术面结构化快照与业绩/风格归因（超额收益来源与风格偏离度）。"
    )

    return {"final_report": final_report, "weighted_total": round(weighted, 3)}


def route_after_compliance(state: MAFBState) -> str:
    return "voting" if state.get("is_compliant") else "blocked"


def node_blocked(state: MAFBState) -> dict[str, Any]:
    disclaimer = (
        "本输出仅供教学演示，不构成投资建议。基金有风险，投资需谨慎。"
    )
    user_profile = state.get("user_profile") or {}
    anchor = state.get("fund_data") or {}
    report = {
        "verdict": "blocked",
        "weighted_total": sum((state.get("agent_scores") or {}).values()),
        "scores": state.get("agent_scores"),
        "reasons": state.get("agent_reasons"),
        "user_profile": user_profile,
        "fund": anchor,
        "rag_chunks": state.get("rag_chunks"),
        "top5_recommendations": [],
        "performance_style_attribution": anchor.get("performance_style_attribution") or {},
        "reasoning_chain": build_reasoning_chain(),
        "position_advice": build_position_advice_mafb(user_profile) if user_profile else {},
        "technical_summary": _technical_report_bundle(anchor),
        "technical_retrieval": state.get("technical_retrieval") or {},
        "risk_summary": _risk_report_bundle(anchor),
        "single_fund_analysis": (
            "【单基金综合结论】\n"
            "当前结果被合规拦截，已暂停对外输出建议性结论。"
        ),
        "compliance": {
            "is_compliant": False,
            "blocked_reason": state.get("blocked_reason"),
            "notes": state.get("compliance_notes"),
        },
        "proposed_portfolio": [],
        "summary": f"合规拦截：{state.get('blocked_reason')}",
        "disclaimer": disclaimer,
    }
    return {"final_report": report}


def route_parallel_analysts(state: MAFBState):
    """第一阶段并行：基本面 / 技术面 / 风控 / 业绩风格归因 / 画像匹配 五路并行。"""
    try:
        from langgraph.types import Send
    except ModuleNotFoundError:
        from langgraph.constants import Send

    return [
        Send("fundamental", state),
        Send("technical", state),
        Send("risk", state),
        Send("attribution", state),
        Send("profiling", state),
    ]
