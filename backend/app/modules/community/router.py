from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.responses import success_response
from app.core.security import get_current_user
from app.db.session import get_db
from app.modules.community.schemas import PostCreate, PostRead
from app.modules.community.service import create_post, like_post, list_posts

router = APIRouter(prefix="/community/posts", tags=["community"])


@router.get("")
def get_posts(db: Session = Depends(get_db)):
    posts = list_posts(db)
    data = [PostRead.model_validate(post).model_dump() for post in posts]
    return success_response(data=data)


@router.post("")
def add_post(payload: PostCreate, current_user=Depends(get_current_user), db: Session = Depends(get_db)):
    post = create_post(db, current_user.id, payload)
    return success_response(data=PostRead.model_validate(post).model_dump(), message="帖子发布成功")


@router.post("/{post_id}/like")
def add_like(post_id: int, db: Session = Depends(get_db)):
    post = like_post(db, post_id)
    return success_response(data=PostRead.model_validate(post).model_dump(), message="点赞成功")
