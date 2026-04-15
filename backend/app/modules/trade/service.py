import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.exceptions import APIException
from app.modules.trade.models import Trade
from app.modules.trade.schemas import TradeCreate
from app.services.ta_lib import calculate_trade_stats


def create_trade(db: Session, user_id: int, payload: TradeCreate) -> Trade:
    trade = Trade(user_id=user_id, **payload.model_dump())
    db.add(trade)
    db.commit()
    db.refresh(trade)
    return trade


def create_trades(db: Session, user_id: int, trades: list[dict]) -> list[Trade]:
    created = []
    for item in trades:
        payload = TradeCreate.model_validate(item)
        created.append(create_trade(db, user_id, payload))
    return created


def list_user_trades(db: Session, user_id: int) -> list[Trade]:
    return list(
        db.scalars(
            select(Trade).where(Trade.user_id == user_id).order_by(Trade.trade_date.desc(), Trade.id.desc())
        )
    )


def get_user_trade(db: Session, user_id: int, trade_id: int) -> Trade:
    trade = db.scalar(select(Trade).where(Trade.id == trade_id, Trade.user_id == user_id))
    if not trade:
        raise APIException(code=20002, message="交易记录不存在", status_code=404)
    return trade


def summarize_trades(db: Session, user_id: int) -> dict:
    trades = list_user_trades(db, user_id)
    if not trades:
        return calculate_trade_stats(pd.DataFrame())

    records = [
        {
            "profit": float(trade.profit),
            "trade_date": trade.trade_date.isoformat(),
            "amount": float(trade.amount),
        }
        for trade in trades
    ]
    return calculate_trade_stats(pd.DataFrame(records))
