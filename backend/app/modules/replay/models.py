from __future__ import annotations

from sqlalchemy import ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin


class ReflectionEmbedding(Base, TimestampMixin):
    __tablename__ = "reflection_embeddings"
    __table_args__ = (UniqueConstraint("user_id", "note_id", name="uq_reflection_embedding_user_note"),)

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    note_id: Mapped[int] = mapped_column(ForeignKey("notes.id", ondelete="CASCADE"), index=True)
    model: Mapped[str] = mapped_column(String(64), nullable=False, default="text-embedding-v3")
    dim: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    embedding_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")


class TradeCurveFeature(Base, TimestampMixin):
    __tablename__ = "trade_curve_features"
    __table_args__ = (UniqueConstraint("user_id", "trade_id", name="uq_trade_curve_feature_user_trade"),)

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    trade_id: Mapped[int] = mapped_column(ForeignKey("trades.id", ondelete="CASCADE"), index=True)
    symbol: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    nav30_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    curve_signature: Mapped[str] = mapped_column(String(255), nullable=False, default="")
