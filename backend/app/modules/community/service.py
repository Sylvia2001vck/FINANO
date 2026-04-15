from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.exceptions import APIException
from app.modules.community.models import Post
from app.modules.community.schemas import PostCreate


def create_post(db: Session, user_id: int, payload: PostCreate) -> Post:
    post = Post(user_id=user_id, **payload.model_dump())
    db.add(post)
    db.commit()
    db.refresh(post)
    return post


def list_posts(db: Session) -> list[Post]:
    return list(db.scalars(select(Post).order_by(Post.created_at.desc())))


def like_post(db: Session, post_id: int) -> Post:
    post = db.get(Post, post_id)
    if not post:
        raise APIException(code=40001, message="帖子不存在", status_code=404)
    post.likes += 1
    db.commit()
    db.refresh(post)
    return post
