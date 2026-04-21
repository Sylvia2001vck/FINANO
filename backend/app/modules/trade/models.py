import enum
from datetime import date
from decimal import Decimal

from sqlalchemy import Date, Enum, ForeignKey, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin


class TradeDirection(str, enum.Enum):
    buy = "buy"
    sell = "sell"


class Trade(Base, TimestampMixin):
    __tablename__ = "trades"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    trade_date: Mapped[date] = mapped_column(Date, nullable=False)
    buy_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    sell_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    sell_amount: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    symbol: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(50), nullable=False)
    direction: Mapped[TradeDirection] = mapped_column(Enum(TradeDirection), nullable=False)
    quantity: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    price: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    fee: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False, default=0)
    profit: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False, default=0)
    platform: Mapped[str] = mapped_column(String(20), nullable=False, default="manual")
    notes: Mapped[str | None] = mapped_column(Text)

    user = relationship("User", back_populates="trades")
    review_notes = relationship("Note", back_populates="trade")
