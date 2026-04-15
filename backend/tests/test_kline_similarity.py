import numpy as np

from app.agent.fund_similarity import similarity_cosine
from app.services.fund_data import parse_lsjz_apidata_body


def test_parse_lsjz_sample():
    sample = r"""
var apidata={ content:"
| 净值日期 | 单位净值 | 累计净值 | 日增长率 | 申购状态 |
| 2026-04-14 | 1.7539 | 1.7539 | 0.71% | 开放 |
| 2026-04-13 | 1.7415 | 1.7415 | -1.54% | 开放 |
",records:2,pages:1,curpage:1};
"""
    rows = parse_lsjz_apidata_body(sample)
    assert len(rows) == 2
    assert rows[0]["date"] == "2026-04-13"
    assert abs(rows[1]["daily_return"] - 0.0071) < 1e-6


def test_cosine_identical_series():
    a = np.array([0.01, -0.02, 0.015, 0.0, -0.001])
    b = np.array([0.01, -0.02, 0.015, 0.0, -0.001])
    assert similarity_cosine(a, b) > 0.999
