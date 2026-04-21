from __future__ import annotations

import math
from typing import Any

from app.agent.fund_catalog import get_fund_by_code
from app.agent.fund_similarity import find_similar_kline_funds
from app.agent.llm_client import invoke_compliance_llm, invoke_finance_agent_score
from app.agent.profiling_mafb import build_user_profile_mafb
from app.agent.rag_faiss import rerank_by_profile, retrieve_fund_context
from app.agent.state import MAFBState
from app.agent.top5 import (
    build_position_advice_mafb,
    build_reasoning_chain,
)
from app.services.fund_data import fetch_fund_live_quote, fetch_fund_nav_history
from app.services.similar_funds import similar_funds

_FORBIDDEN = ("保证收益", "稳赚", "无风险", "内幕", "必涨", "只赚不赔")
_WEIGHTS = {
    "fundamental": 0.22,
    "technical": 0.22,
    "risk": 0.20,
    "kline": 0.18,
    "profiling": 0.12,
    "allocation": 0.06,
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


def _build_similarity_top5(anchor: dict[str, Any], kline_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """主表：K 线相似 TOP5，并并入演示池「统计特征余弦」相似度（与 /agent/funds/similar 同源）。"""
    code = str(anchor.get("code") or "").strip()
    if not code:
        return []
    feat_rows = similar_funds(code, top_k=40)
    feat_map = {str(r["code"]): r for r in feat_rows}
    if kline_rows:
        out: list[dict[str, Any]] = []
        for i, kr in enumerate(kline_rows[:5], start=1):
            fc = str(kr.get("code") or "")
            fr = feat_map.get(fc)
            out.append(
                {
                    "rank": i,
                    "code": kr.get("code"),
                    "name": kr.get("name"),
                    "track": kr.get("track"),
                    "kline_similarity": kr.get("similarity"),
                    "kline_method": kr.get("method"),
                    "kline_window_days": kr.get("window_days"),
                    "kline_rationale": kr.get("rationale"),
                    "feature_similarity": (fr or {}).get("similarity"),
                    "feature_rationale": (fr or {}).get("rationale"),
                }
            )
        return out
    return [
        {
            "rank": i,
            "code": r.get("code"),
            "name": r.get("name"),
            "track": r.get("track"),
            "kline_similarity": None,
            "kline_method": None,
            "kline_window_days": None,
            "kline_rationale": "主基金净值序列过短，K 线相似为空；下列为统计特征相似 TOP5。",
            "feature_similarity": r.get("similarity"),
            "feature_rationale": r.get("rationale"),
        }
        for i, r in enumerate(feat_rows[:5], start=1)
    ]


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


def _data_not_ready_reason(agent_key: str, missing_fields: list[str]) -> str:
    missing = ",".join(missing_fields) if missing_fields else "unknown"
    return (
        f'{{"error":"数据源未就绪","agent":"{agent_key}","score":0,'
        f'"missing_fields":"{missing}"}}'
    )


def _missing_fields_for_agent(agent_key: str, fund: dict[str, Any], state: MAFBState) -> list[str]:
    nav_len = int(fund.get("nav_points_lookback") or 0)
    required: dict[str, list[str]] = {
        "fundamental": ["aum_billion", "sharpe_3y", "max_drawdown_3y"],
        "technical": ["momentum_60d", "volatility_60d"],
        "risk": ["risk_rating", "max_drawdown_3y", "volatility_60d"],
        "kline": ["kline_seed_similarity"],
        "profiling": ["risk_rating"],
    }
    miss: list[str] = []
    for k in required.get(agent_key, []):
        val = fund.get(k)
        if val is None:
            miss.append(k)
            continue
        if isinstance(val, (int, float)) and k != "risk_rating" and float(val) == 0.0:
            miss.append(k)
    if agent_key == "kline" and nav_len < 40:
        miss.append("nav_history_40d")
    if agent_key == "profiling":
        profile = state.get("user_profile") or {}
        if not profile:
            miss.append("user_profile")
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

    nav_rows = fetch_fund_nav_history(code, days=200, timeout=8.0)
    nav_vals = [float(r.get("nav") or 0.0) for r in nav_rows if r.get("nav") is not None]
    rets = [float(r.get("daily_return") or 0.0) for r in nav_rows if r.get("daily_return") is not None]

    if nav_rows:
        fund["nav_points_lookback"] = len(nav_rows)
        if len(nav_rows) >= 61:
            nav_now = float(nav_rows[-1].get("nav") or 0.0)
            nav_60 = float(nav_rows[-61].get("nav") or 0.0)
            if nav_60 > 0:
                fund["momentum_60d"] = (nav_now / nav_60) - 1.0
        sharpe = _calc_sharpe_from_returns(rets)
        if sharpe is not None:
            fund["sharpe_3y"] = sharpe
        mdd = _calc_max_drawdown(nav_vals)
        if mdd is not None:
            fund["max_drawdown_3y"] = mdd
        vol = _calc_volatility_from_returns(rets)
        if vol is not None:
            fund["volatility_60d"] = vol

    live = fetch_fund_live_quote(code, timeout=6.0)
    if live:
        fund["live_quote"] = live
        if not fund.get("name"):
            fund["name"] = str(live.get("name") or fund.get("name") or "")

    missing_all = _missing_fields_for_agent("fundamental", fund, state)
    note = (
        f"数据预热完成：code={code}, nav_points={int(fund.get('nav_points_lookback') or 0)}, "
        f"live_quote={'yes' if live else 'no'}。"
    )
    if missing_all:
        note += f" 关键字段待补齐：{','.join(missing_all)}。"
    return {
        "fund_data": fund,
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
    merged_chunks = (list(chunks) + boost)[:8]
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
    score = _clamp_score(sharpe * 3 - dd * 4 + min(aum / 400, 1))
    level = "基本面稳健" if score >= 1 else ("基本面中性" if score >= 0 else "基本面偏弱")
    reason = (
        f"【核心结论】{level}；"
        f"【硬事实数据】3年夏普={sharpe:.2f}，最大回撤={dd:.1%}，规模={aum:.2f}亿；"
        "【逻辑推演】风险收益效率与回撤控制共同决定资产质量，历史统计不代表未来表现；"
        f"【基本面打分】{score}"
    )
    return {"agent_scores": {"fundamental": score}, "agent_reasons": {"fundamental": reason}}


def _technical_rule(state: MAFBState) -> dict[str, Any]:
    fund = state.get("fund_data") or {}
    mom = float(fund.get("momentum_60d") or 0)
    score = _clamp_score(mom * 12)
    level = "趋势改善" if score >= 1 else ("趋势震荡" if score >= 0 else "趋势偏弱")
    reason = (
        f"【核心结论】{level}；"
        f"【硬事实数据】60日动量={mom:.2%}；"
        "【逻辑推演】动量刻画趋势惯性，当前信号仅反映历史路径特征，不构成收益承诺；"
        f"【技术面打分】{score}"
    )
    return {"agent_scores": {"technical": score}, "agent_reasons": {"technical": reason}}


def _risk_rule(state: MAFBState) -> dict[str, Any]:
    fund = state.get("fund_data") or {}
    fund_risk = int(fund.get("risk_rating") or 3)
    dd = float(fund.get("max_drawdown_3y") or 0.0)
    vol = float(fund.get("volatility_60d") or 0.0)
    score = _clamp_score(2.2 - 0.7 * fund_risk - 4.0 * dd - 2.5 * vol)
    level = "风险可控" if score >= 1 else ("风险中性" if score >= 0 else "风险偏高")
    reason = (
        f"【核心结论】{level}；"
        f"【硬事实数据】标的风险评级={fund_risk}，最大回撤={dd:.1%}，波动率={vol:.1%}；"
        "【逻辑推演】风险评级、回撤和波动共同刻画标的在极端行情下的防御上限，属于历史风险画像；"
        f"【风险评分】{score}"
    )
    return {"agent_scores": {"risk": score}, "agent_reasons": {"risk": reason}}


def node_fundamental(state: MAFBState) -> dict[str, Any]:
    fund = state.get("fund_data") or {}
    missing = _missing_fields_for_agent("fundamental", fund, state)
    if missing:
        return {
            "agent_scores": {"fundamental": 0},
            "agent_reasons": {"fundamental": _data_not_ready_reason("fundamental", missing)},
        }
    llm = invoke_finance_agent_score(
        "fundamental",
        "基金基本面分析师（规模、夏普、回撤等历史统计）",
        fund,
        list(state.get("rag_chunks") or []),
        int(state.get("risk_level") or 3),
    )
    if llm:
        return {
            "agent_scores": {"fundamental": llm.score},
            "agent_reasons": {"fundamental": llm.reason},
        }
    return _fundamental_rule(state)


def node_technical(state: MAFBState) -> dict[str, Any]:
    fund = state.get("fund_data") or {}
    missing = _missing_fields_for_agent("technical", fund, state)
    if missing:
        return {
            "agent_scores": {"technical": 0},
            "agent_reasons": {"technical": _data_not_ready_reason("technical", missing)},
        }
    llm = invoke_finance_agent_score(
        "technical",
        "基金趋势与动量分析师（非价格预测）",
        fund,
        list(state.get("rag_chunks") or []),
        int(state.get("risk_level") or 3),
    )
    if llm:
        return {
            "agent_scores": {"technical": llm.score},
            "agent_reasons": {"technical": llm.reason},
        }
    return _technical_rule(state)


def node_risk(state: MAFBState) -> dict[str, Any]:
    fund = state.get("fund_data") or {}
    missing = _missing_fields_for_agent("risk", fund, state)
    if missing:
        return {
            "agent_scores": {"risk": 0},
            "agent_reasons": {"risk": _data_not_ready_reason("risk", missing)},
        }
    llm = invoke_finance_agent_score(
        "risk",
        "基金风险与用户画像匹配分析师",
        fund,
        list(state.get("rag_chunks") or []),
        int(state.get("risk_level") or 3),
    )
    if llm:
        return {
            "agent_scores": {"risk": llm.score},
            "agent_reasons": {"risk": llm.reason},
        }
    return _risk_rule(state)


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


def node_kline_similar(state: MAFBState) -> dict[str, Any]:
    """K 线 / 净值序列相似：PAA+粗排+带窗 DTW 精排（tiered）。"""
    code = (state.get("fund_code") or "510300").strip()
    days = 80
    try:
        rows = find_similar_kline_funds(code, top_n=5, days=days, method="tiered")
    except Exception:
        rows = []
    sim = float(rows[0].get("similarity") or 0.0) if rows else 0.0
    fund = state.get("fund_data") or {}
    fund["kline_seed_similarity"] = sim
    kline_score = _clamp_score((sim - 0.75) * 6.0)
    level = "形态高度相似" if sim >= 0.85 else ("形态中度相似" if sim >= 0.7 else "形态相似度偏低")
    reason = (
        f"【核心结论】{level}；"
        f"【硬事实数据】近{days}日DTW最高相似度={sim:.2f}，方法=tiered(PAA+DTW)；"
        "【逻辑推演】相似度衡量历史曲线形态接近程度，仅用于形态学参考，不代表未来走势复现；"
        f"【形态评分】{kline_score}"
    )
    missing = _missing_fields_for_agent("kline", fund, state)
    if missing:
        return {
            "kline_similar_funds": rows,
            "agent_scores": {"kline": 0},
            "agent_reasons": {"kline": _data_not_ready_reason("kline", missing)},
            "compliance_notes": ["K线相似度：数据源未就绪，已输出中性分。"],
        }
    kline_chunks = _build_kline_symbolic_chunks(code, rows, days=days)
    llm = invoke_finance_agent_score(
        "kline",
        "K线形态学专家（PAA序列指纹+形态标签+DTW案例类比）",
        fund,
        list(state.get("rag_chunks") or []) + kline_chunks,
        int(state.get("risk_level") or 3),
    )
    if llm:
        reason = llm.reason
        kline_score = llm.score
    return {
        "kline_similar_funds": rows,
        "agent_scores": {"kline": kline_score},
        "agent_reasons": {"kline": reason},
        "compliance_notes": ["K线相似度：形态相近标的（净值序列，演示）。"],
    }


def node_asset_allocation(state: MAFBState) -> dict[str, Any]:
    profile = state.get("user_profile") or {}
    fund = state.get("fund_data") or {}
    risk = int(profile.get("risk_level") or 3)
    cap = round(min(0.78, 0.52 + risk * 0.05), 3)
    core_weight = round(min(0.45 + risk * 0.04, 0.65, cap - 0.1), 3)
    satellite = round(max(0.15, 1 - core_weight - 0.2), 3)
    cash = round(1 - core_weight - satellite, 3)

    portfolio = [
        {
            "code": fund.get("code"),
            "name": fund.get("name"),
            "role": "core",
            "weight": core_weight,
            "rationale": "核心仓：与 FBTI 推断风险等级相匹配的主基金/ETF。",
        },
        {
            "code": "511010",
            "name": "国债ETF",
            "role": "stabilizer",
            "weight": satellite if risk <= 3 else satellite * 0.6,
            "rationale": "波动缓冲：用于降低组合波动（演示用固定标的，可替换为货基/短债）。",
        },
        {
            "code": "CASH",
            "name": "现金管理",
            "role": "liquidity",
            "weight": max(cash, 0.05),
            "rationale": "流动性预留：便于定投与再平衡。",
        },
    ]
    return {
        "proposed_portfolio": portfolio,
        "compliance_notes": ["资产配置：结构化权重草案（非投资建议，演示）。"],
    }


def node_compliance(state: MAFBState) -> dict[str, Any]:
    reasons = state.get("agent_reasons") or {}
    text_blob = " ".join(reasons.values())
    notes: list[str] = []
    blocked = False
    reason = ""

    for word in _FORBIDDEN:
        if word in text_blob:
            blocked = True
            reason = f"命中合规词库：{word}"
            break

    fund = state.get("fund_data") or {}
    user_risk = int(state.get("risk_level") or 3)
    fund_risk = int(fund.get("risk_rating") or 3)
    if fund_risk - user_risk >= 3:
        blocked = True
        reason = reason or "基金风险等级显著高于用户画像可承受范围"

    scores = state.get("agent_scores") or {}
    raw_total = sum(scores.values())
    if raw_total <= -4:
        blocked = True
        reason = reason or "多智能体综合打分过低，触发审慎拦截"

    llm = invoke_compliance_llm(text_blob, str(fund.get("code", "")))
    if llm:
        notes.append(f"大模型合规审查：compliance_score={llm.compliance_score}。")
        if llm.advisory_notes:
            notes.append(llm.advisory_notes[:500])
        if not llm.allow_continue:
            blocked = True
            reason = reason or "大模型合规审查：不建议继续输出组合草案"

    notes.append("合规审查：已完成禁宣词检测与风险等级错配检测。")
    return {
        "is_compliant": not blocked,
        "blocked_reason": reason,
        "compliance_notes": notes,
    }


def node_voting(state: MAFBState) -> dict[str, Any]:
    scores = dict(state.get("agent_scores") or {})
    alloc_score = 1 if state.get("is_compliant") else -2
    scores["allocation"] = alloc_score

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
    kline_rows = list(state.get("kline_similar_funds") or [])
    similarity_top5 = _build_similarity_top5(anchor, kline_rows)
    chain = build_reasoning_chain()
    position = build_position_advice_mafb(user_profile)

    final_report = {
        "verdict": "pass",
        "weighted_total": round(weighted, 3),
        "scores": scores,
        "score_breakdown": detail,
        "user_profile": user_profile,
        "fund": anchor,
        "rag_chunks": state.get("rag_chunks"),
        "proposed_portfolio": state.get("proposed_portfolio"),
        "similarity_top5": similarity_top5,
        "kline_similar_funds": kline_rows,
        "top5_recommendations": [],
        "reasoning_chain": chain,
        "position_advice": position,
        "reasons": state.get("agent_reasons"),
        "compliance": {
            "is_compliant": state.get("is_compliant"),
            "blocked_reason": state.get("blocked_reason"),
            "notes": state.get("compliance_notes"),
        },
        "disclaimer": disclaimer,
    }

    final_report["summary"] = (
        f"多智能体加权总分 {weighted:.2f}；已输出 K 线/统计特征融合的相似基金 TOP5（演示）。"
    )

    return {"final_report": final_report, "weighted_total": round(weighted, 3), "agent_scores": {"allocation": alloc_score}}


def route_after_compliance(state: MAFBState) -> str:
    return "voting" if state.get("is_compliant") else "blocked"


def node_blocked(state: MAFBState) -> dict[str, Any]:
    disclaimer = (
        "本输出仅供教学演示，不构成投资建议。基金有风险，投资需谨慎。"
    )
    user_profile = state.get("user_profile") or {}
    anchor = state.get("fund_data") or {}
    kline_rows = list(state.get("kline_similar_funds") or [])
    similarity_top5 = _build_similarity_top5(anchor, kline_rows)
    report = {
        "verdict": "blocked",
        "weighted_total": sum((state.get("agent_scores") or {}).values()),
        "scores": state.get("agent_scores"),
        "reasons": state.get("agent_reasons"),
        "user_profile": user_profile,
        "top5_recommendations": [],
        "similarity_top5": similarity_top5,
        "kline_similar_funds": kline_rows,
        "reasoning_chain": build_reasoning_chain(),
        "position_advice": build_position_advice_mafb(user_profile) if user_profile else {},
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
    """第一阶段并行：基本面 / 技术面 / 风控 三路先行。"""
    try:
        from langgraph.types import Send
    except ModuleNotFoundError:
        from langgraph.constants import Send

    return [
        Send("fundamental", state),
        Send("technical", state),
        Send("risk", state),
    ]
