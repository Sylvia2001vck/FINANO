from decimal import Decimal

import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.exceptions import APIException
from app.modules.trade.models import Trade, TradeDirection
from app.modules.trade.schemas import TradeCreate
from app.services.ta_lib import calculate_trade_stats


def _round_money(x: float, nd: int = 2) -> float:
    return round(float(x), nd)


def normalize_trade_create_payload(payload: TradeCreate) -> dict:
    """
    将 TradeCreate 转为 Trade ORM 可接受的字段字典。
    新版：buy_date + amount(买入毛额) + fee_percent + 单价或数量之一；可选 sell_date + sell_amount 已了结。
    """
    p = payload
    sym = p.symbol.strip()
    name = (p.name or "").strip() or sym
    plat = (p.platform or "manual").strip() or "manual"
    notes = p.notes

    if p.buy_date is not None:
        if p.amount is None or p.amount <= 0:
            raise APIException(code=40001, message="买入成交额（amount）须大于 0", status_code=400)
        fp = p.fee_percent if p.fee_percent is not None else 0.03
        rate = fp / 100.0
        fee_buy = _round_money(float(p.amount) * rate)
        net_buy = float(p.amount) - fee_buy

        qty = float(p.quantity) if p.quantity is not None and p.quantity > 0 else None
        price = float(p.price) if p.price is not None and p.price > 0 else None
        if qty and not price:
            price = _round_money(net_buy / qty, 6)
        elif price and not qty:
            qty = _round_money(net_buy / price, 4)
        else:
            raise APIException(code=40001, message="请填写买入单价或买入数量之一，以便与成交额、手续费推算另一项", status_code=400)
        if qty <= 0 or price <= 0:
            raise APIException(code=40001, message="推算得到的数量或价格无效", status_code=400)

        sell_date = p.sell_date
        sell_amt = p.sell_amount
        if sell_date is not None and sell_amt is not None:
            fee_sell = _round_money(float(sell_amt) * rate)
            net_sell = float(sell_amt) - fee_sell
            profit = _round_money(net_sell - net_buy)
            trade_date = sell_date
            direction = TradeDirection.sell
            total_fee = _round_money(fee_buy + fee_sell)
            sell_amount_db = float(sell_amt)
        elif sell_date is None and sell_amt is None:
            profit = 0.0
            trade_date = p.buy_date
            direction = TradeDirection.buy
            total_fee = fee_buy
            sell_amount_db = None
        else:
            raise APIException(
                code=40001,
                message="已了结时请同时填写「卖出日期」与「卖出成交额」；持仓至今则两者都留空",
                status_code=400,
            )

        return {
            "trade_date": trade_date,
            "buy_date": p.buy_date,
            "sell_date": sell_date if sell_date is not None else None,
            "sell_amount": sell_amount_db,
            "symbol": sym,
            "name": name[:50],
            "direction": direction,
            "quantity": Decimal(str(qty)),
            "price": Decimal(str(price)),
            "amount": Decimal(str(p.amount)),
            "fee": Decimal(str(total_fee)),
            "profit": Decimal(str(profit)),
            "platform": plat[:20],
            "notes": notes,
        }

    if p.trade_date is None or p.direction is None:
        raise APIException(code=40001, message="缺少 buy_date（新版）或 trade_date+direction（旧版）", status_code=400)
    if p.quantity is None or p.price is None or p.amount is None:
        raise APIException(code=40001, message="旧版创建需提供 quantity、price、amount", status_code=400)
    fee = p.fee if p.fee is not None else 0.0
    profit = p.profit if p.profit is not None else 0.0
    return {
        "trade_date": p.trade_date,
        "buy_date": None,
        "sell_date": None,
        "sell_amount": None,
        "symbol": sym,
        "name": name[:50],
        "direction": p.direction,
        "quantity": Decimal(str(p.quantity)),
        "price": Decimal(str(p.price)),
        "amount": Decimal(str(p.amount)),
        "fee": Decimal(str(fee)),
        "profit": Decimal(str(profit)),
        "platform": plat[:20],
        "notes": notes,
    }


def create_trade(db: Session, user_id: int, payload: TradeCreate) -> Trade:
    norm = normalize_trade_create_payload(payload)
    trade = Trade(user_id=user_id, **norm)
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
