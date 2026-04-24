from datetime import date

from sqlalchemy import Date, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin


class User(Base, TimestampMixin):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    username: Mapped[str] = mapped_column(String(50), unique=True, index=True, nullable=False)
    email: Mapped[str] = mapped_column(String(100), unique=True, index=True, nullable=False)
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)

    mbti: Mapped[str | None] = mapped_column(String(4), nullable=True)
    birth_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    birth_time_slot: Mapped[str | None] = mapped_column(String(16), nullable=True)
    layout_facing: Mapped[str | None] = mapped_column(String(1), nullable=True)
    risk_preference: Mapped[int | None] = mapped_column(Integer, nullable=True)

    fbti_profile: Mapped[str | None] = mapped_column(String(32), nullable=True)
    user_wuxing: Mapped[str | None] = mapped_column(String(32), nullable=True)

    trades = relationship("Trade", back_populates="user", cascade="all, delete-orphan")
    notes = relationship("Note", back_populates="user", cascade="all, delete-orphan")
    posts = relationship("Post", back_populates="user", cascade="all, delete-orphan")
    agent_fund_picks = relationship("UserAgentFund", back_populates="user", cascade="all, delete-orphan")


class UserAgentFund(Base, TimestampMixin):
    """MAFB / 基金池：用户自选 6 位基金代码（仅存代码，展示时向全市场目录解析）。"""

    __tablename__ = "user_agent_funds"
    __table_args__ = (UniqueConstraint("user_id", "fund_code", name="uq_user_agent_fund_code"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False)
    fund_code: Mapped[str] = mapped_column(String(6), nullable=False, index=True)

    user = relationship("User", back_populates="agent_fund_picks")
