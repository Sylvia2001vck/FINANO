from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import Date, DateTime, Float, Index, String, Text, UniqueConstraint, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class OfflineBase(DeclarativeBase):
    pass


class FundNavSnapshot(OfflineBase):
    __tablename__ = "fund_nav_snapshot"
    __table_args__ = (
        UniqueConstraint("fund_code", "nav_date", name="uq_fund_nav_snapshot_code_date"),
        Index("ix_fund_nav_snapshot_code_date", "fund_code", "nav_date"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    fund_code: Mapped[str] = mapped_column(String(10), nullable=False, index=True)
    nav_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    nav: Mapped[float] = mapped_column(Float, nullable=False)
    source: Mapped[str] = mapped_column(String(40), nullable=False, default="eastmoney_lsjz")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class OfflineJobStatus(OfflineBase):
    __tablename__ = "offline_job_status"
    __table_args__ = (UniqueConstraint("job_name", name="uq_offline_job_name"),)

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    job_name: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    run_count: Mapped[int] = mapped_column(default=0, nullable=False)
    fail_count: Mapped[int] = mapped_column(default=0, nullable=False)
    last_started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_duration_sec: Mapped[float | None] = mapped_column(Float, nullable=True)
    last_row_count: Mapped[int] = mapped_column(default=0, nullable=False)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
