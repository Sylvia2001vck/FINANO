"""FBTI 测试与画像：/api/v1/user/fbti/*"""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.exceptions import APIException
from app.core.responses import success_response
from app.core.security import get_current_user
from app.db.session import get_db
from app.modules.user.models import User
from app.modules.user.schemas import UserRead
from app.services.bazi_wuxing import compute_today_wuxing_preference, fuse_wuxing
from app.services.fbti_engine import match_archetype, score_fbti_code

router = APIRouter(prefix="/user", tags=["fbti"])


class FbtiTestSubmit(BaseModel):
    answers: list[str] = Field(..., min_length=8, max_length=8, description="8 道题，每项 A 或 B")
    birth_date: date | None = None


@router.post("/fbti/test")
def submit_fbti_test(
    payload: FbtiTestSubmit,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    code = score_fbti_code(payload.answers)
    arch = match_archetype(code)
    bd = payload.birth_date
    user = db.get(User, current_user.id)
    if not user:
        raise APIException(code=10001, status_code=404)

    bazi_el = ""
    if bd is not None:
        user.birth_date = bd
        bazi_el = compute_today_wuxing_preference(bd)
    elif user.birth_date:
        bazi_el = compute_today_wuxing_preference(user.birth_date)

    awx = str(arch.get("wuxing") or "")
    merged = fuse_wuxing(awx, bazi_el) if bazi_el else awx

    user.fbti_profile = code[:32]
    user.user_wuxing = merged[:32]
    db.add(user)
    db.commit()
    db.refresh(user)

    return success_response(
        data={
            "fbti_code": arch.get("matched_code", arch["code"]),
            "fbti_profile": user.fbti_profile,
            "archetype": {
                "code": arch["code"],
                "name": arch["name"],
                "wuxing": arch["wuxing"],
                "tags": arch.get("tags"),
                "blurb": arch.get("blurb"),
                "nearest_archetype": arch.get("nearest_archetype", False),
            },
            "bazi_wuxing_hint": bazi_el,
            "user_wuxing": user.user_wuxing,
            "user": UserRead.model_validate(user).model_dump(),
        },
        message="FBTI 已保存",
    )


@router.get("/fbti/profile")
def get_fbti_profile(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    user = db.get(User, current_user.id)
    if not user:
        raise APIException(code=10001, status_code=404)
    arch = None
    if user.fbti_profile:
        arch = match_archetype(user.fbti_profile)
    return success_response(
        data={
            "fbti_profile": user.fbti_profile,
            "user_wuxing": user.user_wuxing,
            "birth_date": user.birth_date.isoformat() if user.birth_date else None,
            "archetype": arch,
        },
        message="ok",
    )
