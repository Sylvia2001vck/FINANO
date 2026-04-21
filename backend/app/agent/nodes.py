from __future__ import annotations

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
from app.services.similar_funds import similar_funds

_FORBIDDEN = ("保证收益", "稳赚", "无风险", "内幕", "必涨", "只赚不赔")
_WEIGHTS = {
    "fundamental": 0.25,
    "technical": 0.25,
    "risk": 0.20,
    "profiling": 0.15,
    "allocation": 0.15,
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
    reason = (
        f"FBTI「{name_fb}」画像中的类型/赛道偏好摘要与标的赛道「{track}」的一致性粗评（演示规则）。"
        f"偏好摘要：{pref[:160] or '—'}。"
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


def node_load_fund_and_rag(state: MAFBState) -> dict[str, Any]:
    code = (state.get("fund_code") or "510300").strip()
    fund = get_fund_by_code(code)
    if not fund:
        fund = get_fund_by_code("510300") or {}
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
    reason = (
        f"基金基本面：规模约{aum:.0f}亿，近三年夏普约{sharpe:.2f}，最大回撤约{dd:.0%}。"
        " 以上为历史统计特征，不代表未来表现。"
    )
    return {"agent_scores": {"fundamental": score}, "agent_reasons": {"fundamental": reason}}


def _technical_rule(state: MAFBState) -> dict[str, Any]:
    fund = state.get("fund_data") or {}
    mom = float(fund.get("momentum_60d") or 0)
    score = _clamp_score(mom * 12)
    reason = f"技术面/动量：近60日收益约{mom:.2%}，用于趋势与动量维度打分（非预测）。"
    return {"agent_scores": {"technical": score}, "agent_reasons": {"technical": reason}}


def _risk_rule(state: MAFBState) -> dict[str, Any]:
    fund = state.get("fund_data") or {}
    user_risk = int(state.get("risk_level") or 3)
    fund_risk = int(fund.get("risk_rating") or 3)
    gap = fund_risk - user_risk
    score = _clamp_score(1.5 - gap)
    reason = f"风控匹配：用户风险等级{user_risk}，标的基金风险评级约{fund_risk}，偏差{gap}档。"
    return {"agent_scores": {"risk": score}, "agent_reasons": {"risk": reason}}


def node_fundamental(state: MAFBState) -> dict[str, Any]:
    fund = state.get("fund_data") or {}
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


def node_kline_similar(state: MAFBState) -> dict[str, Any]:
    """K 线 / 净值序列相似：PAA+粗排+带窗 DTW 精排（tiered）。"""
    code = (state.get("fund_code") or "510300").strip()
    days = 80
    try:
        rows = find_similar_kline_funds(code, top_n=5, days=days, method="tiered")
    except Exception:
        rows = []
    reason = (
        f"K线相似基金：近 {days} 日 PAA 粗排 + 带窗 DTW 精排（tiered），"
        f"与目录内基金比较（历史形态，非预测）。"
    )
    return {
        "kline_similar_funds": rows,
        "agent_scores": {"kline": 0},
        "agent_reasons": {"kline": reason},
        "compliance_notes": ["K线相似度：形态相近标的（净值序列，演示）。"],
    }


def node_asset_allocation(state: MAFBState) -> dict[str, Any]:
    profile = state.get("user_profile") or {}
    fund = state.get("fund_data") or {}
    score_p, reason_p = _fbti_track_alignment_score(state)
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
        "agent_scores": {"profiling": score_p},
        "agent_reasons": {"profiling": reason_p},
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
    """LangGraph 原生并行：基本面 / 技术面 / 风控 / K线相似 四路 fan-out（Send）。"""
    try:
        from langgraph.types import Send
    except ModuleNotFoundError:
        from langgraph.constants import Send

    return [
        Send("fundamental", state),
        Send("technical", state),
        Send("risk", state),
        Send("kline_similar", state),
    ]
