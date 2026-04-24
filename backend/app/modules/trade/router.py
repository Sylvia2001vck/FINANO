from fastapi import APIRouter, Depends, File, Query, UploadFile
from sqlalchemy.orm import Session

from app.agent.fund_catalog import get_fund_by_code, list_funds_catalog_window
from app.core.exceptions import APIException
from app.core.responses import success_response
from app.core.security import get_current_user
from app.db.session import get_db
from app.modules.trade.schemas import TradeCreate, TradeCurveResponse, TradeRead
from app.modules.trade.service import (
    create_trade,
    create_trades,
    delete_trade,
    get_trade_curve_with_markers,
    list_user_trades,
    summarize_trades,
)
from app.services.ocr import recognize_statement


router = APIRouter(prefix="/trades", tags=["trades"])


@router.get("/securities/search")
def search_securities(
    q: str = Query("", max_length=80),
    limit: int = Query(30, ge=1, le=100),
    _user=Depends(get_current_user),
):
    """按代码/名称子串搜索基金目录（用于交易表单联想）。"""
    items, total = list_funds_catalog_window(limit=limit, offset=0, query=q.strip() or None)
    slim = [{"code": str(x.get("code", "")), "name": str(x.get("name", ""))} for x in items if x.get("code")]
    return success_response(data={"items": slim, "total": total}, message="ok")


@router.get("/securities/lookup/{code}")
def lookup_security(code: str, _user=Depends(get_current_user)):
    """6 位代码反查名称（不打实时估值）。"""
    hit = get_fund_by_code(code.strip(), include_live=False)
    if not hit:
        raise APIException(code=20003, message="未找到该证券代码", status_code=404)
    return success_response(
        data={"code": str(hit.get("code", "")).strip(), "name": str(hit.get("name", "")).strip()},
        message="ok",
    )


@router.get("")
def get_trades(current_user=Depends(get_current_user), db: Session = Depends(get_db)):
    trades = list_user_trades(db, current_user.id)
    data = [TradeRead.model_validate(trade).model_dump() for trade in trades]
    return success_response(data=data)


@router.post("")
def add_trade(payload: TradeCreate, current_user=Depends(get_current_user), db: Session = Depends(get_db)):
    trade, dedup_hit = create_trade(db, current_user.id, payload)
    return success_response(
        data={
            "trade": TradeRead.model_validate(trade).model_dump(),
            "dedup_hit": bool(dedup_hit),
        },
        message="交易记录创建成功",
    )


@router.delete("/{trade_id}")
def remove_trade(trade_id: int, current_user=Depends(get_current_user), db: Session = Depends(get_db)):
    delete_trade(db, current_user.id, trade_id)
    return success_response(data={"id": trade_id}, message="交易记录已删除")


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


@router.get("/curve/{symbol}")
def trade_curve(symbol: str, current_user=Depends(get_current_user), db: Session = Depends(get_db)):
    data = get_trade_curve_with_markers(db, current_user.id, symbol)
    return success_response(data=TradeCurveResponse.model_validate(data).model_dump())
