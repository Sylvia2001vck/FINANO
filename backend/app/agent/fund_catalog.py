"""基金目录：默认内置演示池；可选 FUND_CATALOG_MODE=eastmoney_full 从天天基金公开 JS 加载全市场索引。"""

from __future__ import annotations

import random
import time
from typing import Any

from app.core.config import settings
from app.services.fund_data import fetch_fund_live_quote

_STATIC_FUNDS: list[dict[str, Any]] = [
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


def static_demo_pool_size() -> int:
    """内置演示池只数（供 catalog-status 等展示）。"""
    return len(_STATIC_FUNDS)


def _use_eastmoney_full() -> bool:
    return (settings.fund_catalog_mode or "static").lower().strip() == "eastmoney_full"


def _catalog_rows() -> list[dict[str, Any]]:
    if not _use_eastmoney_full():
        return _STATIC_FUNDS
    from app.agent.eastmoney_fund_loader import get_cached_full_catalog
    try:
        return get_cached_full_catalog()
    except Exception:
        # 全市场索引拉取失败时降级到内置演示池，避免 /agent/funds 直接 500
        return _STATIC_FUNDS


def list_funds_catalog_only() -> list[dict[str, Any]]:
    """仅目录静态字段（不打行情接口，供相似度 / TOP5 / FAISS 等使用）。"""
    return [dict(x) for x in _catalog_rows()]


def resolve_fund_code_by_name_query(query: str) -> str | None:
    """
    按基金名称在全库中解析 6 位代码：全名唯一、前缀唯一、子串唯一时返回；否则取子串命中里名称最短的一条。
    """
    q = (query or "").strip().lower()
    if len(q) < 2:
        return None
    rows = list_funds_catalog_only()
    names = [(str(r.get("name", "")).strip().lower(), str(r["code"])) for r in rows if r.get("code")]
    exact = [c for n, c in names if n == q]
    if len(exact) == 1:
        return exact[0]
    starts = [c for n, c in names if n.startswith(q)]
    if len(starts) == 1:
        return starts[0]
    contains = [(n, c) for n, c in names if q in n]
    if not contains:
        return None
    if len(contains) == 1:
        return contains[0][1]
    contains.sort(key=lambda x: len(x[0]))
    return contains[0][1]


def filter_catalog_rows(
    rows: list[dict[str, Any]],
    *,
    query: str | None = None,
    track_kw: str | None = None,
    type_kw: str | None = None,
    etf_only: bool = False,
    risk_min: int | None = None,
    risk_max: int | None = None,
) -> list[dict[str, Any]]:
    """选股规则筛选（子串 + 风险区间 + 可选仅 ETF），在全量目录子集上操作。"""
    out = list(rows)
    if query and query.strip():
        qs = query.strip().lower()
        out = [r for r in out if qs in str(r.get("code", "")).lower() or qs in str(r.get("name", "")).lower()]
    if track_kw and track_kw.strip():
        tk = track_kw.strip().lower()
        out = [r for r in out if tk in str(r.get("track", "")).lower()]
    if type_kw and type_kw.strip():
        uk = type_kw.strip().lower()
        out = [r for r in out if uk in str(r.get("type", "")).lower()]
    if etf_only:
        out = [
            r
            for r in out
            if "etf" in str(r.get("type", "")).lower() or "etf" in str(r.get("name", "")).lower()
        ]
    if risk_min is not None:
        out = [r for r in out if int(r.get("risk_rating") or 0) >= int(risk_min)]
    if risk_max is not None:
        out = [r for r in out if int(r.get("risk_rating") or 0) <= int(risk_max)]
    return out


def list_funds_catalog_sample(
    *,
    limit: int = 400,
    seed: int | None = None,
    query: str | None = None,
    track_kw: str | None = None,
    type_kw: str | None = None,
    etf_only: bool = False,
    risk_min: int | None = None,
    risk_max: int | None = None,
) -> tuple[list[dict[str, Any]], int, int]:
    """
    在筛选后的池子中随机抽取 limit 条（不固定「前 400」）。
    返回 (样本, 筛选后池子大小, 使用的随机种子)。
    """
    rows = list_funds_catalog_only()
    filtered = filter_catalog_rows(
        rows,
        query=query,
        track_kw=track_kw,
        type_kw=type_kw,
        etf_only=etf_only,
        risk_min=risk_min,
        risk_max=risk_max,
    )
    pool = filtered if filtered else rows
    pool_size = len(pool)
    if pool_size == 0:
        return [], 0, seed or 0
    seed_used = int(seed) if seed is not None else int(time.time() * 1000) % (2**31)
    rng = random.Random(seed_used)
    k = min(int(limit), pool_size)
    idx = list(range(pool_size))
    rng.shuffle(idx)
    picked = [dict(pool[i]) for i in idx[:k]]
    return picked, pool_size, seed_used


def list_funds_catalog_window(
    *,
    limit: int = 200,
    offset: int = 0,
    query: str | None = None,
) -> tuple[list[dict[str, Any]], int]:
    """分页 + 可选按代码/名称子串筛选；用于 HTTP 列表接口，避免一次返回上万条。"""
    rows = list_funds_catalog_only()
    if query and query.strip():
        qs = query.strip().lower()
        rows = [
            r
            for r in rows
            if qs in str(r.get("code", "")).lower() or qs in str(r.get("name", "")).lower()
        ]
    total = len(rows)
    slice_ = rows[offset : offset + limit]
    return [dict(x) for x in slice_], total


def get_fund_by_code(code: str, *, include_live: bool | None = None) -> dict[str, Any] | None:
    """
    include_live：默认 None 表示跟随 FUND_LIVE_QUOTE_ENABLED；
    显式 False 时不请求估值（避免相似度等内部逻辑 N 次打网）。
    """
    normalized = code.strip()
    base: dict[str, Any] | None = None
    if _use_eastmoney_full():
        from app.agent.eastmoney_fund_loader import lookup_full_catalog

        hit = lookup_full_catalog(normalized)
        base = dict(hit) if hit else None
    else:
        for row in _STATIC_FUNDS:
            if row["code"] == normalized:
                base = dict(row)
                break
    if not base:
        return None
    out = dict(base)
    want_live = settings.fund_live_quote_enabled if include_live is None else include_live
    if want_live:
        live = fetch_fund_live_quote(normalized)
        if live:
            out["live_quote"] = live
    return out


def all_fund_docs() -> list[tuple[str, dict[str, Any]]]:
    """(doc_text, metadata) for FAISS indexing。"""
    return [(f"{item['code']} {item['name']} {item['track']} {item['doc']}", item) for item in _catalog_rows()]


def list_funds() -> list[dict[str, Any]]:
    """
    列表接口用：全市场模式下不批量合并估值（避免 N 次 HTTP），仅返回目录字段；
    单只估值请用 get_fund_by_code 或后续专用接口。
    """
    rows = list_funds_catalog_only()
    if _use_eastmoney_full():
        return rows
    if not settings.fund_live_quote_enabled:
        return rows
    out: list[dict[str, Any]] = []
    for row in rows:
        item = dict(row)
        live = fetch_fund_live_quote(str(row["code"]))
        if live:
            item["live_quote"] = live
        out.append(item)
    return out
