from bisect import bisect_right
from collections import defaultdict
from datetime import date, datetime, timedelta
from decimal import Decimal

import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.exceptions import APIException
from app.modules.replay.service import upsert_trade_curve_feature
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


def _resolve_latest_nav_price_from_lsjz(symbol: str) -> float | None:
    today = date.today()
    start = (today - timedelta(days=14)).isoformat()
    end = today.isoformat()
    data = fetch_lsjz_eastmoney_json_api_cached(
        symbol,
        start_date=start,
        end_date=end,
        timeout=20.0,
    )
    if not data.get("ok"):
        return None
    pts = list(data.get("points_asc") or [])
    if not pts:
        return None
    for p in reversed(pts):
        try:
            px = float(p.get("dwjz"))
        except (TypeError, ValueError):
            continue
        if px > 0:
            return px
    return None


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
            latest_price = _resolve_latest_nav_price_from_lsjz(sym)
            if latest_price is not None:
                profit = _round_money(float(qty) * float(latest_price) - float(p.amount))
            else:
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


def create_trade(db: Session, user_id: int, payload: TradeCreate) -> tuple[Trade, bool]:
    norm = normalize_trade_create_payload(payload)
    # 幂等保护：短时间内同用户同关键字段重复提交，直接返回最近一条，避免连点造成重复记录
    cutoff = datetime.utcnow() - timedelta(seconds=20)
    dup = db.scalar(
        select(Trade)
        .where(
            Trade.user_id == user_id,
            Trade.symbol == str(norm.get("symbol") or ""),
            Trade.trade_date == norm.get("trade_date"),
            Trade.buy_date == norm.get("buy_date"),
            Trade.sell_date == norm.get("sell_date"),
            Trade.direction == norm.get("direction"),
            Trade.amount == norm.get("amount"),
            Trade.platform == str(norm.get("platform") or "manual"),
            Trade.created_at >= cutoff,
        )
        .order_by(Trade.id.desc())
        .limit(1)
    )
    if dup is not None:
        return dup, True
    trade = Trade(user_id=user_id, **norm)
    db.add(trade)
    db.commit()
    db.refresh(trade)
    try:
        upsert_trade_curve_feature(db, user_id, trade)
    except Exception:
        # 曲线特征写入失败不影响交易创建
        pass
    return trade, False


def delete_trade(db: Session, user_id: int, trade_id: int) -> None:
    trade = get_user_trade(db, user_id, trade_id)
    db.delete(trade)
    db.commit()


def create_trades(db: Session, user_id: int, trades: list[dict]) -> list[Trade]:
    created = []
    for item in trades:
        payload = TradeCreate.model_validate(item)
        t, _ = create_trade(db, user_id, payload)
        created.append(t)
    return created


def list_user_trades(db: Session, user_id: int) -> list[Trade]:
    trades = list(
        db.scalars(
            select(Trade).where(Trade.user_id == user_id).order_by(Trade.trade_date.desc(), Trade.id.desc())
        )
    )
    latest_nav_cache: dict[str, float | None] = {}
    for t in trades:
        if t.sell_date is not None:
            continue
        if t.direction != TradeDirection.buy:
            continue
        sym = str(t.symbol or "").strip()
        if not sym:
            continue
        if sym not in latest_nav_cache:
            latest_nav_cache[sym] = _resolve_latest_nav_price_from_lsjz(sym)
        latest_px = latest_nav_cache[sym]
        if latest_px is None:
            continue
        try:
            unrealized = _round_money(float(t.quantity) * float(latest_px) - float(t.amount))
            t.profit = Decimal(str(unrealized))
        except Exception:
            continue
    return trades


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
    stats = calculate_trade_stats(pd.DataFrame(records))
    stats["daily_pnl_series"] = _build_daily_pnl_series(db, user_id, trades)
    return stats


