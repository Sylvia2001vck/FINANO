from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError
import math
import re
import time
from dataclasses import dataclass
from typing import Any

from app.core.config import settings

_TTL_SEC = 1800.0
_CACHE: dict[str, tuple[float, dict[str, Any]]] = {}


def _run_with_timeout(fn, *args, timeout_sec: float = 8.0, **kwargs) -> tuple[str, Any]:
    """Run blocking third-party call with a hard timeout."""
    with ThreadPoolExecutor(max_workers=1) as ex:
        fut = ex.submit(fn, *args, **kwargs)
        try:
            return "ok", fut.result(timeout=max(0.5, float(timeout_sec)))
        except FuturesTimeoutError:
            return "timeout", None
        except Exception:
            return "error", None


@dataclass
class FundamentalSnapshot:
    aum_billion: float | None
    manager_score: float | None
    manager_return_annual: float | None
    stock_top10_concentration: float | None
    stock_top5_concentration: float | None
    stock_equity_ratio: float | None
    holding_drift: float | None
    quarter_samples: int
    top_holdings: list[dict[str, Any]]
    source_notes: list[str]
    context_chunks: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "aum_billion": self.aum_billion,
            "manager_score": self.manager_score,
            "manager_return_annual": self.manager_return_annual,
            "stock_top10_concentration": self.stock_top10_concentration,
            "stock_top5_concentration": self.stock_top5_concentration,
            "stock_equity_ratio": self.stock_equity_ratio,
            "holding_drift": self.holding_drift,
            "quarter_samples": self.quarter_samples,
            "top_holdings": self.top_holdings,
            "source_notes": self.source_notes,
            "fundamental_context_chunks": self.context_chunks,
        }


def _to_float(v: Any) -> float | None:
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).strip().replace("%", "").replace(",", "")
    if not s:
        return None
    m = re.search(r"[-+]?\d+(\.\d+)?", s)
    if not m:
        return None
    try:
        return float(m.group())
    except ValueError:
        return None


def _pick_first_numeric(obj: dict[str, Any], keys: list[str]) -> float | None:
    for k in keys:
        if k in obj:
            val = _to_float(obj.get(k))
            if val is not None:
                return val
    return None


def _pick_ratio_column(cols: list[Any]) -> str | None:
    """
    Pick the most likely holdings weight column.
    Prefer exact '占净值比例', avoid change/delta columns like '占净值比例变动'.
    """
    bad_tokens = ("变动", "同比", "环比", "变化", "较上期", "增减")
    scored: list[tuple[int, str]] = []
    for c in cols:
        s = str(c)
        score = 0
        if "占净值比例" in s:
            score = 100
        elif "占净值" in s and "比例" in s:
            score = 80
        elif "比例" in s:
            score = 40
        if score <= 0:
            continue
        if any(t in s for t in bad_tokens):
            score -= 90
        if score > 0:
            scored.append((score, s))
    if not scored:
        return None
    scored.sort(key=lambda x: x[0], reverse=True)
    return scored[0][1]


def _normalize_ratio_value(v: Any) -> float:
    n = float(_to_float(v) or 0.0)
    if n <= 0:
        return 0.0
    return n / 100.0 if n > 1.0 else n


def _extract_aum_billion(raw: str) -> float | None:
    s = str(raw or "").strip()
    if not s:
        return None
    num = _to_float(s)
    if num is None:
        return None
    if "万亿" in s:
        return float(num * 10000.0)
    if "亿" in s:
        return float(num)
    if "万" in s:
        return float(num / 10000.0)
    # 没单位时保守按“亿元”解释；若异常大则按“元”回退
    if num > 1e6:
        return float(num / 1e8)
    return float(num)


