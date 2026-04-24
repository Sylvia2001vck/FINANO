from __future__ import annotations

import json
import logging
import math
import threading
from datetime import date, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.agent.fund_catalog import list_funds_catalog_only
from app.core.config import settings
from app.db.session import SessionLocal
from app.modules.fund_nav.models import FundDailySnapshot
from app.services.fund_data import fetch_fund_nav_history
from app.services.fund_fundamental import fetch_fund_fundamental_snapshot

logger = logging.getLogger(__name__)

_LATEST_CACHE: dict[str, tuple[float, dict[str, Any]]] = {}
_LATEST_CACHE_LOCK = threading.Lock()


def _calc_sharpe(returns: list[float]) -> float | None:
    if len(returns) < 30:
        return None
    mean = sum(returns) / len(returns)
    var = sum((x - mean) ** 2 for x in returns) / max(1, len(returns) - 1)
    std = math.sqrt(var)
    if std <= 1e-9:
        return None
    return float((mean / std) * math.sqrt(252.0))


def _calc_mdd(nav_vals: list[float]) -> float | None:
    if len(nav_vals) < 10:
        return None
    peak = nav_vals[0]
    mdd = 0.0
    for v in nav_vals:
        if v > peak:
            peak = v
        if peak > 0:
            mdd = max(mdd, (peak - v) / peak)
    return float(mdd)


def _calc_vol(returns: list[float]) -> float | None:
    if len(returns) < 20:
        return None
    mean = sum(returns) / len(returns)
    var = sum((x - mean) ** 2 for x in returns) / max(1, len(returns) - 1)
    return float(math.sqrt(var) * math.sqrt(252.0))


def _calc_momentum(nav_vals: list[float], lb: int = 60) -> float | None:
    if len(nav_vals) < 12:
        return None
    use_lb = min(lb, len(nav_vals) - 1)
    base = float(nav_vals[-(use_lb + 1)] or 0.0)
    if base <= 0:
        return None
    return float(nav_vals[-1] / base - 1.0)


def _build_snapshot_blob(code: str, name: str, risk_rating: int | None = None) -> dict[str, Any]:
    nav_rows = fetch_fund_nav_history(code, days=280, timeout=12.0)
    nav_vals = [float(x.get("nav") or 0.0) for x in nav_rows if x.get("nav") is not None]
    rets = [float(x.get("daily_return") or 0.0) for x in nav_rows if x.get("daily_return") is not None]
    sharpe = _calc_sharpe(rets)
    mdd = _calc_mdd(nav_vals)
    vol = _calc_vol(rets)
    mom = _calc_momentum(nav_vals, lb=60)

    snap = fetch_fund_fundamental_snapshot(code)
    out: dict[str, Any] = {
        "code": code,
        "name": name,
        "risk_rating": int(risk_rating or snap.get("risk_rating") or 3),
        "nav_points_lookback": len(nav_rows),
        "momentum_60d": mom,
        "volatility_60d": vol,
        "sharpe_3y": sharpe,
        "max_drawdown_3y": mdd,
    }
    out.update(snap or {})
    return out


def refresh_fund_snapshot_batch(db: Session, *, force: bool = False) -> dict[str, Any]:
    today = date.today()
    max_codes = int(settings.fund_snapshot_daily_max_codes)
    codes = list_funds_catalog_only()
    if max_codes > 0:
        codes = codes[: max_codes]
    if not force:
        existed = db.scalar(select(FundDailySnapshot.id).where(FundDailySnapshot.batch_date == today).limit(1))
        if existed:
            return {"ok": True, "batch_date": today.isoformat(), "refreshed": 0, "skipped": True}

    refreshed = 0
    for row in codes:
        code = str(row.get("code") or "").strip()
        if not code:
            continue
        name = str(row.get("name") or "")
        risk_rating = row.get("risk_rating")
        try:
            blob = _build_snapshot_blob(code, name, int(risk_rating) if isinstance(risk_rating, (int, float)) else None)
        except Exception:
            logger.debug("snapshot build failed: %s", code, exc_info=True)
            continue
        item = db.scalar(
            select(FundDailySnapshot).where(FundDailySnapshot.fund_code == code, FundDailySnapshot.batch_date == today)
        )
        if item is None:
            item = FundDailySnapshot(fund_code=code, fund_name=name, batch_date=today)
            db.add(item)
        item.fund_name = name
        item.nav_points = int(blob.get("nav_points_lookback") or 0)
        item.aum_billion = blob.get("aum_billion")
        item.sharpe_3y = blob.get("sharpe_3y")
        item.max_drawdown_3y = blob.get("max_drawdown_3y")
        item.momentum_60d = blob.get("momentum_60d")
        item.volatility_60d = blob.get("volatility_60d")
        item.risk_rating = blob.get("risk_rating")
        item.manager_score = blob.get("manager_score")
        item.stock_top10_concentration = blob.get("stock_top10_concentration")
        item.fund_blob_json = json.dumps(blob, ensure_ascii=False)
        refreshed += 1
        if refreshed % 100 == 0:
            db.flush()
    db.commit()
    return {"ok": True, "batch_date": today.isoformat(), "refreshed": refreshed, "skipped": False}


