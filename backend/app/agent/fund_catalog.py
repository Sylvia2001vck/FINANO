"""Demo catalog of public funds / ETFs — 可通过 FUND_LIVE_QUOTE_ENABLED 合并天天基金估值快照。"""

from __future__ import annotations

from typing import Any

from app.core.config import settings
from app.services.fund_data import fetch_fund_live_quote

_FUNDS: list[dict[str, Any]] = [
    {
        "code": "510300",
        "name": "沪深300ETF",
        "type": "ETF",
        "track": "宽基",
        "aum_billion": 1200.0,
        "sharpe_3y": 0.45,
        "max_drawdown_3y": 0.28,
        "momentum_60d": 0.06,
        "risk_rating": 3,
        "doc": "跟踪沪深300指数，规模大、流动性好，适合作为核心宽基仓位。",
    },
    {
        "code": "515050",
        "name": "5G通信ETF",
        "type": "ETF",
        "track": "科技",
        "aum_billion": 45.0,
        "sharpe_3y": 0.12,
        "max_drawdown_3y": 0.42,
        "momentum_60d": 0.11,
        "risk_rating": 4,
        "doc": "通信与算力产业链主题，波动高于宽基，适合风险承受能力较强的配置。",
    },
    {
        "code": "159928",
        "name": "消费ETF",
        "type": "ETF",
        "track": "消费",
        "aum_billion": 180.0,
        "sharpe_3y": 0.38,
        "max_drawdown_3y": 0.31,
        "momentum_60d": -0.02,
        "risk_rating": 3,
        "doc": "主要覆盖必选与可选消费龙头，长期与内需修复相关。",
    },
    {
        "code": "511010",
        "name": "国债ETF",
        "type": "ETF",
        "track": "固收",
        "aum_billion": 35.0,
        "sharpe_3y": 0.62,
        "max_drawdown_3y": 0.04,
        "momentum_60d": 0.01,
        "risk_rating": 2,
        "doc": "利率债久期工具，波动较低，可用于降低组合波动。",
    },
    {
        "code": "005827",
        "name": "易方达蓝筹精选混合",
        "type": "公募基金",
        "track": "均衡",
        "aum_billion": 520.0,
        "sharpe_3y": 0.22,
        "max_drawdown_3y": 0.35,
        "momentum_60d": 0.03,
        "risk_rating": 3,
        "doc": "偏股混合，行业相对均衡，适合中长期持有与定投思路。",
    },
]


def list_funds_catalog_only() -> list[dict[str, Any]]:
    """仅演示池静态字段（不打行情接口，供相似度计算等使用）。"""
    return [dict(x) for x in _FUNDS]


def get_fund_by_code(code: str, *, include_live: bool | None = None) -> dict[str, Any] | None:
    """
    include_live：默认 None 表示跟随 FUND_LIVE_QUOTE_ENABLED；
    显式 False 时不请求估值（避免相似度等内部逻辑 N 次打网）。
    """
    normalized = code.strip()
    for row in _FUNDS:
        if row["code"] == normalized:
            out = dict(row)
            want_live = settings.fund_live_quote_enabled if include_live is None else include_live
            if want_live:
                live = fetch_fund_live_quote(normalized)
                if live:
                    out["live_quote"] = live
            return out
    return None


def all_fund_docs() -> list[tuple[str, dict[str, Any]]]:
    """(doc_text, metadata) for FAISS indexing."""
    return [(f"{item['code']} {item['name']} {item['track']} {item['doc']}", item) for item in _FUNDS]


def list_funds() -> list[dict[str, Any]]:
    """演示基金池列表；开启 FUND_LIVE_QUOTE_ENABLED 时为每条合并 live_quote（供 GET /api/v1/agent/funds）。"""
    if not settings.fund_live_quote_enabled:
        return list_funds_catalog_only()
    out: list[dict[str, Any]] = []
    for row in _FUNDS:
        item = dict(row)
        live = fetch_fund_live_quote(str(row["code"]))
        if live:
            item["live_quote"] = live
        out.append(item)
    return out