def _akshare_overview_fields(fund_code: str) -> tuple[float | None, str | None, list[str]]:
    try:
        import akshare as ak  # type: ignore
    except Exception:
        return None, None, ["akshare_overview_import_failed"]

    notes: list[str] = []
    df = None
    saw_timeout = False
    saw_error = False
    timeout_sec = float(settings.fundamental_akshare_timeout_sec or 12.0)
    call_attempts = (
        {"symbol": fund_code},
        {"fund": fund_code},
        {"symbol": fund_code, "indicator": "基金概况"},
        {"fund": fund_code, "indicator": "基金概况"},
        {"fund": fund_code, "indicator": "基金基本信息"},
    )
    for kwargs in call_attempts:
        status, cand = _run_with_timeout(ak.fund_open_fund_info_em, timeout_sec=timeout_sec, **kwargs)
        if status == "timeout":
            saw_timeout = True
            continue
        if status == "error":
            saw_error = True
            continue
        df = cand
        if df is not None and not getattr(df, "empty", True):
            notes.append("akshare_overview_ok")
            break

    if df is None or getattr(df, "empty", True):
        if saw_timeout:
            return None, None, notes + ["akshare_overview_timeout"]
        if saw_error:
            return None, None, notes + ["akshare_overview_error"]
        return None, None, notes + ["akshare_overview_empty"]

    cols = list(df.columns)
    key_col = cols[0] if cols else None
    val_col = cols[1] if len(cols) >= 2 else None
    kv: dict[str, str] = {}
    if key_col and val_col:
        try:
            for _, row in df[[key_col, val_col]].dropna().iterrows():
                kv[str(row[key_col]).strip()] = str(row[val_col]).strip()
        except Exception:
            kv = {}

    aum_keys = ["基金规模", "基金规模（亿元）", "基金规模（合计）", "规模", "最新规模"]
    mgr_keys = ["基金经理", "现任基金经理", "基金经理人"]
    aum_billion = None
    manager_name = None
    for k in aum_keys:
        if k in kv and kv[k]:
            aum_billion = _extract_aum_billion(kv[k])
            if aum_billion is not None:
                break
    for k in mgr_keys:
        if k in kv and kv[k]:
            manager_name = kv[k]
            break

    # 兜底：有些表不是 key/value，而是直接列字段
    if aum_billion is None:
        for c in cols:
            if "规模" in str(c):
                try:
                    s = str(df[c].dropna().iloc[0])
                    aum_billion = _extract_aum_billion(s)
                    if aum_billion is not None:
                        break
                except Exception:
                    continue
    if manager_name is None:
        for c in cols:
            if "经理" in str(c):
                try:
                    s = str(df[c].dropna().iloc[0]).strip()
                    if s:
                        manager_name = s
                        break
                except Exception:
                    continue
    return aum_billion, manager_name, notes


def _akshare_portfolio_drift(fund_code: str, max_quarters: int) -> tuple[float | None, int]:
    if not bool(settings.fundamental_use_akshare):
        return None, 0
    try:
        import akshare as ak  # type: ignore
    except Exception:
        return None, 0

    timeout_sec = float(settings.fundamental_akshare_timeout_sec or 12.0)
    _, df = _run_with_timeout(ak.fund_portfolio_hold_em, symbol=fund_code, timeout_sec=timeout_sec)
    if df is None:
        _, df = _run_with_timeout(ak.fund_portfolio_hold_em, code=fund_code, timeout_sec=timeout_sec)

    if df is None or getattr(df, "empty", True):
        return None, 0
    cols = list(df.columns)
    quarter_col = next((c for c in cols if "季度" in str(c) or "报告期" in str(c)), None)
    stock_col = next((c for c in cols if "代码" in str(c)), None)
    ratio_col = _pick_ratio_column(cols)
    if not quarter_col or not stock_col or not ratio_col:
        return None, 0

    work = df[[quarter_col, stock_col, ratio_col]].copy()
    work = work.dropna(subset=[quarter_col, stock_col, ratio_col])
    work[ratio_col] = work[ratio_col].apply(_normalize_ratio_value)
    quarters = sorted({str(x) for x in work[quarter_col].tolist()}, reverse=True)
    if len(quarters) < 2:
        return None, min(1, len(quarters))
    quarters = quarters[: max(2, int(max_quarters))]

    drift_vals: list[float] = []
    for i in range(len(quarters) - 1):
        q1, q2 = quarters[i], quarters[i + 1]
        d1 = work[work[quarter_col].astype(str) == q1]
        d2 = work[work[quarter_col].astype(str) == q2]
        if d1.empty or d2.empty:
            continue
        m1 = {str(r[stock_col]): float(r[ratio_col]) for _, r in d1.iterrows()}
        m2 = {str(r[stock_col]): float(r[ratio_col]) for _, r in d2.iterrows()}
        keys = set(m1.keys()) | set(m2.keys())
        if not keys:
            continue
        l1 = sum(abs(m1.get(k, 0.0) - m2.get(k, 0.0)) for k in keys)
        drift_vals.append(l1 / 2.0)
    if not drift_vals:
        return None, len(quarters)
    return float(sum(drift_vals) / len(drift_vals)), len(quarters)


