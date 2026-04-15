"""eastmoney_fund_loader 解析逻辑（不发起真实外网请求）。"""

from app.agent.eastmoney_fund_loader import _parse_fundcode_search_js, _row_to_fund


def test_parse_fundcode_search_js_minimal():
    js = 'var r = [["510300","HS300","沪深300ETF","指数型-股票","HS300"]];'
    rows = _parse_fundcode_search_js(js)
    assert len(rows) == 1
    fund = _row_to_fund(rows[0])
    assert fund is not None
    assert fund["code"] == "510300"
    assert "沪深300" in fund["name"]
