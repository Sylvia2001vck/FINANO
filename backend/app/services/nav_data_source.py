"""净值/K 线序列数据源解析（大陆天天基金 vs 港股 ETF 日线）。"""

from __future__ import annotations

from app.core.config import settings

# 请求体 / 前端可选值
NAV_SOURCE_AUTO = "auto"
NAV_SOURCE_EASTMONEY = "eastmoney_cn"
NAV_SOURCE_HK_ETF = "hk_etf"


def normalize_nav_source_token(raw: str | None) -> str:
    s = (raw or "").strip().lower()
    if s in ("", NAV_SOURCE_AUTO):
        return NAV_SOURCE_AUTO
    if s in ("eastmoney", "eastmoney_cn", "cn", "tiantian", "ttjj"):
        return NAV_SOURCE_EASTMONEY
    if s in ("hk", "hk_etf", "hongkong", "hk_stock"):
        return NAV_SOURCE_HK_ETF
    return NAV_SOURCE_AUTO


def resolve_nav_data_source(fund_code: str, explicit: str | None) -> str:
    """
    explicit：来自 MAFB 单次请求的 nav_data_source；空则用环境 NAV_DATA_SOURCE_DEFAULT。
    返回 eastmoney_cn | hk_etf（已解析，不含 auto）。
    """
    token = normalize_nav_source_token(explicit)
    if token == NAV_SOURCE_AUTO:
        token = normalize_nav_source_token(settings.nav_data_source_default)

    if token == NAV_SOURCE_HK_ETF:
        return NAV_SOURCE_HK_ETF
    if token == NAV_SOURCE_EASTMONEY:
        return NAV_SOURCE_EASTMONEY

    code = (fund_code or "").strip().upper()
    if code.endswith(".HK"):
        return NAV_SOURCE_HK_ETF
    digits = "".join(ch for ch in code if ch.isdigit())
    if len(digits) == 5:
        return NAV_SOURCE_HK_ETF
    return NAV_SOURCE_EASTMONEY
