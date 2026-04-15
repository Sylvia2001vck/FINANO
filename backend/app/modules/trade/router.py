from fastapi import APIRouter, Depends, File, UploadFile
from sqlalchemy.orm import Session

from app.core.responses import success_response
from app.core.security import get_current_user
from app.db.session import get_db
from app.modules.trade.schemas import TradeCreate, TradeRead
from app.modules.trade.service import create_trade, create_trades, list_user_trades, summarize_trades
from app.services.ocr import recognize_statement


router = APIRouter(prefix="/trades", tags=["trades"])


@router.get("")
def get_trades(current_user=Depends(get_current_user), db: Session = Depends(get_db)):
    trades = list_user_trades(db, current_user.id)
    data = [TradeRead.model_validate(trade).model_dump() for trade in trades]
    return success_response(data=data)


@router.post("")
def add_trade(payload: TradeCreate, current_user=Depends(get_current_user), db: Session = Depends(get_db)):
    trade = create_trade(db, current_user.id, payload)
    return success_response(data=TradeRead.model_validate(trade).model_dump(), message="交易记录创建成功")


@router.post("/import/ocr")
async def import_by_ocr(
    file: UploadFile = File(...),
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    content = await file.read()
    trades = recognize_statement(content)
    created_trades = create_trades(db, current_user.id, trades)
    data = [TradeRead.model_validate(trade).model_dump() for trade in created_trades]
    return success_response(data=data, message="交割单识别并导入成功")


@router.get("/stats/summary")
def stats_summary(current_user=Depends(get_current_user), db: Session = Depends(get_db)):
    return success_response(data=summarize_trades(db, current_user.id))