def _build_daily_pnl_series(db: Session, user_id: int, trades: list[Trade] | None = None) -> list[dict]:
    src = trades if trades is not None else list_user_trades(db, user_id)
    if not src:
        return []
    valid_trades = [t for t in src if t.buy_date is not None and float(t.amount) > 0]
    if not valid_trades:
        return []

    symbol_to_trades: dict[str, list[Trade]] = defaultdict(list)
    for t in valid_trades:
        sym = str(t.symbol or "").strip()
        if sym:
            symbol_to_trades[sym].append(t)
    if not symbol_to_trades:
        return []

    start_date = min((t.buy_date for t in valid_trades if t.buy_date is not None), default=None)
    if start_date is None:
        return []
    end_date = date.today()
    for t in valid_trades:
        if t.sell_date and t.sell_date > end_date:
            end_date = t.sell_date

    nav_date_union: set[date] = set()
    symbol_nav_index: dict[str, tuple[list[date], list[float]]] = {}
    for sym in symbol_to_trades.keys():
        payload = fetch_lsjz_eastmoney_json_api_cached(
            sym,
            start_date=start_date.isoformat(),
            end_date=end_date.isoformat(),
            timeout=20.0,
        )
        pts = list(payload.get("points_asc") or [])
        dates: list[date] = []
        navs: list[float] = []
        for p in pts:
            try:
                d = datetime.fromisoformat(str(p.get("date") or "")[:10]).date()
                nav = float(p.get("dwjz"))
            except Exception:
                continue
            if nav <= 0:
                continue
            dates.append(d)
            navs.append(nav)
            nav_date_union.add(d)
        if dates:
            symbol_nav_index[sym] = (dates, navs)

    if not nav_date_union:
        return []

    for t in valid_trades:
        nav_date_union.add(t.buy_date)
        if t.sell_date:
            nav_date_union.add(t.sell_date)
    all_dates = sorted([d for d in nav_date_union if start_date <= d <= end_date])
    if not all_dates:
        return []

    def nav_at_or_before(sym: str, d: date) -> float | None:
        idx = symbol_nav_index.get(sym)
        if idx is None:
            return None
        ds, vs = idx
        pos = bisect_right(ds, d) - 1
        if pos < 0:
            return None
        return vs[pos]

    realized_cache: dict[int, float] = {}
    for t in valid_trades:
        if not t.sell_date:
            continue
        if t.sell_amount is not None:
            realized_cache[t.id] = _round_money(float(t.sell_amount) - float(t.amount))
            continue
        sell_nav = nav_at_or_before(t.symbol, t.sell_date)
        if sell_nav is not None:
            realized_cache[t.id] = _round_money(float(t.quantity) * float(sell_nav) - float(t.amount))
        else:
            realized_cache[t.id] = _round_money(float(t.profit))

    out: list[dict] = []
    prev_cum = 0.0
    for d in all_dates:
        cumulative = 0.0
        for t in valid_trades:
            if d < t.buy_date:
                continue
            end_hold = t.sell_date or end_date
            if d > end_hold:
                cumulative += realized_cache.get(t.id, _round_money(float(t.profit)))
                continue
            nav = nav_at_or_before(t.symbol, d)
            if nav is None:
                if t.sell_date and d >= t.sell_date:
                    cumulative += realized_cache.get(t.id, _round_money(float(t.profit)))
                continue
            cumulative += _round_money(float(t.quantity) * float(nav) - float(t.amount))
        cumulative = _round_money(cumulative)
        daily = _round_money(cumulative - prev_cum)
        out.append(
            {
                "date": d.isoformat(),
                "daily_pnl": daily,
                "cumulative_pnl": cumulative,
            }
        )
        prev_cum = cumulative
    return out


def get_trade_curve_with_markers(db: Session, user_id: int, symbol: str) -> dict:
    sym = str(symbol or "").strip()
    if not sym:
        raise APIException(code=40001, message="基金代码不能为空", status_code=400)
    trades = list(
        db.scalars(
            select(Trade)
            .where(Trade.user_id == user_id, Trade.symbol == sym)
            .order_by(Trade.buy_date.asc(), Trade.trade_date.asc(), Trade.id.asc())
        )
    )
    if not trades:
        return {"symbol": sym, "name": "", "points": [], "markers": []}

    name = str(trades[0].name or sym)
    start_anchor = min((t.buy_date or t.trade_date for t in trades), default=date.today())
    end_anchor = max((t.sell_date or date.today() for t in trades), default=date.today())
    start = (start_anchor - timedelta(days=30)).isoformat()
    end = (end_anchor + timedelta(days=3)).isoformat()
    payload = fetch_lsjz_eastmoney_json_api_cached(sym, start_date=start, end_date=end, timeout=22.0)
    pts = list(payload.get("points_asc") or [])

    curve_points: list[dict] = []
    nav_dates: list[date] = []
    nav_values: list[float] = []
    for p in pts:
        try:
            ds = str(p.get("date") or "")[:10]
            d = datetime.fromisoformat(ds).date()
            nav = float(p.get("dwjz"))
        except Exception:
            continue
        if nav <= 0:
            continue
        nav_dates.append(d)
        nav_values.append(nav)
        curve_points.append({"date": d.isoformat(), "nav": nav})

    def marker_nav_on(d: date) -> float | None:
        if not nav_dates:
            return None
        pos = bisect_right(nav_dates, d) - 1
        if pos < 0:
            return None
        return nav_values[pos]

    markers: list[dict] = []
    for t in trades:
        buy_d = t.buy_date or t.trade_date
        buy_nav = marker_nav_on(buy_d)
        markers.append(
            {
                "trade_id": int(t.id),
                "date": buy_d.isoformat(),
                "action": "buy",
                "amount": float(t.amount),
                "quantity": float(t.quantity),
                "nav": buy_nav,
                "label": f"买入 #{t.id}",
            }
        )
        if t.sell_date:
            sell_nav = marker_nav_on(t.sell_date)
            markers.append(
                {
                    "trade_id": int(t.id),
                    "date": t.sell_date.isoformat(),
                    "action": "sell",
                    "amount": float(t.sell_amount) if t.sell_amount is not None else None,
                    "quantity": float(t.quantity),
                    "nav": sell_nav,
                    "label": f"卖出 #{t.id}",
                }
            )

    markers.sort(key=lambda x: (x.get("date") or "", 0 if x.get("action") == "buy" else 1, int(x.get("trade_id") or 0)))
    return {"symbol": sym, "name": name, "points": curve_points, "markers": markers}
