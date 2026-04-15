import os
from pathlib import Path

os.environ["DATABASE_URL"] = "sqlite:///./test_finano.db"
os.environ["CORS_ORIGINS"] = '["http://localhost:5173"]'

from fastapi.testclient import TestClient

from app.main import app


client = TestClient(app)
DB_FILE = Path("test_finano.db")


def _auth_headers():
    response = client.post(
        "/api/v1/auth/register",
        json={
            "username": "apitest",
            "email": "apitest@example.com",
            "password": "secret123",
        },
    )
    token = response.json()["data"]["access_token"]
    return {"Authorization": f"Bearer {token}"}


def test_trade_flow():
    headers = _auth_headers()
    create_response = client.post(
        "/api/v1/trades",
        headers=headers,
        json={
            "trade_date": "2024-01-05",
            "symbol": "600519",
            "name": "贵州茅台",
            "direction": "buy",
            "quantity": 100,
            "price": 1800,
            "amount": 180000,
            "fee": 15,
            "profit": 3200,
            "platform": "manual",
            "notes": "smoke",
        },
    )
    assert create_response.status_code == 200
    summary_response = client.get("/api/v1/trades/stats/summary", headers=headers)
    assert summary_response.status_code == 200
    assert summary_response.json()["data"]["total_trades"] >= 1


def teardown_module():
    if DB_FILE.exists():
        DB_FILE.unlink()
