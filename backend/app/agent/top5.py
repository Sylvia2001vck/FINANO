"""MAFB：推理链文案；娱乐化个性化 TOP5（五行/流年）供 AI 选股页使用。"""

from __future__ import annotations

from typing import Any

from app.agent.fund_catalog import list_funds


def build_reasoning_chain() -> list[str]:
    return [
        "① User Profiling（MAFB）：仅使用已保存的 FBTI 金融人格与账户风险偏好，合成 risk_level 与风格标签；不含八字五行流年演示。",
        "② 基金主数据与预热：按主基金代码拉取目录字段，叠加离线净值仓与实时估值，并计算夏普/回撤/波动率/EMA/RSI/MACD 等统计特征。",
        "③ RAG（FAISS）：用「代码 + 名称 + 赛道」检索事实片段；按用户 risk_level 对命中结果轻量重排。",
        "④ 并行基本面 / 技术面 / 风控 / 业绩风格归因 / 画像匹配（LangGraph Send）：五路写 agent_scores 与 agent_reasons。",
        "④a 基本面：以 akshare/em 数据快照（规模/持仓/漂移）+ 统计特征为输入，优先金融大模型 JSON；失败则规则分。",
        "④b 技术面：优先 LLM；失败则动量规则分。",
        "④c 风控：优先 LLM；失败则用户与基金风险等级偏差规则分。",
        "④d 业绩与风格归因：拆解超额收益来源（选股/风格Beta/择时/风控）并输出大盘小盘、价值成长、质量的相似度与偏离度。",
        "④e 画像匹配：评估用户画像与标的风格适配度，解释潜在行为偏差风险。",
        "⑤ Compliance：执行禁宣词、风险错配与可选合规大模型审查；输出合规提示但不拦截主结果。",
        "⑥ Voting：对五个子智能体加权汇总，输出单基金大模型分析、技术快照、风险快照、归因结果与可解释链路（不输出组合草案）。",
    ]


def build_position_advice_mafb(user_profile: dict[str, Any]) -> dict[str, Any]:
    """不含流年：仅用 FBTI 推断的 risk_level 给出权益上限演示。"""
    risk = int(user_profile.get("risk_level") or 3)
    cap = round(min(0.78, 0.52 + risk * 0.05), 3)
    equity_suggest = round(min(cap - 0.08, 0.32 + risk * 0.06), 3)
    return {
        "risk_level": risk,
        "suggested_max_equity_weight": equity_suggest,
        "liunian_equity_cap": cap,
        "note": "基于 FBTI 推断的风险档位与权益上限（演示，不构成投资建议）。",
    }


def _track_mingli_score(dominant: str, track: str) -> float:
    mapping = {
        "金": {"固收": 2, "宽基": 1, "均衡": 1, "消费": 0, "科技": -1},
        "木": {"科技": 2, "均衡": 1, "宽基": 0, "消费": 0, "固收": -1},
        "水": {"固收": 1, "宽基": 1, "均衡": 1, "科技": 0, "消费": 0},
        "火": {"科技": 2, "消费": 1, "宽基": 0, "均衡": 0, "固收": -2},
        "土": {"均衡": 2, "宽基": 1, "消费": 1, "科技": 0, "固收": 0},
    }
    return float(mapping.get(dominant, mapping["土"]).get(track, 0))


def build_top5_personalized_entertainment(user_profile: dict[str, Any], anchor_fund: dict[str, Any]) -> list[dict[str, Any]]:
    user_risk = int(user_profile.get("risk_level") or 3)
    dominant = user_profile.get("dominant_element") or "土"
    liu = user_profile.get("liunian_2026") or {}
    sector_bias = liu.get("sector_bias") or {}
    layout = user_profile.get("layout_sector_tilt") or {}

    ranked: list[tuple[float, dict[str, Any]]] = []
    for fund in list_funds():
        track = str(fund.get("track") or "宽基")
        sharpe = float(fund.get("sharpe_3y") or 0)
        dd = float(fund.get("max_drawdown_3y") or 0.3)
        mom = float(fund.get("momentum_60d") or 0)
        fund_risk = int(fund.get("risk_rating") or 3)

        fin = sharpe * 2.2 - dd * 2.6 + mom * 7.0 + (3 - abs(fund_risk - user_risk)) * 0.55
        ming = _track_mingli_score(dominant, track) * 1.1
        ming += float(sector_bias.get(track, 0)) * 12.0
        ming += float(layout.get(track, 0)) * 6.0

        if fund.get("code") == anchor_fund.get("code"):
            fin += 0.35

        total = fin + ming
        reason_ming = (
            f"命理/结构化：日主五行语境 dominant={dominant}，赛道={track}；"
            f"2026 丙午行业倾斜系数约 {float(sector_bias.get(track, 0)):.2f}；"
            f"环境偏好倾斜约 {float(layout.get(track, 0)):.2f}。"
        )
        reason_fin = (
            f"金融统计：近三年夏普约 {sharpe:.2f}，最大回撤约 {dd:.0%}，60 日动量约 {mom:.2%}，"
            f"基金风险等级 {fund_risk} 与用户画像风险 {user_risk} 对齐评估。"
        )
        ranked.append(
            (
                total,
                {
                    "code": fund.get("code"),
                    "name": fund.get("name"),
                    "track": track,
                    "composite_score": round(total, 3),
                    "reason_mingli_structured": reason_ming,
                    "reason_finance": reason_fin,
                    "is_anchor": fund.get("code") == anchor_fund.get("code"),
                },
            )
        )

    ranked.sort(key=lambda x: x[0], reverse=True)
    out = []
    for i, (_, row) in enumerate(ranked[:5], start=1):
        row["rank"] = i
        out.append(row)
    return out


# 兼容旧名：AI 选股娱乐化融合层仍 import 此名
build_top5_recommendations = build_top5_personalized_entertainment


def build_position_advice(user_profile: dict[str, Any]) -> dict[str, Any]:
    liu = user_profile.get("liunian_2026") or {}
    cap = float(liu.get("max_equity_weight_cap") or 0.68)
    risk = int(user_profile.get("risk_level") or 3)
    equity_suggest = round(min(cap, 0.35 + risk * 0.06), 3)
    return {
        "risk_level": risk,
        "suggested_max_equity_weight": equity_suggest,
        "liunian_equity_cap": cap,
        "note": liu.get("position_note", ""),
    }
