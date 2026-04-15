"""FAISS-backed retrieval over fund fact snippets + optional rerank by query hash."""

from __future__ import annotations

import hashlib
from typing import Any

import numpy as np

from app.agent.fund_catalog import all_fund_docs

_INDEX = None
_DOCS: list[str] = []
_META: list[dict[str, Any]] = []


def _text_embedding(text: str, dim: int = 64) -> np.ndarray:
    rng = np.random.default_rng(int(hashlib.sha256(text.encode("utf-8")).hexdigest()[:8], 16))
    vec = rng.standard_normal(dim, dtype=np.float32)
    norm = np.linalg.norm(vec) or 1.0
    return vec / norm


def _ensure_index() -> None:
    global _INDEX, _DOCS, _META
    if _INDEX is not None:
        return
    import faiss

    pairs = all_fund_docs()
    _DOCS = [p[0] for p in pairs]
    _META = [p[1] for p in pairs]
    if not _DOCS:
        _INDEX = faiss.IndexFlatIP(64)
        return
    dim = 64
    matrix = np.vstack([_text_embedding(t, dim) for t in _DOCS]).astype("float32")
    _INDEX = faiss.IndexFlatIP(dim)
    _INDEX.add(matrix)


def retrieve_fund_context(query: str, top_k: int = 3) -> tuple[list[str], list[dict[str, Any]]]:
    _ensure_index()
    import faiss

    if _INDEX is None or _INDEX.ntotal == 0:
        return [], []

    dim = 64
    q = _text_embedding(query, dim).reshape(1, -1).astype("float32")
    scores, idx = _INDEX.search(q, min(top_k, len(_DOCS)))
    chunks: list[str] = []
    metas: list[dict[str, Any]] = []
    for rank, i in enumerate(idx[0]):
        if i < 0 or i >= len(_DOCS):
            continue
        score = float(scores[0][rank])
        chunks.append(_DOCS[i])
        metas.append({**_META[i], "retrieval_score": round(score, 4)})
    return chunks, metas


def rerank_by_profile(
    metas: list[dict[str, Any]],
    user_profile: dict[str, Any],
) -> list[dict[str, Any]]:
    """Lightweight rerank: combine retrieval score with risk / sector tilt."""
    tilt = user_profile.get("layout_sector_tilt") or {}
    risk = int(user_profile.get("risk_level") or 3)

    def score_row(row: dict[str, Any]) -> float:
        base = float(row.get("retrieval_score", 0.0))
        track = row.get("track", "")
        sector_bonus = 0.1 * float(tilt.get(track, 0.0))
        rating = int(row.get("risk_rating") or 3)
        risk_penalty = abs(rating - risk) * 0.08
        return base + sector_bonus - risk_penalty

    ranked = sorted(metas, key=score_row, reverse=True)
    return ranked
