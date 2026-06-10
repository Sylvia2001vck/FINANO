"""BOCHK / Hong Kong demo data layer: curated fund catalog, mock quotes, SFC RAG chunks."""

from __future__ import annotations

import json
import logging
from functools import lru_cache
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_DATA_DIR = Path(__file__).resolve().parent.parent / "data"


@lru_cache(maxsize=1)
def load_bochk_catalog() -> list[dict[str, Any]]:
    path = _DATA_DIR / "bochk_funds.json"
    with path.open(encoding="utf-8") as f:
        rows = json.load(f)
    out: list[dict[str, Any]] = []
    for row in rows:
        item = dict(row)
        item.setdefault("type", "公募基金")
        item.setdefault("track", "其他")
        item.setdefault("risk_rating", 3)
        item.setdefault("sharpe_3y", 0.2)
        item.setdefault("max_drawdown_3y", 0.15)
        item.setdefault("momentum_60d", 0.0)
        item.setdefault("aum_billion", float(item.get("aum_billion") or 1.0))
        item["catalog_region"] = "HK"
        item["distributor"] = "BOCHK"
        out.append(item)
    return out


@lru_cache(maxsize=1)
def _bochk_index() -> dict[str, dict[str, Any]]:
    idx: dict[str, dict[str, Any]] = {}
    for row in load_bochk_catalog():
        code = str(row.get("code", "")).strip().upper()
        if code:
            idx[code] = row
        isin = str(row.get("isin", "")).strip().upper()
        if isin:
            idx[isin] = row
    return idx


def lookup_bochk_fund(code_or_isin: str) -> dict[str, Any] | None:
    key = (code_or_isin or "").strip().upper()
    if not key:
        return None
    hit = _bochk_index().get(key)
    return dict(hit) if hit else None


def resolve_bochk_fund_by_name_query(query: str) -> str | None:
    q = (query or "").strip().lower()
    if len(q) < 2:
        return None
    rows = load_bochk_catalog()
    names = [
        (str(r.get("name", "")).strip().lower(), str(r["code"]))
        for r in rows
        if r.get("code")
    ]
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


def fetch_bochk_mock_live_quote(code: str) -> dict[str, Any] | None:
    """演示用：以 JSON 內 nav_latest 模擬 BOCHK 公開基金價格快照。"""
    base = lookup_bochk_fund(code)
    if not base:
        return None
    nav = base.get("nav_latest")
    if nav is None:
        return None
    return {
        "source": "bochk_demo",
        "fund_code": base.get("code"),
        "isin": base.get("isin"),
        "nav": float(nav),
        "currency": base.get("currency") or "HKD",
        "name": base.get("name"),
        "risk_rating": base.get("risk_rating"),
        "as_of": "demo_snapshot",
    }


def _read_text_chunks(path: Path, *, doc_type: str, region: str) -> list[tuple[str, dict[str, Any]]]:
    if not path.is_file():
        return []
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        logger.warning("Failed to read %s", path)
        return []
    chunks: list[tuple[str, dict[str, Any]]] = []
    buf: list[str] = []
    title = doc_type
    for line in text.splitlines():
        if line.startswith("# "):
            if buf:
                body = "\n".join(buf).strip()
                if body:
                    chunks.append((body, {"doc_type": doc_type, "region": region, "title": title}))
                buf = []
            title = line.lstrip("# ").strip()
        else:
            buf.append(line)
    if buf:
        body = "\n".join(buf).strip()
        if body:
            chunks.append((body, {"doc_type": doc_type, "region": region, "title": title}))
    return chunks


def load_sfc_rag_pairs() -> list[tuple[str, dict[str, Any]]]:
    pairs: list[tuple[str, dict[str, Any]]] = []
    pairs.extend(
        _read_text_chunks(
            _DATA_DIR / "sfc_compliance" / "suitability_guidelines.md",
            doc_type="sfc_compliance",
            region="HK",
        )
    )
    pairs.extend(
        _read_text_chunks(
            _DATA_DIR / "hk_investor_context.md",
            doc_type="hk_investor_context",
            region="HK",
        )
    )
    return pairs
