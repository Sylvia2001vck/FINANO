from __future__ import annotations

from sqlalchemy import Boolean, Float, ForeignKey, Index, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin


class UserMafbReportAsset(Base, TimestampMixin):
    __tablename__ = "user_mafb_report_assets"
    __table_args__ = (
        Index("ix_user_mafb_report_assets_user_created", "user_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False)
    fund_code: Mapped[str] = mapped_column(String(10), nullable=False, default="")
    include_fbti: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    title: Mapped[str] = mapped_column(String(120), nullable=False, default="")
    weighted_total: Mapped[float | None] = mapped_column(Float, nullable=True)
    verdict: Mapped[str | None] = mapped_column(String(32), nullable=True)
    final_report_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")


class UserMafbReportPin(Base, TimestampMixin):
    __tablename__ = "user_mafb_report_pins"
    __table_args__ = (
        UniqueConstraint("user_id", "report_id", name="uq_user_mafb_report_pin"),
        Index("ix_user_mafb_report_pins_user", "user_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False)
    report_id: Mapped[int] = mapped_column(ForeignKey("user_mafb_report_assets.id", ondelete="CASCADE"), index=True, nullable=False)
