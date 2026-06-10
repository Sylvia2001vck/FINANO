"""Unified RAG document pairs: fund facts + SFC compliance + HK investor context."""

from __future__ import annotations

from typing import Any

from app.agent.fund_catalog import all_fund_docs
from app.core.config import settings
from app.services.bochk_data import load_sfc_rag_pairs


def is_bochk_catalog_mode() -> bool:
    return (settings.fund_catalog_mode or "static").strip().lower() == "bochk_hk"


def all_rag_doc_pairs() -> list[tuple[str, dict[str, Any]]]:
    pairs = list(all_fund_docs())
    if is_bochk_catalog_mode():
        pairs.extend(load_sfc_rag_pairs())
    return pairs
