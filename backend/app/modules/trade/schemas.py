from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field

from app.modules.trade.models import TradeDirection


class TradeCreate(BaseModel):
    """创建交易：新版（buy_date + 买入成交额 + 费率）或旧版（trade_date + direction + 量价）。"""

    symbol: str = Field(min_length=1, max_length=20)
    name: str = Field(min_length=1, max_length=50)
    platform: str = "manual"
    notes: str | None = None

    buy_date: date | None = None
    sell_date: date | None = None
    sell_amount: float | None = None
    fee_percent: float | None = Field(default=None, ge=0, le=100)

    trade_date: date | None = None
    direction: TradeDirection | None = None
    quantity: float | None = None
    price: float | None = None
    amount: float | None = None
    fee: float | None = None
    profit: float | None = None


class TradeRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int
    trade_date: date
    buy_date: date | None = None
    sell_date: date | None = None
    sell_amount: float | None = None
    symbol: str
    name: str
    direction: TradeDirection
    quantity: float
    price: float
    amount: float
    fee: float
    profit: float
    platform: str
    notes: str | None
    created_at: datetime
    updated_at: datetime


class TradeStats(BaseModel):
    total_trades: int = 0
    win_rate: float = 0
    profit_factor: float = 0
    max_drawdown: float = 0
    total_profit: float = 0
    avg_profit: float = 0
