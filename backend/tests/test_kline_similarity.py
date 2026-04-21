import numpy as np

from app.agent.fund_similarity import (
    _coarse_paa_normalized,
    _paa,
    _series_on_master_dates,
    similarity_cosine,
    similarity_dtw_banded,
)
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


def test_paa_fixed_length():
    x = np.arange(100, dtype=float)
    y = _paa(x, 10)
    assert y.shape == (10,)
    assert abs(float(y.mean()) - float(x.mean())) < 1e-6


def test_series_on_master_ffill():
    master = ["2025-01-01", "2025-01-02", "2025-01-03", "2025-01-04"]
    peer = {"2025-01-01": 0.1, "2025-01-03": 0.3}
    v = _series_on_master_dates(peer, master)
    assert v.shape == (4,)
    assert abs(v[0] - 0.1) < 1e-9
    assert abs(v[1] - 0.1) < 1e-9
    assert abs(v[2] - 0.3) < 1e-9


def test_coarse_vectors_unit_norm():
    x = np.sin(np.linspace(0, 3, 60)).astype(float)
    v = _coarse_paa_normalized(x, 16)
    assert v.shape == (16,)
    n = float(np.linalg.norm(v))
    assert abs(n - 1.0) < 1e-4


def test_banded_dtw_self_high():
    x = np.random.default_rng(0).normal(0, 0.01, size=40).astype(float)
    s = similarity_dtw_banded(x, x, band_ratio=0.2)
    assert s > 0.99
