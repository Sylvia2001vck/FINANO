from __future__ import annotations

from pathlib import Path
from typing import Generator

from sqlalchemy import create_engine
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
_connect_args = {"check_same_thread": False} if settings.fund_offline_db_url.startswith("sqlite") else {}

offline_engine = create_engine(
    settings.fund_offline_db_url,
    future=True,
    pool_pre_ping=True,
    connect_args=_connect_args,
)
OfflineSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=offline_engine, future=True)


def get_offline_db() -> Generator[Session, None, None]:
    db = OfflineSessionLocal()
    try:
        yield db
    finally:
        db.close()
