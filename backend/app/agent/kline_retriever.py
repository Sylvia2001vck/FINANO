from __future__ import annotations

from collections import deque
from datetime import datetime
import time
from typing import Any

from sqlalchemy import select

from app.agent.kline_faiss_store import get_index_version, query_latest_fund_windows
from app.modules.fund_offline.models import FundNavSnapshot
from app.modules.fund_offline.query_queue import run_serial_db_task
from app.modules.fund_offline.session import OfflineSessionLocal

_RETRIEVAL_COSTS = deque(maxlen=512)
_SHADOW_COSTS = deque(maxlen=512)


def _percentile(values: list[float], p: float) -> float | None:
    if not values:
        return None
    arr = sorted(values)
    idx = int(round((len(arr) - 1) * p))
    idx = max(0, min(idx, len(arr) - 1))
    return float(arr[idx])


def retrieve_technical_matches(code: str, top_k: int = 5, nav_rows: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    t0 = time.monotonic()
    c = str(code or "").strip()
    if not c:
        out = {"ok": False, "error": "data_not_ready", "matches": [], "query": None, "data_version": get_index_version()}
        _RETRIEVAL_COSTS.append(time.monotonic() - t0)
        return out
    try:
        result = query_latest_fund_windows(c, top_k=top_k, nav_rows=nav_rows)
    except Exception:  # noqa: BLE001
        out = {"ok": False, "error": "query_failed", "matches": [], "query": None, "data_version": get_index_version()}
        _RETRIEVAL_COSTS.append(time.monotonic() - t0)
        return out
    result["data_version"] = get_index_version()
    _RETRIEVAL_COSTS.append(time.monotonic() - t0)
    return result


def get_shadow_segments_for_matches(
    matches: list[dict[str, Any]],
    *,
    max_points_per_segment: int = 64,
) -> list[dict[str, Any]]:
    t0 = time.monotonic()

    def _read_segments() -> list[dict[str, Any]]:
        db = OfflineSessionLocal()
        out: list[dict[str, Any]] = []
        try:
            for m in matches:
                code = str(m.get("code") or "").strip()
                sd = str(m.get("start_date") or "")[:10]
                ed = str(m.get("end_date") or "")[:10]
                if not code or not sd or not ed:
                    continue
                rows = list(
                    db.scalars(
                        select(FundNavSnapshot)
                        .where(
                            FundNavSnapshot.fund_code == code,
                            FundNavSnapshot.nav_date >= datetime.fromisoformat(sd).date(),
                            FundNavSnapshot.nav_date <= datetime.fromisoformat(ed).date(),
                        )
                        .order_by(FundNavSnapshot.nav_date.asc())
                    )
                )
                if not rows:
                    continue
                if len(rows) > max_points_per_segment:
                    step = max(1, len(rows) // max_points_per_segment)
                    rows = rows[::step]
                points = [{"date": r.nav_date.isoformat(), "nav": float(r.nav)} for r in rows]
                out.append(
                    {
                        "code": code,
                        "start_date": sd,
                        "end_date": ed,
                        "similarity": float(m.get("similarity") or 0.0),
                        "fwd_return_5d": m.get("fwd_return_5d"),
                        "fwd_return_10d": m.get("fwd_return_10d"),
                        "fwd_return_20d": m.get("fwd_return_20d"),
                        "points": points,
                    }
                )
            return out
        finally:
            db.close()

    try:
        return run_serial_db_task(
            _read_segments,
            task_name="get_shadow_segments_for_matches",
            timeout_sec=40.0,
        )
    finally:
        _SHADOW_COSTS.append(time.monotonic() - t0)


def get_retrieval_metrics() -> dict[str, Any]:
    rt = list(_RETRIEVAL_COSTS)
    sh = list(_SHADOW_COSTS)
    return {
        "technical_retrieval": {
            "count": len(rt),
            "p50_sec": _percentile(rt, 0.5),
            "p95_sec": _percentile(rt, 0.95),
        },
        "shadow_segments": {
            "count": len(sh),
            "p50_sec": _percentile(sh, 0.5),
            "p95_sec": _percentile(sh, 0.95),
        },
    }
