from app.services.similar_funds import similar_funds


def test_similar_funds_returns_ordered_rows():
    rows = similar_funds("510300", top_k=3)
    assert len(rows) <= 3
    assert all("similarity" in r and "code" in r for r in rows)
    assert all(r["code"] != "510300" for r in rows)


def test_similar_funds_unknown_code():
    assert similar_funds("000000") == []
