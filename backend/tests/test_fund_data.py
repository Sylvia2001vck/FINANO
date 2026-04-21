from app.services.fund_data import fetch_fund_live_quote, merge_lsjz_points_asc, parse_tiantian_jsonp


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


def test_merge_lsjz_points_asc():
    base = [
        {"date": "2025-01-01", "dwjz": 1.0},
        {"date": "2025-01-03", "dwjz": 1.02},
    ]
    extra = [
        {"date": "2025-01-03", "dwjz": 1.03},
        {"date": "2025-01-06", "dwjz": 1.05},
    ]
    merged = merge_lsjz_points_asc(base, extra, start_date="2025-01-01", end_date="2025-01-31")
    assert [p["date"] for p in merged] == ["2025-01-01", "2025-01-03", "2025-01-06"]
    assert abs(merged[1]["dwjz"] - 1.03) < 1e-9
