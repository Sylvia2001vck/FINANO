from datetime import timedelta
from decimal import Decimal

import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.exceptions import APIException
from app.modules.trade.models import Trade, TradeDirection
from app.modules.trade.schemas import TradeCreate
from app.services.fund_data import fetch_lsjz_eastmoney_json_api_cached
from app.services.ta_lib import calculate_trade_stats


def _round_money(x: float, nd: int = 2) -> float:
    return round(float(x), nd)


def _resolve_nav_price_from_lsjz(symbol: str, target_date) -> float:
    start = (target_date - timedelta(days=7)).isoformat()
    end = (target_date + timedelta(days=2)).isoformat()
    data = fetch_lsjz_eastmoney_json_api_cached(
        symbol,
        start_date=start,
        end_date=end,
        timeout=20.0,
    )
    if not data.get("ok"):
        raise APIException(code=40001, message="买入净值数据暂不可用，请稍后重试", status_code=400)
    pts = list(data.get("points_asc") or [])
    if not pts:
        raise APIException(code=40001, message="未查询到买入日期附近净值，请更换日期", status_code=400)
    target = target_date.isoformat()
    chosen = None
    for p in pts:
        d = str(p.get("date") or "")
        if d and d <= target:
            chosen = p
        elif d and d > target:
            break
    if chosen is None:
        chosen = pts[0]
    px = chosen.get("dwjz")
    try:
        price = float(px)
    except (TypeError, ValueError):
        raise APIException(code=40001, message="净值格式异常，请稍后重试", status_code=400)
    if price <= 0:
        raise APIException(code=40001, message="净值无效，请稍后重试", status_code=400)
    return price


def normalize_trade_create_payload(payload: TradeCreate) -> dict:
    """
    将 TradeCreate 转为 Trade ORM 可接受的字段字典。
    新版：buy_date + amount(买入成交额)；买入单价从天天基金历史净值反查，再反推数量。
    """
    p = payload
    sym = p.symbol.strip()
    name = (p.name or "").strip() or sym
    plat = (p.platform or "manual").strip() or "manual"
    notes = p.notes

    if p.buy_date is not None:
        if p.amount is None or p.amount <= 0:
            raise APIException(code=40001, message="买入成交额（amount）须大于 0", status_code=400)
        price = _resolve_nav_price_from_lsjz(sym, p.buy_date)
        qty = _round_money(float(p.amount) / price, 4)
        if qty <= 0 or price <= 0:
            raise APIException(code=40001, message="推算得到的数量或价格无效", status_code=400)

        sell_date = p.sell_date
        sell_amt = p.sell_amount
        if sell_date is not None:
            # 若已卖出：优先按卖出日净值自动估算卖出成交额，避免手填误差
            try:
                sell_price = _resolve_nav_price_from_lsjz(sym, sell_date)
                sell_amount_auto = _round_money(float(qty) * float(sell_price))
            except APIException:
                if sell_amt is None:
                    raise
                sell_amount_auto = _round_money(float(sell_amt))
            profit = _round_money(float(sell_amount_auto) - float(p.amount))
            trade_date = sell_date
            direction = TradeDirection.sell
            total_fee = 0.0
            sell_amount_db = float(sell_amount_auto)
        elif sell_date is None and sell_amt is None:
            profit = 0.0
            trade_date = p.buy_date
            direction = TradeDirection.buy
            total_fee = 0.0
            sell_amount_db = None
        else:
            raise APIException(
                code=40001,
                message="持仓至今请不要填写卖出成交额；已卖出只需填写卖出日期",
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


def delete_trade(db: Session, user_id: int, trade_id: int) -> None:
    trade = get_user_trade(db, user_id, trade_id)
    db.delete(trade)
    db.commit()


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
