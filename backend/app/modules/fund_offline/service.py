from __future__ import annotations

import logging
import threading
import time
from datetime import date, datetime, timedelta
from typing import Any, Callable

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from app.agent.fund_catalog import list_funds_catalog_only
from app.agent.kline_faiss_store import build_and_persist_index, get_index_version
from app.agent.kline_retriever import get_retrieval_metrics
from app.core.config import settings
from app.modules.fund_offline.models import FundNavSnapshot, OfflineBase, OfflineJobStatus
from app.modules.fund_offline.session import OfflineSessionLocal, offline_engine
from app.services.fund_data import fetch_lsjz_eastmoney_json_api_cached

logger = logging.getLogger(__name__)

_SYNC_JOB_NAME = "fund_nav_snapshot_sync"


def ensure_offline_schema() -> None:
    OfflineBase.metadata.create_all(bind=offline_engine)


def _iso_date(v: str, fallback: date) -> date:
    try:
        return datetime.fromisoformat(v[:10]).date()
    except Exception:
        return fallback


def _latest_date_by_code(db: Session, code: str) -> date | None:
    return db.scalar(select(func.max(FundNavSnapshot.nav_date)).where(FundNavSnapshot.fund_code == code))


def _pull_points(code: str, start_d: date, end_d: date) -> list[dict[str, Any]]:
    out = fetch_lsjz_eastmoney_json_api_cached(
        code,
        start_date=start_d.isoformat(),
        end_date=end_d.isoformat(),
        timeout=35.0,
    )
    return list(out.get("points_asc") or [])


def _upsert_nav_points(db: Session, code: str, rows: list[dict[str, Any]], source: str = "eastmoney_lsjz") -> int:
    payloads: list[dict[str, Any]] = []
    for p in rows:
        try:
            d = datetime.fromisoformat(str(p.get("date") or "")[:10]).date()
            nav = float(p.get("dwjz"))
        except Exception:
            continue
        if nav <= 0:
            continue
        payloads.append(
            {
                "fund_code": code,
                "nav_date": d,
                "nav": nav,
                "source": source,
                "updated_at": datetime.utcnow(),
            }
        )
    if not payloads:
        return 0
    dialect = str(getattr(getattr(db, "bind", None), "dialect", None).name if getattr(db, "bind", None) else "").lower()
    ins = pg_insert if dialect == "postgresql" else sqlite_insert
    stmt = ins(FundNavSnapshot).values(payloads)
    stmt = stmt.on_conflict_do_update(
        index_elements=["fund_code", "nav_date"],
        set_={
            "nav": stmt.excluded.nav,
            "source": stmt.excluded.source,
            "updated_at": stmt.excluded.updated_at,
        },
    )
    db.execute(stmt)
    return len(payloads)


