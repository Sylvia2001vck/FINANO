"""从东方财富/天天基金公开 JS 拉取全市场基金代码与名称，映射为 fund_catalog 统一结构。"""

from __future__ import annotations

import json
import logging
import re
import threading
from typing import Any

import httpx

logger = logging.getLogger(__name__)

_FUNDCODE_SEARCH_URL = "https://fund.eastmoney.com/js/fundcode_search.js"
# 写缓存与 rag 重置；与 _FETCH_ONCE 配合，避免在持锁期间执行 HTTP
_LOCK = threading.Lock()
# 全市场目录只拉取一次；HTTP 在锁外执行，其它接口仍可读状态而不被长时间阻塞
_FETCH_ONCE = threading.Lock()
_CACHE_ROWS: list[dict[str, Any]] | None = None
_CACHE_INDEX: dict[str, dict[str, Any]] | None = None
_LAST_FETCH_ERROR: str | None = None
_INFLIGHT_WARM: threading.Thread | None = None
_INFLIGHT_LOCK = threading.Lock()
# 同步请求（如 GET /funds）正在拉取时也为 True，便于与后台 warm 线程统一展示「busy」
_CATALOG_FETCH_ACTIVE = False


def _category_to_track(category: str) -> str:
    c = (category or "").strip()
    if not c:
        return "其他"
    for sep in ("-", "·", "－"):
        if sep in c:
            return (c.split(sep, 1)[0].strip() or "其他")[:12]
    return (c[:12] if c else "其他")


def _risk_from_category(category: str) -> int:
    c = category or ""
    if "货币" in c:
        return 1
    if "债券" in c or "债" in c:
        return 2
    if "股票" in c or "指数" in c or "ETF" in c.upper():
        return 4
    if "混合" in c:
        return 3
    return 3


def _row_to_fund(item: list[Any]) -> dict[str, Any] | None:
    if not item or len(item) < 4:
        return None
    code = str(item[0]).strip()
    name = str(item[2]).strip()
    category = str(item[3]).strip()
    if not re.fullmatch(r"\d{6}", code) or not name:
        return None
    track = _category_to_track(category)
    return {
        "code": code,
        "name": name,
        "type": category[:32] or "基金",
        "track": track,
        "aum_billion": 0.0,
        "sharpe_3y": 0.0,
        "max_drawdown_3y": 0.3,
        "momentum_60d": 0.0,
        "risk_rating": _risk_from_category(category),
        "doc": f"{name}（{category}）。全市场索引条目，夏普/回撤等为演示占位，非实时回测。",
        "source": "eastmoney_fundcode_search",
    }


def _parse_fundcode_search_js(text: str) -> list[list[Any]]:
    text = text.strip().lstrip("\ufeff")
    m = re.search(r"var\s+r\s*=\s*(\[[\s\S]*\])\s*;", text)
    if not m:
        raise ValueError("fundcode_search.js: 未匹配到 var r = [...];")
    return json.loads(m.group(1))


def fetch_full_fund_rows(*, timeout: float = 120.0) -> list[dict[str, Any]]:
    """HTTP 拉取并解析；失败抛错由上层降级。"""
    headers = {
        "User-Agent": "Mozilla/5.0 (compatible; Finano/1.0)",
        "Referer": "https://fund.eastmoney.com/",
    }
    with httpx.Client(timeout=timeout, follow_redirects=True) as client:
        r = client.get(_FUNDCODE_SEARCH_URL, headers=headers)
        r.raise_for_status()
        text = r.text
    raw_rows = _parse_fundcode_search_js(text)
    out: list[dict[str, Any]] = []
    for item in raw_rows:
        row = _row_to_fund(item)
        if row:
            out.append(row)
    if not out:
        raise ValueError("解析结果为空")
    logger.info("eastmoney fundcode_search: loaded %s funds", len(out))
    return out


def get_catalog_status() -> dict[str, Any]:
    """供 HTTP 轮询：是否已缓存、后台是否仍在拉取、最近一次错误（无则 null）。"""
    rows = _CACHE_ROWS
    if rows is not None:
        return {"cached": True, "count": len(rows), "busy": False, "error": None}
    with _INFLIGHT_LOCK:
        warm_alive = _INFLIGHT_WARM is not None and _INFLIGHT_WARM.is_alive()
    return {
        "cached": False,
        "count": 0,
        "busy": warm_alive or _CATALOG_FETCH_ACTIVE,
        "error": _LAST_FETCH_ERROR,
    }


def get_cached_full_catalog() -> list[dict[str, Any]]:
    """线程安全懒加载；首次调用会下载约 2MB JS（在 _FETCH_ONCE 内单飞，HTTP 不占 _LOCK）。"""
    global _CACHE_ROWS, _CACHE_INDEX, _LAST_FETCH_ERROR, _CATALOG_FETCH_ACTIVE
    if _CACHE_ROWS is not None:
        return _CACHE_ROWS
    with _FETCH_ONCE:
        if _CACHE_ROWS is not None:
            return _CACHE_ROWS
        _CATALOG_FETCH_ACTIVE = True
        try:
            _LAST_FETCH_ERROR = None
            rows = fetch_full_fund_rows()
            with _LOCK:
                _CACHE_ROWS = rows
                _CACHE_INDEX = {str(r["code"]): dict(r) for r in rows}
            try:
                from app.agent import rag_faiss

                rag_faiss.reset_rag_index()
            except Exception:
                logger.debug("rag_faiss.reset_rag_index skipped", exc_info=True)
            return _CACHE_ROWS
        except Exception as e:
            _LAST_FETCH_ERROR = str(e)
            raise
        finally:
            _CATALOG_FETCH_ACTIVE = False


def start_warm_catalog_background() -> str:
    """
    在后台线程触发 get_cached_full_catalog（与首次 HTTP 命中共享单飞锁）。
    返回: ready | running | started
    """
    global _INFLIGHT_WARM
    if _CACHE_ROWS is not None:
        return "ready"

    def _worker() -> None:
        try:
            get_cached_full_catalog()
        except Exception:
            logger.exception("后台预热全市场基金目录失败")

    with _INFLIGHT_LOCK:
        if _INFLIGHT_WARM is not None and _INFLIGHT_WARM.is_alive():
            return "running"
        t = threading.Thread(target=_worker, daemon=True, name="eastmoney-catalog-warm")
        _INFLIGHT_WARM = t
        t.start()
    return "started"


def get_cached_index() -> dict[str, dict[str, Any]]:
    get_cached_full_catalog()
    assert _CACHE_INDEX is not None
    return _CACHE_INDEX


def lookup_full_catalog(code: str) -> dict[str, Any] | None:
    row = get_cached_index().get(code.strip())
    return dict(row) if row else None


def reset_full_catalog_cache() -> None:
    global _CACHE_ROWS, _CACHE_INDEX, _LAST_FETCH_ERROR, _INFLIGHT_WARM, _CATALOG_FETCH_ACTIVE
    with _FETCH_ONCE:
        _CATALOG_FETCH_ACTIVE = False
        with _LOCK:
            _CACHE_ROWS = None
            _CACHE_INDEX = None
            _LAST_FETCH_ERROR = None
        with _INFLIGHT_LOCK:
            _INFLIGHT_WARM = None
