from datetime import date

from sqlalchemy import Date, Integer, String
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
    layout_facing: Mapped[str | None] = mapped_column(String(1), nullable=True)
    risk_preference: Mapped[int | None] = mapped_column(Integer, nullable=True)

    fbti_profile: Mapped[str | None] = mapped_column(String(32), nullable=True)
    user_wuxing: Mapped[str | None] = mapped_column(String(32), nullable=True)

    trades = relationship("Trade", back_populates="user", cascade="all, delete-orphan")
    notes = relationship("Note", back_populates="user", cascade="all, delete-orphan")
    posts = relationship("Post", back_populates="user", cascade="all, delete-orphan")