def _akshare_holdings_features(
    fund_code: str,
) -> tuple[float | None, float | None, float | None, list[dict[str, Any]], int, list[str]]:
    if not bool(settings.fundamental_use_akshare):
        return None, None, None, [], 0, ["akshare_disabled"]
    try:
        import akshare as ak  # type: ignore
    except Exception:
        return None, None, None, [], 0, ["akshare_import_failed"]
    timeout_sec = float(settings.fundamental_akshare_timeout_sec or 12.0)
    saw_timeout = False
    saw_error = False
    status, df = _run_with_timeout(ak.fund_portfolio_hold_em, symbol=fund_code, timeout_sec=timeout_sec)
    if status == "timeout":
        saw_timeout = True
    elif status == "error":
        saw_error = True
    if df is None:
        status, df = _run_with_timeout(ak.fund_portfolio_hold_em, code=fund_code, timeout_sec=timeout_sec)
        if status == "timeout":
            saw_timeout = True
        elif status == "error":
            saw_error = True
    # one retry with a slightly larger timeout, to reduce transient timeout rate
    if df is None:
        retry_timeout = min(30.0, timeout_sec * 1.8)
        status, df = _run_with_timeout(ak.fund_portfolio_hold_em, symbol=fund_code, timeout_sec=retry_timeout)
        if status == "timeout":
            saw_timeout = True
        elif status == "error":
            saw_error = True
    if df is None:
        retry_timeout = min(30.0, timeout_sec * 1.8)
        status, df = _run_with_timeout(ak.fund_portfolio_hold_em, code=fund_code, timeout_sec=retry_timeout)
        if status == "timeout":
            saw_timeout = True
        elif status == "error":
            saw_error = True
    if df is None or getattr(df, "empty", True):
        if saw_timeout:
            return None, None, None, [], 0, ["akshare_holdings_timeout"]
        if saw_error:
            return None, None, None, [], 0, ["akshare_holdings_error"]
        return None, None, None, [], 0, ["akshare_holdings_empty"]

    cols = list(df.columns)
    quarter_col = next((c for c in cols if "季度" in str(c) or "报告期" in str(c)), None)
    stock_col = next((c for c in cols if "代码" in str(c)), None)
    name_col = next((c for c in cols if "名称" in str(c) or "简称" in str(c)), None)
    ratio_col = _pick_ratio_column(cols)
    if not stock_col or not ratio_col:
        return None, None, None, [], 0, ["akshare_holdings_schema_unexpected"]

    work = df.copy()
    try:
        work[ratio_col] = work[ratio_col].apply(_normalize_ratio_value)
    except Exception:
        return None, None, None, [], 0, ["akshare_holdings_ratio_parse_failed"]

    quarter_samples = 0
    latest_rows = work
    if quarter_col is not None:
        try:
            quarter_vals = [str(x) for x in work[quarter_col].dropna().tolist()]
            uniq = sorted(set(quarter_vals), reverse=True)
            quarter_samples = len(uniq)
            if uniq:
                latest_rows = work[work[quarter_col].astype(str) == uniq[0]]
        except Exception:
            quarter_samples = 0

    latest_rows = latest_rows.sort_values(by=ratio_col, ascending=False)
    vals: list[float] = []
    vals5: list[float] = []
    tops: list[dict[str, Any]] = []
    for _, row in latest_rows.head(10).iterrows():
        code = str(row.get(stock_col) or "").strip()
        ratio = float(row.get(ratio_col) or 0.0)
        if not code or ratio <= 0:
            continue
        vals.append(ratio)
        if len(vals5) < 5:
            vals5.append(ratio)
        nm = str(row.get(name_col) or "").strip() if name_col else ""
        tops.append({"code": code, "name": nm, "ratio": ratio})
    if not vals:
        return None, None, None, [], quarter_samples, ["akshare_holdings_latest_empty"]
    # Some schemas expose values in per-mille-like scale (x10 after initial normalization).
    # Apply a conservative correction only when concentration is clearly impossible.
    extra_note: list[str] = []
    if sum(vals) > 1.2 or max(vals) > 0.4:
        scaled = [v / 10.0 for v in vals]
        if sum(scaled) <= 1.2 and max(scaled) <= 0.4:
            vals = scaled
            vals5 = [v / 10.0 for v in vals5]
            for item in tops:
                item["ratio"] = float(item.get("ratio") or 0.0) / 10.0
            extra_note.append("akshare_holdings_scaled_div10")
    top10 = float(sum(vals))
    top5 = float(sum(vals5)) if vals5 else None
    # 权益仓位缺精确信源时，用 top10 作为保守代理（上限 95%）
    eq_ratio = float(min(0.95, max(top10, 0.0)))
    return eq_ratio, top10, top5, tops, quarter_samples, ["akshare_holdings_ok", *extra_note]


