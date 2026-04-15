from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field

from app.modules.trade.models import TradeDirection


class TradeBase(BaseModel):
    trade_date: date
    symbol: str = Field(min_length=1, max_length=20)
    name: str = Field(min_length=1, max_length=50)
    direction: TradeDirection
    quantity: float = Field(gt=0)
    price: float = Field(gt=0)
    amount: float = Field(gt=0)
    fee: float = Field(default=0, ge=0)
    profit: float = 0
    platform: str = "manual"
    notes: str | None = None


class TradeCreate(TradeBase):
    pass


class TradeRead(TradeBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int
    created_at: datetime
    updated_at: datetime


class TradeStats(BaseModel):
    total_trades: int = 0
    win_rate: float = 0
    profit_factor: float = 0
    max_drawdown: float = 0
    total_profit: float = 0
    avg_profit: float = 0
