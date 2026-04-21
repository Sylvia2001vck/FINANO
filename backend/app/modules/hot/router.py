from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.responses import success_response
from app.db.session import get_db
from app.modules.hot.schemas import HotNewsSnapshotRead
from app.modules.hot.service import list_hot_news_snapshot


router = APIRouter(prefix="/hot", tags=["hot"])


@router.get("")
def get_hot_news(db: Session = Depends(get_db)):
    payload = list_hot_news_snapshot(db)
    data = HotNewsSnapshotRead.model_validate(payload).model_dump()
    return success_response(data=data)
