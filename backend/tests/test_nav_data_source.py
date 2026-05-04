from app.services.nav_data_source import resolve_nav_data_source


def test_resolve_nav_auto_mainland():
    assert resolve_nav_data_source("510300", None) == "eastmoney_cn"


def test_resolve_nav_explicit_hk():
    assert resolve_nav_data_source("510300", "hk_etf") == "hk_etf"


def test_resolve_nav_auto_hk_five_digit():
    assert resolve_nav_data_source("02828", None) == "hk_etf"


def test_resolve_nav_auto_hk_suffix():
    assert resolve_nav_data_source("02828.HK", None) == "hk_etf"
