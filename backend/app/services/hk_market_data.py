"""港股标的日线（AkShare），转换为与大陆基金净值序列一致的结构（收盘价→nav）。"""

from __future__ import annotations

import logging
import time
from datetime import datetime, timedelta
from typing import Any

logger = logging.getLogger(__name__)

_HK_NAV_CACHE: dict[str, tuple[float, list[dict[str, Any]]]] = {}
_HK_NAV_TTL_SEC = 180.0


def _normalize_hk_symbol(code: str) -> str:
    c = (code or "").strip().upper().replace(".HK", "")
    return "".join(ch for ch in c if ch.isdigit())


def fetch_hk_equity_daily_as_nav_history(
    fund_code: str,
    days: int = 90,
    timeout: float = 15.0,
) -> list[dict[str, Any]]:
    """
    拉取港股日线，输出与 fetch_fund_nav_history 兼容的行：
    date, nav(收盘), daily_return, daily_pct_display
    """
    sym = _normalize_hk_symbol(fund_code)
    if not sym:
        return []

    _ = float(timeout)  # 对齐大陆净值接口签名；AkShare 底层 requests 超时由全局控制

    try:
        import akshare as ak
    except ImportError:
        logger.warning("akshare not installed; HK nav history unavailable")
        return []

    per = max(20, min(int(days), 800))
    cache_key = f"{sym}:{per}"
    now = time.monotonic()
    hit = _HK_NAV_CACHE.get(cache_key)
    if hit is not None:
        ts, payload = hit
        if now - ts < _HK_NAV_TTL_SEC:
            return list(payload)

    end = datetime.now()
    start = end - timedelta(days=int(per * 1.8))

    df = None
    last_err: Exception | None = None
    for variant in (sym, sym.zfill(5), sym.lstrip("0") or sym):
        try:
            df = ak.stock_hk_hist(
                symbol=str(variant),
                period="daily",
                start_date=start.strftime("%Y%m%d"),
                end_date=end.strftime("%Y%m%d"),
                adjust="",
            )
            if df is not None and len(df) > 0:
                sym = str(variant)
                break
        except Exception as e:
            last_err = e
            df = None

    if df is None or len(df) == 0:
        logger.info("hk stock_hk_hist empty for %s last_err=%s", fund_code, last_err)
        return []

    rows: list[dict[str, Any]] = []
    date_col = "日期" if "日期" in df.columns else None
    close_col = "收盘" if "收盘" in df.columns else ("收盘价格" if "收盘价格" in df.columns else None)
    pct_col = "涨跌幅" if "涨跌幅" in df.columns else None
    if not date_col or not close_col:
        logger.warning("hk hist unexpected columns: %s", list(df.columns))
        return []

    prev_nav: float | None = None
    for _, r in df.iterrows():
        raw_d = r.get(date_col)
        if raw_d is None:
            continue
        try:
            if hasattr(raw_d, "strftime"):
                d_s = raw_d.strftime("%Y-%m-%d")
            else:
                d_s = str(raw_d)[:10]
        except Exception:
            d_s = str(raw_d)[:10]

        try:
            nav = float(r.get(close_col))
        except Exception:
            continue

        daily_return: float | None = None
        if pct_col is not None:
            pv = r.get(pct_col)
            if pv is not None:
                try:
                    s = str(pv).replace("%", "").strip()
                    daily_return = float(s) / 100.0
                except Exception:
                    daily_return = None
        if daily_return is None and prev_nav is not None and prev_nav > 0:
            daily_return = nav / prev_nav - 1.0
        elif daily_return is None:
            daily_return = 0.0

        rows.append(
            {
                "date": d_s,
                "nav": nav,
                "daily_return": float(daily_return),
                "daily_pct_display": f"{float(daily_return) * 100:.2f}%",
            }
        )
        prev_nav = nav

    rows.sort(key=lambda x: x["date"])
    if len(rows) > per:
        rows = rows[-per:]

    _HK_NAV_CACHE[cache_key] = (time.monotonic(), list(rows))
    return rows