def sync_fund_nav_snapshot(
    db: Session,
    *,
    full: bool = False,
    max_codes: int | None = None,
    rebuild_index: bool = True,
    progress_every: int = 100,
    progress_callback: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    ensure_offline_schema()
    started = datetime.utcnow()
    st = db.scalar(select(OfflineJobStatus).where(OfflineJobStatus.job_name == _SYNC_JOB_NAME).limit(1))
    if st is None:
        st = OfflineJobStatus(job_name=_SYNC_JOB_NAME, run_count=0, fail_count=0)
        db.add(st)
        db.flush()
    st.run_count = int(st.run_count or 0) + 1
    st.last_started_at = started
    st.last_error = None
    db.commit()

    max_n = int(max_codes or settings.fund_offline_sync_max_codes)
    codes = list_funds_catalog_only()
    if max_n > 0:
        codes = codes[:max_n]
    total_codes = len(codes)
    start_default = _iso_date(settings.fund_offline_sync_start_date, fallback=date.today() - timedelta(days=365 * 5))
    end_date = date.today()
    rows_upserted = 0
    code_done = 0
    progress_every = max(1, int(progress_every))

    try:
        if progress_callback:
            try:
                progress_callback(
                    {
                        "stage": "start",
                        "codes_total": total_codes,
                        "codes_processed": 0,
                        "rows_upserted": 0,
                        "elapsed_sec": 0.0,
                    }
                )
            except Exception:
                logger.debug("offline progress callback(start) failed", exc_info=True)
        for row in codes:
            code = str(row.get("code") or "").strip()
            if not code:
                continue
            if full:
                start_date = start_default
            else:
                latest = _latest_date_by_code(db, code)
                start_date = (latest - timedelta(days=4)) if latest else (end_date - timedelta(days=120))
            if start_date > end_date:
                start_date = end_date - timedelta(days=5)
            points = _pull_points(code, start_date, end_date)
            rows_upserted += _upsert_nav_points(db, code, points)
            code_done += 1
            if code_done % progress_every == 0:
                db.commit()
                if progress_callback:
                    try:
                        progress_callback(
                            {
                                "stage": "running",
                                "codes_total": total_codes,
                                "codes_processed": code_done,
                                "rows_upserted": rows_upserted,
                                "elapsed_sec": round((datetime.utcnow() - started).total_seconds(), 3),
                                "last_code": code,
                            }
                        )
                    except Exception:
                        logger.debug("offline progress callback(running) failed", exc_info=True)
        db.commit()
        finished = datetime.utcnow()
        duration = (finished - started).total_seconds()
        st = db.scalar(select(OfflineJobStatus).where(OfflineJobStatus.job_name == _SYNC_JOB_NAME).limit(1))
        if st:
            st.last_finished_at = finished
            st.last_success_at = finished
            st.last_duration_sec = duration
            st.last_row_count = rows_upserted
            st.last_error = None
            db.commit()
        index_result: dict[str, Any] | None = None
        if rebuild_index:
            t_idx = time.monotonic()
            index_result = build_and_persist_index(max_codes=max_n)
            index_result["duration_sec"] = round(time.monotonic() - t_idx, 4)
        if progress_callback:
            try:
                progress_callback(
                    {
                        "stage": "done",
                        "codes_total": total_codes,
                        "codes_processed": code_done,
                        "rows_upserted": rows_upserted,
                        "elapsed_sec": round(duration, 3),
                    }
                )
            except Exception:
                logger.debug("offline progress callback(done) failed", exc_info=True)
        return {
            "ok": True,
            "full": full,
            "codes_processed": code_done,
            "rows_upserted": rows_upserted,
            "duration_sec": round(duration, 3),
            "started_at": started.isoformat(),
            "finished_at": finished.isoformat(),
            "index": index_result,
        }
    except Exception as e:  # noqa: BLE001
        db.rollback()
        finished = datetime.utcnow()
        duration = (finished - started).total_seconds()
        if progress_callback:
            try:
                progress_callback(
                    {
                        "stage": "error",
                        "codes_total": total_codes,
                        "codes_processed": code_done,
                        "rows_upserted": rows_upserted,
                        "elapsed_sec": round(duration, 3),
                        "error": f"{type(e).__name__}: {e}",
                    }
                )
            except Exception:
                logger.debug("offline progress callback(error) failed", exc_info=True)
        st = db.scalar(select(OfflineJobStatus).where(OfflineJobStatus.job_name == _SYNC_JOB_NAME).limit(1))
        if st:
            st.fail_count = int(st.fail_count or 0) + 1
            st.last_finished_at = finished
            st.last_duration_sec = duration
            st.last_error = f"{type(e).__name__}: {e}"
            db.commit()
        logger.exception("offline fund nav sync failed")
        return {
            "ok": False,
            "full": full,
            "codes_processed": code_done,
            "rows_upserted": rows_upserted,
            "duration_sec": round(duration, 3),
            "error": f"{type(e).__name__}: {e}",
        }


def _need_full_refresh(now_dt: datetime) -> bool:
    return int(now_dt.weekday()) == int(settings.fund_offline_sync_full_weekday)


def start_offline_sync_scheduler():
    if not settings.fund_offline_enabled:
        return None, None
    ensure_offline_schema()
    stop_event = threading.Event()

    def _worker():
        interval = max(1800, int(settings.fund_offline_sync_interval_sec))
        while not stop_event.is_set():
            db = OfflineSessionLocal()
            try:
                full = _need_full_refresh(datetime.now())
                sync_fund_nav_snapshot(db, full=full, rebuild_index=True)
            except Exception:
                logger.exception("offline scheduler worker failed")
            finally:
                db.close()
            stop_event.wait(interval)

    t = threading.Thread(target=_worker, daemon=True, name="fund-offline-sync-scheduler")
    t.start()
    return stop_event, t


def get_offline_status(db: Session) -> dict[str, Any]:
    ensure_offline_schema()
    row = db.scalar(select(OfflineJobStatus).where(OfflineJobStatus.job_name == _SYNC_JOB_NAME).limit(1))
    total_rows = db.scalar(select(func.count()).select_from(FundNavSnapshot)) or 0
    total_codes = db.scalar(select(func.count(func.distinct(FundNavSnapshot.fund_code)))) or 0
    latest = db.scalar(select(func.max(FundNavSnapshot.nav_date)))
    run_count = int(row.run_count) if row else 0
    fail_count = int(row.fail_count) if row else 0
    success_rate = float(max(0.0, (run_count - fail_count) / run_count)) if run_count > 0 else None
    return {
        "enabled": bool(settings.fund_offline_enabled),
        "db_url": settings.fund_offline_db_url,
        "sync_interval_sec": int(settings.fund_offline_sync_interval_sec),
        "max_codes": int(settings.fund_offline_sync_max_codes),
        "window_start": settings.fund_offline_sync_start_date,
        "rows_total": int(total_rows),
        "codes_total": int(total_codes),
        "latest_nav_date": latest.isoformat() if latest else None,
        "job": {
            "run_count": run_count,
            "fail_count": fail_count,
            "success_rate": success_rate,
            "last_started_at": row.last_started_at.isoformat() if row and row.last_started_at else None,
            "last_finished_at": row.last_finished_at.isoformat() if row and row.last_finished_at else None,
            "last_success_at": row.last_success_at.isoformat() if row and row.last_success_at else None,
            "last_duration_sec": float(row.last_duration_sec) if row and row.last_duration_sec is not None else None,
            "last_row_count": int(row.last_row_count) if row else 0,
            "last_error": row.last_error if row else None,
        },
        "kline_index": get_index_version(),
        "runtime_metrics": get_retrieval_metrics(),
    }
