from datetime import date

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.core.exceptions import APIException
from app.core.security import get_password_hash, verify_password
from app.modules.user.models import User
from app.modules.user.schemas import UserCreate


def get_user_by_email(db: Session, email: str) -> User | None:
    return db.scalar(select(User).where(User.email == email))


def create_user(db: Session, payload: UserCreate) -> User:
    exists = db.scalar(select(User).where(or_(User.email == payload.email, User.username == payload.username)))
    if exists:
        raise APIException(code=40001, message="用户名或邮箱已存在", status_code=409)

    user = User(
        username=payload.username,
        email=payload.email,
        hashed_password=get_password_hash(payload.password),
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def authenticate_user(db: Session, email: str, password: str) -> User:
    user = get_user_by_email(db, email)
    if not user:
        raise APIException(code=10001, status_code=404)
    if not verify_password(password, user.hashed_password):
        raise APIException(code=10002, status_code=401)
    return user


def update_investor_profile(
    db: Session,
    user_id: int,
    *,
    mbti: str | None,
    birth_date: date | None,
    birth_time_slot: str | None,
    layout_facing: str | None,
    risk_preference: int | None,
) -> User:
    user = db.get(User, user_id)
    if not user:
        raise APIException(code=10001, status_code=404)
    if mbti is not None:
        user.mbti = mbti.upper()[:4] if mbti else None
    if birth_date is not None:
        user.birth_date = birth_date
    if birth_time_slot is not None:
        user.birth_time_slot = str(birth_time_slot).strip().upper()[:16] if birth_time_slot else None
    if layout_facing is not None:
        user.layout_facing = layout_facing.upper()[:1] if layout_facing else None
    if risk_preference is not None:
        user.risk_preference = risk_preference
    db.commit()
    db.refresh(user)
    return user
