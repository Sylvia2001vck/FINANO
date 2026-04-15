from app.services.fund_data import fetch_fund_live_quote, parse_tiantian_jsonp


def test_parse_tiantian_jsonp():
    raw = 'jsonpgz({"fundcode":"005827","name":"易方达蓝筹","dwjz":"1.2345"});'
    data = parse_tiantian_jsonp(raw)
    assert data is not None
    assert data["fundcode"] == "005827"
    assert data["name"] == "易方达蓝筹"


def test_parse_tiantian_jsonp_invalid():
    assert parse_tiantian_jsonp("not json") is None


def test_fetch_live_quote_invalid_code():
    assert fetch_fund_live_quote("abc") is None
    assert fetch_fund_live_quote("12345") is None