def _akshare_manager_quality_score(fund_code: str) -> tuple[float | None, float | None, list[str]]:
    """
    Rule-based manager score reconstruction:
    score ~= 0.4 * tenure_years + 0.6 * annual_return.
    Then clamp to [0, 5].
    """
    if not bool(settings.fundamental_use_akshare):
        return None, None, ["akshare_manager_disabled"]
    try:
        import akshare as ak  # type: ignore
    except Exception:
        return None, None, ["akshare_manager_import_failed"]

    timeout_sec = float(settings.fundamental_akshare_timeout_sec or 12.0)
    notes: list[str] = []
    status, df = _run_with_timeout(ak.fund_manager_history_em, symbol=fund_code, timeout_sec=timeout_sec)
    if df is None:
        status2, df = _run_with_timeout(ak.fund_manager_history_em, fund=fund_code, timeout_sec=timeout_sec)
        status = status2 if status == "ok" else status
    if df is None or getattr(df, "empty", True):
        if status == "timeout":
            return None, None, ["akshare_manager_timeout"]
        if status == "error":
            return None, None, ["akshare_manager_error"]
        return None, None, ["akshare_manager_empty"]

    cols = list(df.columns)
    tenure_col = next((c for c in cols if "任职天数" in str(c) or "任职时长" in str(c)), None)
    ann_col = next((c for c in cols if "年化" in str(c) and "回报" in str(c)), None)
    ret_col = next((c for c in cols if "任职回报" in str(c) or ("收益" in str(c) and "任职" in str(c))), None)
    if tenure_col is None and ann_col is None and ret_col is None:
        return None, None, ["akshare_manager_schema_unexpected"]

    row0 = None
    try:
        row0 = df.iloc[0]
    except Exception:
        return None, None, ["akshare_manager_row_parse_failed"]
    if row0 is None:
        return None, None, ["akshare_manager_row_parse_failed"]

    tenure_days = _to_float(row0.get(tenure_col)) if tenure_col else None
    annual = _to_float(row0.get(ann_col)) if ann_col else None
    if annual is None and ret_col is not None and tenure_days and tenure_days > 30:
        total_ret = _to_float(row0.get(ret_col))
        if total_ret is not None:
            total_ret = total_ret / 100.0 if total_ret > 1 else total_ret
            annual = (1.0 + total_ret) ** (365.0 / max(30.0, tenure_days)) - 1.0
    if annual is not None and annual > 1.0:
        annual = annual / 100.0

    years = (tenure_days / 365.0) if isinstance(tenure_days, (int, float)) and tenure_days > 0 else None
    if years is None and annual is None:
        return None, None, ["akshare_manager_insufficient_fields"]

    score_raw = 0.0
    if years is not None:
        score_raw += min(2.5, max(0.0, years * 0.4))
    if annual is not None:
        score_raw += min(2.5, max(-0.5, annual * 6.0))
    score = float(max(0.0, min(5.0, score_raw)))
    notes.append("akshare_manager_score_ok")
    return score, annual, notes


