from app.agent.fund_catalog import filter_catalog_rows, list_funds_catalog_sample


def test_filter_catalog_rows_track():
    rows = [
        {"code": "000001", "name": "A", "track": "指数", "type": "指数型-股票", "risk_rating": 4},
        {"code": "000002", "name": "B", "track": "债券", "type": "债券型", "risk_rating": 2},
    ]
    r = filter_catalog_rows(rows, track_kw="指数")
    assert len(r) == 1 and r[0]["code"] == "000001"


def test_list_funds_catalog_sample_deterministic():
    rows = [{"code": f"{i:06d}", "name": f"n{i}", "track": "宽基", "type": "ETF", "risk_rating": 3} for i in range(50)]
    from app.agent import fund_catalog as fc

    orig = fc.list_funds_catalog_only
    fc.list_funds_catalog_only = lambda: [dict(x) for x in rows]  # type: ignore[method-assign]
    try:
        a, n1, s1 = fc.list_funds_catalog_sample(limit=5, seed=42, etf_only=True)
        b, n2, s2 = fc.list_funds_catalog_sample(limit=5, seed=42, etf_only=True)
        assert len(a) == 5 and n1 == n2 == 50 and s1 == s2 == 42
        assert [x["code"] for x in a] == [x["code"] for x in b]
    finally:
        fc.list_funds_catalog_only = orig  # type: ignore[method-assign]
