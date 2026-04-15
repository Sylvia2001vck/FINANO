from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.responses import success_response
from app.db.session import get_db
from app.modules.hot.schemas import HotNewsRead
from app.modules.hot.service import list_hot_news


router = APIRouter(prefix="/hot", tags=["hot"])


@router.get("")
def get_hot_news(db: Session = Depends(get_db)):
    items = list_hot_news(db)
    data = [HotNewsRead.model_validate(item).model_dump() for item in items]
    return success_response(data=data)
