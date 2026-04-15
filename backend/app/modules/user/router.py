from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.responses import success_response
from app.core.security import create_access_token, get_current_user
from app.db.session import get_db
from app.modules.user.schemas import TokenResponse, UserCreate, UserLogin, UserRead
from app.modules.user.service import authenticate_user, create_user


router = APIRouter(prefix="/auth", tags=["auth"])
user_router = APIRouter(prefix="/users", tags=["users"])


@router.post("/register")
def register(payload: UserCreate, db: Session = Depends(get_db)):
    user = create_user(db, payload)
    token = create_access_token(str(user.id))
    data = TokenResponse(access_token=token, user=user)
    return success_response(data=data.model_dump(), message="注册成功")


@router.post("/login")
def login(payload: UserLogin, db: Session = Depends(get_db)):
    user = authenticate_user(db, payload.email, payload.password)
    token = create_access_token(str(user.id))
    data = TokenResponse(access_token=token, user=user)
    return success_response(data=data.model_dump(), message="登录成功")


@user_router.get("/me")
def me(current_user=Depends(get_current_user)):
    return success_response(data=UserRead.model_validate(current_user).model_dump())
