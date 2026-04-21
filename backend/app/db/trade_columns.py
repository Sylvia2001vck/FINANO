"""为 trades 表补充买入/卖出日期与卖出金额列（SQLite / MySQL 兼容，幂等）。"""

from __future__ import annotations

from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine


def ensure_trade_lifecycle_columns(engine: Engine) -> None:
    insp = inspect(engine)
    if "trades" not in insp.get_table_names():
        return
    cols = {c["name"] for c in insp.get_columns("trades")}
    dialect = engine.dialect.name
    with engine.begin() as conn:
        if "buy_date" not in cols:
            conn.execute(text("ALTER TABLE trades ADD COLUMN buy_date DATE"))
        if "sell_date" not in cols:
            conn.execute(text("ALTER TABLE trades ADD COLUMN sell_date DATE"))
        if "sell_amount" not in cols:
            if dialect == "sqlite":
                conn.execute(text("ALTER TABLE trades ADD COLUMN sell_amount NUMERIC(12, 2)"))
            else:
                conn.execute(text("ALTER TABLE trades ADD COLUMN sell_amount DECIMAL(12,2) NULL"))
