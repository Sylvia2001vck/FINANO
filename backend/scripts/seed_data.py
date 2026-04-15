import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1]))

from app.db.base import Base
from app.db.session import SessionLocal, engine
from app.modules.trade.schemas import TradeCreate
from app.modules.trade.service import create_trade
from app.modules.user.schemas import UserCreate
from app.modules.user.service import create_user, get_user_by_email


def main():
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        user = get_user_by_email(db, "test@example.com")
        if not user:
            user = create_user(
                db,
                UserCreate(username="testuser", email="test@example.com", password="test123"),
            )

        trades = [
            TradeCreate(
                trade_date="2024-01-05",
                symbol="600519",
                name="贵州茅台",
                direction="buy",
                quantity=100,
                price=1800,
                amount=180000,
                fee=15,
                profit=18000,
            ),
            TradeCreate(
                trade_date="2024-01-15",
                symbol="000858",
                name="五粮液",
                direction="buy",
                quantity=200,
                price=150,
                amount=30000,
                fee=10,
                profit=-3000,
            ),
        ]
        for trade in trades:
            create_trade(db, user.id, trade)
        print("Seed data created successfully.")
    finally:
        db.close()


if __name__ == "__main__":
    main()
