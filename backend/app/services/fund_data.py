"""
真实行情 / 估值适配层（东方财富 · 天天基金 JSONP）。

接口：https://fundgz.1234567.com.cn/js/{code}.js
含：请求间隔限流、短期缓存、失败降级（由调用方不合并 live_quote）。
"""

from __future__ import annotations

import json
import logging
import re
import time
from typing import Any

import httpx

logger = logging.getLogger(__name__)

_TIANTIAN_GZ_URL = "https://fundgz.1234567.com.cn/js/{code}.js"

# 两次真实 HTTP 请求之间至少间隔（秒），降低对公开接口的请求频率（估值接口）
_MIN_HTTP_INTERVAL_SEC = 5.0
# 历史净值 lsjz 批量扫描时使用更短间隔；候选数已由统计相似预筛控制，略降间隔以缩短 TOP10 等待
_MIN_LSJZ_INTERVAL_SEC = 0.22
# 同一基金代码估值缓存时间（秒），列表接口连续读盘时避免重复打网
_CACHE_TTL_SEC = 60.0

_last_http_mono: float = 0.0
_last_lsjz_mono: float = 0.0
_quote_cache: dict[str, tuple[float, dict[str, Any]]] = {}


def parse_tiantian_jsonp(body: str) -> dict[str, Any] | None:
    """解析 jsonpgz({...}); 形式。"""
    m = re.search(r"jsonpgz\s*\(\s*(\{[\s\S]*\})\s*\)\s*;?", body)
    if not m:
        return None
    try:
        return json.loads(m.group(1))
    except json.JSONDecodeError:
        return None


def _throttle_http() -> None:
    global _last_http_mono
    now = time.monotonic()
    gap = now - _last_http_mono
    if gap < _MIN_HTTP_INTERVAL_SEC:
        time.sleep(_MIN_HTTP_INTERVAL_SEC - gap)


def _throttle_lsjz() -> None:
    global _last_lsjz_mono
    now = time.monotonic()
    gap = now - _last_lsjz_mono
    if gap < _MIN_LSJZ_INTERVAL_SEC:
        time.sleep(_MIN_LSJZ_INTERVAL_SEC - gap)


def _normalize_quote_payload(code: str, data: dict[str, Any]) -> dict[str, Any]:
    """源站字段 + 演示/前端常用别名（gzjs/gssj 等）。"""
    gsz = str(data.get("gsz") or "")
    gszzl = str(data.get("gszzl") or "")
    gztime = str(data.get("gztime") or "")
    dwjz = str(data.get("dwjz") or "")
    return {
        "source": "eastmoney_tiantian_gz",
        "fundcode": str(data.get("fundcode") or code),
        "name": str(data.get("name") or ""),
        "jzrq": str(data.get("jzrq") or ""),
        "dwjz": dwjz,
        "gsz": gsz,
        "gszzl": gszzl,
        "gztime": gztime,
        # 别名（便于前端与课程文档统一阅读）
        "gzjs": gsz,
        "gssj": gztime,
    }


def fetch_fund_live_quote(fund_code: str, timeout: float = 8.0) -> dict[str, Any] | None:
    """
    拉取基金最新估值/净值相关字段（非交易接口）。
    带缓存与全局限流；成功返回 dict，失败返回 None。
    """
    code = fund_code.strip()
    if not re.fullmatch(r"\d{6}", code):
        return None

    now = time.monotonic()
    cached = _quote_cache.get(code)
    if cached is not None:
        ts, payload = cached
        if now - ts < _CACHE_TTL_SEC:
            return payload

    url = _TIANTIAN_GZ_URL.format(code=code)
    try:
        _throttle_http()
        r = httpx.get(
            url,
            timeout=timeout,
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                "Referer": f"https://fund.eastmoney.com/{code}.html",
            },
        )
        r.raise_for_status()
        raw = r.text
    except Exception:
        logger.debug("fund live quote request failed: %s", code, exc_info=True)
        return None
    finally:
        global _last_http_mono
        _last_http_mono = time.monotonic()

    data = parse_tiantian_jsonp(raw)
    if not data:
        logger.debug("fund live quote parse failed: %s", code)
        return None

    payload = _normalize_quote_payload(code, data)
    _quote_cache[code] = (time.monotonic(), payload)
    return payload


def get_fund_real_time(fund_code: str) -> dict[str, Any] | None:
    """对外统一入口（与文档命名一致）。"""
    return fetch_fund_live_quote(fund_code)


# ---------- 历史净值（K 线 / 时间序列）----------
_LSJZ_URL = "https://fund.eastmoney.com/f10/F10DataApi.aspx"
_NAV_CACHE_TTL_SEC = 1800.0
_nav_hist_cache: dict[str, tuple[float, list[dict[str, Any]]]] = {}


def parse_lsjz_apidata_body(body: str) -> list[dict[str, Any]]:
    """
    解析 F10DataApi.aspx?type=lsjz 返回的 JS（apidata={ content:\"<table>...\" }）。
    提取：日期、单位净值、日增长率(%) → 转为小数日收益 daily_return。
    """
    rows: list[dict[str, Any]] = []
    pattern = re.compile(
        r"\|\s*(\d{4}-\d{2}-\d{2})\s*\|\s*([\d.]+)\s*\|\s*([\d.]+)\s*\|\s*([-+]?\d+\.?\d*)\s*%",
        re.MULTILINE,
    )
    for m in pattern.finditer(body):
        date_s, dwjz_s, _ljjz, pct_s = m.groups()
        try:
            pct_val = float(pct_s) / 100.0
        except ValueError:
            continue
        try:
            nav = float(dwjz_s)
        except ValueError:
            continue
        rows.append(
            {
                "date": date_s,
                "nav": nav,
                "daily_return": pct_val,
                "daily_pct_display": f"{pct_s}%",
            }
        )
    # 源站通常最新在上；按日期升序便于构造收益序列
    rows.sort(key=lambda x: x["date"])
    return rows


def fetch_fund_nav_history(fund_code: str, days: int = 90, timeout: float = 15.0) -> list[dict[str, Any]]:
    """
    拉取基金历史净值（近若干交易日，受单页条数限制最多一次取 200 条）。
    失败返回 []，不抛异常。
    """
    code = fund_code.strip()
    if not re.fullmatch(r"\d{6}", code):
        return []

    per = max(5, min(int(days), 200))
    now = time.monotonic()
    cache_key = f"{code}:{per}"
    cached = _nav_hist_cache.get(cache_key)
    if cached is not None:
        ts, payload = cached
        if now - ts < _NAV_CACHE_TTL_SEC:
            return list(payload)

    params = {"type": "lsjz", "code": code, "page": 1, "per": per}
    try:
        _throttle_lsjz()
        r = httpx.get(
            _LSJZ_URL,
            params=params,
            timeout=timeout,
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                "Referer": f"https://fund.eastmoney.com/{code}/lsjz.html",
            },
        )
        r.raise_for_status()
        text = r.text
    except Exception:
        logger.debug("fund nav history request failed: %s", code, exc_info=True)
        return []
    finally:
        global _last_lsjz_mono
        _last_lsjz_mono = time.monotonic()

    parsed = parse_lsjz_apidata_body(text)
    if len(parsed) > days:
        parsed = parsed[-days:]
    _nav_hist_cache[cache_key] = (time.monotonic(), list(parsed))
    return parsed
