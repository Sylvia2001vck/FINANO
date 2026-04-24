from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

import numpy as np
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.modules.fund_offline.models import FundNavSnapshot
from app.modules.fund_offline.session import OfflineSessionLocal


@dataclass
class KlineWindowFeature:
    code: str
    start_date: str
    end_date: str
    vector: np.ndarray
    fwd_return_5d: float | None
    fwd_return_10d: float | None
    fwd_return_20d: float | None


def _paa(values: list[float], dims: int) -> np.ndarray:
    n = len(values)
    out: list[float] = []
    for i in range(dims):
        l = int(i * n / dims)
        r = int((i + 1) * n / dims)
        if r <= l:
            out.append(float(values[min(l, n - 1)]))
        else:
            out.append(float(sum(values[l:r]) / max(1, (r - l))))
    arr = np.array(out, dtype=np.float32)
    norm = float(np.linalg.norm(arr))
    if norm > 1e-12:
        arr = arr / norm
    return arr


def _group_series(db: Session, min_points: int = 40) -> dict[str, list[tuple[date, float]]]:
    rows = list(
        db.scalars(
            select(FundNavSnapshot).order_by(FundNavSnapshot.fund_code.asc(), FundNavSnapshot.nav_date.asc())
        )
    )
    by_code: dict[str, list[tuple[date, float]]] = {}
    for row in rows:
        code = str(row.fund_code or "").strip()
        if not code:
            continue
        by_code.setdefault(code, []).append((row.nav_date, float(row.nav)))
    return {k: v for k, v in by_code.items() if len(v) >= min_points}


def build_window_features(
    db: Session,
    *,
    window_size: int | None = None,
    paa_dims: int | None = None,
    max_codes: int | None = None,
) -> list[KlineWindowFeature]:
    win = int(window_size or settings.kline_window_size_days)
    dims = int(paa_dims or settings.kline_paa_dims)
    by_code = _group_series(db, min_points=max(40, win + 20))
    codes = sorted(by_code.keys())
    if max_codes and max_codes > 0:
        codes = codes[: int(max_codes)]

    out: list[KlineWindowFeature] = []
    for code in codes:
        seq = by_code.get(code) or []
        dates = [d for d, _ in seq]
        navs = [v for _, v in seq]
        if len(navs) < win + 1:
            continue
        for i in range(0, len(navs) - win + 1):
            part = navs[i : i + win]
            base = part[0]
            if base <= 0:
                continue
            norm_vals = [(x / base) - 1.0 for x in part]
            vec = _paa(norm_vals, dims)
            end_idx = i + win - 1

            def _fwd(days: int) -> float | None:
                j = end_idx + days
                if j >= len(navs):
                    return None
                p0 = navs[end_idx]
                p1 = navs[j]
                if p0 <= 0:
                    return None
                return float(p1 / p0 - 1.0)

            out.append(
                KlineWindowFeature(
                    code=code,
                    start_date=dates[i].isoformat(),
                    end_date=dates[end_idx].isoformat(),
                    vector=vec,
                    fwd_return_5d=_fwd(5),
                    fwd_return_10d=_fwd(10),
                    fwd_return_20d=_fwd(20),
                )
            )
    return out


def build_latest_query_feature(
    db: Session,
    code: str,
    *,
    window_size: int | None = None,
    paa_dims: int | None = None,
) -> tuple[np.ndarray | None, dict[str, Any] | None]:
    win = int(window_size or settings.kline_window_size_days)
    dims = int(paa_dims or settings.kline_paa_dims)
    rows = list(
        db.scalars(
            select(FundNavSnapshot)
            .where(FundNavSnapshot.fund_code == code)
            .order_by(FundNavSnapshot.nav_date.asc())
        )
    )
    if len(rows) < win:
        return None, None
    tail = rows[-win:]
    navs = [float(r.nav) for r in tail]
    base = navs[0]
    if base <= 0:
        return None, None
    norm_vals = [(x / base) - 1.0 for x in navs]
    vec = _paa(norm_vals, dims)
    meta = {
        "code": code,
        "start_date": tail[0].nav_date.isoformat(),
        "end_date": tail[-1].nav_date.isoformat(),
        "as_of": datetime.utcnow().isoformat(),
    }
    return vec, meta


def load_window_features_from_offline_db(max_codes: int | None = None) -> list[KlineWindowFeature]:
    db = OfflineSessionLocal()
    try:
        return build_window_features(db, max_codes=max_codes)
    finally:
        db.close()
