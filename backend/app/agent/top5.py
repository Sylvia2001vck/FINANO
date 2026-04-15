"""个性化基金 TOP5：命理结构化理由 + 金融统计理由（演示池全量打分）。"""

from __future__ import annotations

from typing import Any

from app.agent.fund_catalog import list_funds


def _track_mingli_score(dominant: str, track: str) -> float:
    mapping = {
        "金": {"固收": 2, "宽基": 1, "均衡": 1, "消费": 0, "科技": -1},
        "木": {"科技": 2, "均衡": 1, "宽基": 0, "消费": 0, "固收": -1},
        "水": {"固收": 1, "宽基": 1, "均衡": 1, "科技": 0, "消费": 0},
        "火": {"科技": 2, "消费": 1, "宽基": 0, "均衡": 0, "固收": -2},
        "土": {"均衡": 2, "宽基": 1, "消费": 1, "科技": 0, "固收": 0},
    }
    return float(mapping.get(dominant, mapping["土"]).get(track, 0))


def build_reasoning_chain() -> list[str]:
    return [
        "① User Profiling Agent：MBTI 风险偏好 + 五行向量 + 日主演示特征 + 喜忌规则 + 2026 丙午流年/风水倾斜 → 结构化 user_profile",
        "② RAG：FAISS 检索基金事实片段，重排融合画像",
        "③ 并行 Analysts：Fundamental / Technical / Risk（LangGraph Send）→ agent_scores",
        "④ Asset Allocation：组合权重 + 流年仓位上限",
        "⑤ Compliance：禁宣词 + 风险错配 + 可选大模型合规 JSON",
        "⑥ Voting：加权投票 → 最终报告与 TOP5",
    ]


def build_top5_recommendations(user_profile: dict[str, Any], anchor_fund: dict[str, Any]) -> list[dict[str, Any]]:
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
