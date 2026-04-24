from __future__ import annotations

from datetime import date

from sqlalchemy import Date, Float, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin


class FundDailySnapshot(Base, TimestampMixin):
    __tablename__ = "fund_daily_snapshot"
    __table_args__ = (UniqueConstraint("fund_code", "batch_date", name="uq_fund_snapshot_code_day"),)

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    fund_code: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    fund_name: Mapped[str] = mapped_column(String(120), nullable=False, default="")
    batch_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    nav_points: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    aum_billion: Mapped[float | None] = mapped_column(Float, nullable=True)
    sharpe_3y: Mapped[float | None] = mapped_column(Float, nullable=True)
    max_drawdown_3y: Mapped[float | None] = mapped_column(Float, nullable=True)
    momentum_60d: Mapped[float | None] = mapped_column(Float, nullable=True)
    volatility_60d: Mapped[float | None] = mapped_column(Float, nullable=True)
    risk_rating: Mapped[int | None] = mapped_column(Integer, nullable=True)
    manager_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    stock_top10_concentration: Mapped[float | None] = mapped_column(Float, nullable=True)
    fund_blob_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
