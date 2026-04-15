from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.responses import success_response
from app.core.security import get_current_user
from app.db.session import get_db
from app.modules.trade.service import get_user_trade, summarize_trades
from app.services.qwen_finance import analyze_trade


router = APIRouter(prefix="/ai", tags=["ai"])


@router.post("/analyze/{trade_id}")
def analyze(trade_id: int, current_user=Depends(get_current_user), db: Session = Depends(get_db)):
    trade = get_user_trade(db, current_user.id, trade_id)
    stats = summarize_trades(db, current_user.id)
    result = analyze_trade(
        {
            "symbol": trade.symbol,
            "name": trade.name,
            "direction": trade.direction.value,
            "trade_date": trade.trade_date.isoformat(),
            "amount": float(trade.amount),
            "fee": float(trade.fee),
            "profit": float(trade.profit),
            "notes": trade.notes,
        },
        stats,
    )
    return success_response(data=result, message="AI 分析完成")
