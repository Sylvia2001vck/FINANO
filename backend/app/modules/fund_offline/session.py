from __future__ import annotations

from pathlib import Path
from typing import Generator

from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import settings


def _ensure_sqlite_parent(url: str) -> None:
    if not url.startswith("sqlite:///"):
        return
    db_path = url.replace("sqlite:///", "", 1).strip()
    if not db_path or db_path == ":memory:":
        return
    p = Path(db_path)
    if not p.is_absolute():
        p = Path.cwd() / p
    p.parent.mkdir(parents=True, exist_ok=True)


_ensure_sqlite_parent(settings.fund_offline_db_url)
_connect_args = (
    {
        "check_same_thread": False,
        "timeout": 30,
    }
    if settings.fund_offline_db_url.startswith("sqlite")
    else {}
)

offline_engine = create_engine(
    settings.fund_offline_db_url,
    future=True,
    pool_pre_ping=True,
    connect_args=_connect_args,
)
OfflineSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=offline_engine, future=True)


if settings.fund_offline_db_url.startswith("sqlite"):

    @event.listens_for(offline_engine, "connect")
    def _set_offline_sqlite_pragma(dbapi_conn, _):  # noqa: ANN001
        cur = dbapi_conn.cursor()
        try:
            cur.execute("PRAGMA journal_mode=WAL;")
            cur.execute("PRAGMA busy_timeout=30000;")
            cur.execute("PRAGMA synchronous=NORMAL;")
        finally:
            cur.close()


def get_offline_db() -> Generator[Session, None, None]:
    db = OfflineSessionLocal()
    try:
        yield db
    finally:
        db.close()
