import pandas as pd


def calculate_trade_stats(trades_df: pd.DataFrame):
    if trades_df.empty or "profit" not in trades_df.columns:
        return {
            "total_trades": 0,
            "win_rate": 0,
            "profit_factor": 0,
            "max_drawdown": 0,
            "total_profit": 0,
            "avg_profit": 0,
        }

    profit_series = pd.to_numeric(trades_df["profit"], errors="coerce").fillna(0)
    total_trades = int(len(profit_series))
    win_trades = int((profit_series > 0).sum())
    loss_trades = int((profit_series < 0).sum())
    win_rate = (win_trades / total_trades) * 100 if total_trades else 0

    total_profit = float(profit_series[profit_series > 0].sum())
    total_loss = abs(float(profit_series[profit_series < 0].sum()))
    profit_factor = (total_profit / total_loss) if total_loss > 0 else (float("inf") if total_profit > 0 else 0)

    cumulative = profit_series.cumsum()
    running_max = cumulative.cummax().replace(0, pd.NA)
    drawdown = ((cumulative - running_max) / running_max * 100).fillna(0)
    max_drawdown = float(drawdown.min()) if not drawdown.empty else 0
    avg_profit = float(profit_series.mean()) if total_trades else 0

    return {
        "total_trades": total_trades,
        "win_rate": round(win_rate, 2),
        "profit_factor": round(profit_factor, 2) if profit_factor != float("inf") else 999999.0,
        "max_drawdown": round(max_drawdown, 2),
        "total_profit": round(float(profit_series.sum()), 2),
        "avg_profit": round(avg_profit, 2),
        "loss_trades": loss_trades,
    }
