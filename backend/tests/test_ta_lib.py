import pandas as pd

from app.services.ta_lib import calculate_trade_stats


def test_calculate_trade_stats():
    trades_df = pd.DataFrame(
        [
            {"profit": 100},
            {"profit": -50},
            {"profit": 200},
            {"profit": -30},
        ]
    )

    stats = calculate_trade_stats(trades_df)

    assert stats["total_trades"] == 4
    assert stats["win_rate"] == 50.0
    assert stats["profit_factor"] == round(300 / 80, 2)
    assert stats["total_profit"] == 220.0
