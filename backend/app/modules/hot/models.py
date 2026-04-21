from datetime import datetime

from sqlalchemy import DateTime, Float, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class HotNews(Base):
    __tablename__ = "hot_news"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    source: Mapped[str] = mapped_column(String(50), nullable=False)
    publish_time: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)


class HotNewsSnapshot(Base):
    __tablename__ = "hot_news_snapshot"
    __table_args__ = (
        UniqueConstraint("batch_time", "rank", name="uq_hot_news_snapshot_batch_rank"),
        UniqueConstraint("batch_time", "news_id", name="uq_hot_news_snapshot_batch_news"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    news_id: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    source: Mapped[str] = mapped_column(String(80), nullable=False)
    rank: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    batch_time: Mapped[datetime] = mapped_column(DateTime, nullable=False, index=True)
    publish_time: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    sentiment_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