def _read_latest_snapshot(db: Session, code: str) -> dict[str, Any] | None:
    row = db.scalar(
        select(FundDailySnapshot)
        .where(FundDailySnapshot.fund_code == code)
        .order_by(FundDailySnapshot.batch_date.desc(), FundDailySnapshot.updated_at.desc())
        .limit(1)
    )
    if not row:
        return None
    try:
        blob = json.loads(row.fund_blob_json or "{}")
    except Exception:
        blob = {}
    if not isinstance(blob, dict):
        blob = {}
    blob.setdefault("code", row.fund_code)
    blob.setdefault("name", row.fund_name)
    blob.setdefault("nav_points_lookback", row.nav_points)
    return blob


def get_latest_fund_snapshot_cached(code: str) -> dict[str, Any] | None:
    c = str(code or "").strip()
    if not c:
        return None
    now_ts = datetime.utcnow().timestamp()
    with _LATEST_CACHE_LOCK:
        hit = _LATEST_CACHE.get(c)
        if hit and now_ts - hit[0] < 180.0:
            return dict(hit[1])
    db = SessionLocal()
    try:
        blob = _read_latest_snapshot(db, c)
        if blob:
            with _LATEST_CACHE_LOCK:
                _LATEST_CACHE[c] = (now_ts, dict(blob))
        return blob
    except Exception:
        logger.debug("read snapshot failed: %s", c, exc_info=True)
        return None
    finally:
        db.close()


def bootstrap_fund_snapshot(db: Session) -> None:
    if not settings.fund_snapshot_scheduler_enabled:
        return
    try:
        refresh_fund_snapshot_batch(db, force=False)
    except Exception:
        logger.exception("fund snapshot bootstrap failed")


def get_fund_snapshot_status(db: Session) -> dict[str, Any]:
    today = date.today()
    latest = db.scalar(
        select(FundDailySnapshot)
        .order_by(FundDailySnapshot.batch_date.desc(), FundDailySnapshot.updated_at.desc())
        .limit(1)
    )
    today_count = db.scalar(select(func.count()).select_from(FundDailySnapshot).where(FundDailySnapshot.batch_date == today))
    target = int(settings.fund_snapshot_daily_max_codes)
    progress = float(today_count) / float(target) if target > 0 else 0.0
    return {
        "enabled": bool(settings.fund_snapshot_scheduler_enabled),
        "refresh_interval_sec": int(settings.fund_snapshot_refresh_interval_sec),
        "daily_target_codes": target,
        "today_count": int(today_count or 0),
        "today_progress": round(progress, 4),
        "latest_batch_date": latest.batch_date.isoformat() if latest else None,
        "latest_updated_at": latest.updated_at.isoformat() if latest else None,
        "latest_code": latest.fund_code if latest else None,
    }


def start_fund_snapshot_scheduler(session_factory):
    if not settings.fund_snapshot_scheduler_enabled:
        return None, None
    stop_event = threading.Event()

    def _worker():
        interval = max(1800, int(settings.fund_snapshot_refresh_interval_sec))
        while not stop_event.is_set():
            db = session_factory()
            try:
                refresh_fund_snapshot_batch(db, force=False)
            except Exception:
                logger.exception("fund snapshot scheduler refresh failed")
            finally:
                db.close()
            stop_event.wait(interval)

    t = threading.Thread(target=_worker, daemon=True, name="fund-snapshot-scheduler")
    t.start()
    return stop_event, t