def fetch_fund_fundamental_snapshot(fund_code: str) -> dict[str, Any]:
    code = (fund_code or "").strip()
    if not re.fullmatch(r"\d{6}", code):
        return FundamentalSnapshot(
            aum_billion=None,
            manager_score=None,
            manager_return_annual=None,
            stock_top10_concentration=None,
            stock_top5_concentration=None,
            stock_equity_ratio=None,
            holding_drift=None,
            quarter_samples=0,
            top_holdings=[],
            source_notes=["invalid_code"],
            context_chunks=[],
        ).to_dict()

    cached = _CACHE.get(code)
    now = time.monotonic()
    if cached is not None and now - cached[0] < _TTL_SEC:
        return dict(cached[1])

    notes: list[str] = []
    aum_billion = None
    manager_name = None
    manager_score = None
    manager_ret = None
    eq_ratio = None
    top10 = None
    top5 = None
    top_holdings: list[dict[str, Any]] = []
    aum_billion, manager_name, notes_overview = _akshare_overview_fields(code)
    notes.extend(notes_overview)

    eq_ratio, top10, top5, top_holdings, qn_hold, notes_holdings = _akshare_holdings_features(code)
    notes.extend(notes_holdings)
    manager_score, manager_ret, notes_mgr = _akshare_manager_quality_score(code)
    notes.extend(notes_mgr)

    drift, qn_drift = _akshare_portfolio_drift(code, int(settings.fundamental_akshare_quarters))
    qn = max(int(qn_hold or 0), int(qn_drift or 0))
    if qn > 0:
        notes.append(f"akshare_quarters={qn}")
    elif "akshare_unavailable_or_empty" not in notes:
        notes.append("akshare_unavailable_or_empty")

    chunks: list[str] = []
    chunks.append(
        "Fundamental Source Snapshot: "
        f"aum_billion={aum_billion}, manager={manager_name}, manager_score={manager_score}, manager_return_annual={manager_ret}, "
        f"stock_equity_ratio={eq_ratio}, top10_concentration={top10}, top5_concentration={top5}, holding_drift={drift}."
    )
    if aum_billion is not None:
        chunks.append(f"AUM Snapshot: latest reported size about {aum_billion:.2f} bn CNY.")
    if manager_name:
        chunks.append(f"Manager Snapshot: {manager_name}.")
    if manager_score is not None:
        chunks.append(f"Manager Quality Score (rule): {manager_score:.2f}.")
    if top10 is not None:
        lv = "高集中" if top10 >= 0.5 else ("中集中" if top10 >= 0.3 else "低集中")
        chunks.append(f"Holding Concentration: top10={top10:.2%}, level={lv}.")
    if drift is not None:
        chunks.append(f"Style Drift (quarter avg): {drift:.2%} across {qn} quarters.")

    snap = FundamentalSnapshot(
        aum_billion=aum_billion,
        manager_score=manager_score,
        manager_return_annual=manager_ret,
        stock_top10_concentration=top10,
        stock_top5_concentration=top5,
        stock_equity_ratio=eq_ratio,
        holding_drift=drift,
        quarter_samples=qn,
        top_holdings=top_holdings,
        source_notes=notes,
        context_chunks=chunks,
    ).to_dict()
    _CACHE[code] = (now, snap)
    return dict(snap)

