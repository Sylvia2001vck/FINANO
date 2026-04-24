"""
真实行情 / 估值适配层（东方财富 · 天天基金 JSONP）。

接口：https://fundgz.1234567.com.cn/js/{code}.js
含：请求间隔限流、短期缓存、失败降级（由调用方不合并 live_quote）。
"""

from __future__ import annotations

import json
import logging
import math
import re
import time
from collections import OrderedDict
from copy import deepcopy
from typing import Any

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)

try:
    from redis import Redis
except Exception:  # pragma: no cover - optional dependency at runtime
    Redis = None  # type: ignore[assignment]

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
    parsed: list[dict[str, Any]] = []
    try:
        _throttle_lsjz()
        for _ in range(2):
            try:
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
                parsed = parse_lsjz_apidata_body(text)
                if parsed:
                    break
            except Exception:
                parsed = []
            time.sleep(0.08)
    except Exception:
        logger.debug("fund nav history request failed: %s", code, exc_info=True)
        parsed = []
    finally:
        global _last_lsjz_mono
        _last_lsjz_mono = time.monotonic()

    # F10DataApi 偶发空表/反爬时，回退到 JSON API 区间拉取，提升 nav_history 确定性
    if not parsed:
        end = time.strftime("%Y-%m-%d")
        start_ts = time.time() - max(35, int(days * 1.8)) * 86400
        start = time.strftime("%Y-%m-%d", time.localtime(start_ts))
        try:
            payload = fetch_lsjz_eastmoney_json_api_cached(
                code,
                start_date=start,
                end_date=end,
                timeout=min(45.0, timeout + 6.0),
            )
            pts = list(payload.get("points_asc") or [])
            rebuilt: list[dict[str, Any]] = []
            prev_nav: float | None = None
            for p in pts:
                d = str(p.get("date") or "").strip()
                if not d:
                    continue
                try:
                    nav = float(p.get("dwjz"))
                except Exception:
                    continue
                jzzzl = p.get("jzzzl")
                if isinstance(jzzzl, str):
                    s = jzzzl.replace("%", "").strip()
                    try:
                        daily_return = float(s) / 100.0
                    except Exception:
                        daily_return = None
                elif isinstance(jzzzl, (int, float)):
                    daily_return = float(jzzzl) / (100.0 if abs(float(jzzzl)) > 2 else 1.0)
                else:
                    daily_return = None
                if daily_return is None:
                    if prev_nav and prev_nav > 0:
                        daily_return = nav / prev_nav - 1.0
                    else:
                        daily_return = 0.0
                rebuilt.append(
                    {
                        "date": d,
                        "nav": nav,
                        "daily_return": float(daily_return),
                        "daily_pct_display": f"{float(daily_return) * 100:.2f}%",
                    }
                )
                prev_nav = nav
            parsed = rebuilt
        except Exception:
            logger.debug("fund nav json-api fallback failed: %s", code, exc_info=True)
            parsed = []

    if len(parsed) > days:
        parsed = parsed[-days:]
    _nav_hist_cache[cache_key] = (time.monotonic(), list(parsed))
    return parsed


# ---------- 天天基金 JSON API（f10/lsjz，需 fundf10 Referer，否则 403）----------
_LSJZ_JSON_API = "https://api.fund.eastmoney.com/f10/lsjz"
_FUND_F10_REFERER = "https://fundf10.eastmoney.com/"
# 带 startDate/endDate 时接口常固定每页约 20 条，需分页；单次任务内连续翻页用较短间隔
_LSJZ_BURST_SLEEP_SEC = 0.08
_LSJZ_MAX_PAGES = 400

# 区间查询（start_date+end_date）结果：LRU + 热命中 / 增量合并，降低重复全量翻页
_lsjz_http_range_cache: OrderedDict[str, tuple[float, dict[str, Any]]] = OrderedDict()
_redis_client: Any = None
_redis_init_attempted = False


def _lsjz_range_cache_key(code: str, start_date: str, end_date: str) -> str:
    return f"{code.strip()}|{start_date}|{end_date}"


def _lsjz_range_cache_trim() -> None:
    max_n = int(settings.fund_lsjz_http_cache_max)
    while len(_lsjz_http_range_cache) > max_n:
        _lsjz_http_range_cache.popitem(last=False)


def _redis_range_key(key: str) -> str:
    prefix = (settings.redis_cache_prefix or "finano").strip() or "finano"
    return f"{prefix}:funds:lsjz_range:{key}"


def _get_redis_client() -> Any | None:
    """懒初始化 Redis；不可用时返回 None，并保持内存缓存路径可用。"""
    global _redis_client, _redis_init_attempted
    if _redis_init_attempted:
        return _redis_client
    _redis_init_attempted = True
    if Redis is None:
        logger.info("redis package not installed; using in-process cache only")
        _redis_client = None
        return None
    url = (settings.redis_url or "").strip()
    if not url:
        _redis_client = None
        return None
    try:
        timeout = float(settings.redis_socket_timeout_sec)
        cli = Redis.from_url(url, decode_responses=True, socket_timeout=timeout, socket_connect_timeout=timeout)
        cli.ping()
        _redis_client = cli
        logger.info("redis cache enabled for lsjz range cache")
    except Exception:
        logger.warning("redis unavailable; fallback to in-process cache", exc_info=True)
        _redis_client = None
    return _redis_client


def _lsjz_cache_get(key: str) -> tuple[float, dict[str, Any]] | None:
    """优先读本地 LRU，再读 Redis 并回填本地。"""
    entry = _lsjz_http_range_cache.get(key)
    if entry is not None:
        return entry

    cli = _get_redis_client()
    if cli is None:
        return None
    try:
        raw = cli.get(_redis_range_key(key))
        if not raw:
            return None
        obj = json.loads(raw)
        ts = float(obj.get("ts") or 0.0)
        payload = obj.get("payload")
        if not isinstance(payload, dict):
            return None
        _lsjz_http_range_cache[key] = (ts, payload)
        _lsjz_http_range_cache.move_to_end(key)
        _lsjz_range_cache_trim()
        return ts, payload
    except Exception:
        logger.debug("redis get failed for lsjz range cache", exc_info=True)
        return None


def _lsjz_cache_set(key: str, ts: float, payload: dict[str, Any]) -> None:
    _lsjz_http_range_cache[key] = (ts, payload)
    _lsjz_http_range_cache.move_to_end(key)
    _lsjz_range_cache_trim()

    cli = _get_redis_client()
    if cli is None:
        return
    try:
        ttl_sec = max(120, int(settings.fund_lsjz_stale_max_sec) + 300)
        raw = json.dumps({"ts": ts, "payload": payload}, ensure_ascii=False)
        cli.setex(_redis_range_key(key), ttl_sec, raw)
    except Exception:
        logger.debug("redis set failed for lsjz range cache", exc_info=True)


def merge_lsjz_points_asc(
    base: list[dict[str, Any]],
    extra: list[dict[str, Any]],
    *,
    start_date: str,
    end_date: str,
) -> list[dict[str, Any]]:
    """按日期去重合并并按日期升序，限制在 [start_date, end_date]。"""
    by_date: dict[str, dict[str, Any]] = {}
    for p in base:
        d = str(p.get("date") or "").strip()
        if d and start_date <= d <= end_date:
            by_date[d] = p
    for p in extra:
        d = str(p.get("date") or "").strip()
        if d and start_date <= d <= end_date:
            by_date[d] = p
    return sorted(by_date.values(), key=lambda z: str(z.get("date") or ""))


def _lsjz_incremental_fetch_and_merge(
    fund_code: str,
    start_date: str,
    end_date: str,
    cached: dict[str, Any],
    *,
    timeout: float,
) -> dict[str, Any] | None:
    """
    在已有区间快照上，仅拉取 [最新已缓存日期, end_date] 重叠区间并合并。
    若已覆盖 end_date，则返回带 cache_touch 标记的快照（无需再打东财）。
    """
    pts = cached.get("points_asc") or []
    if not pts:
        return None
    last_d = str(pts[-1].get("date") or "").strip()
    if not last_d:
        return None
    if last_d >= end_date:
        out = deepcopy(cached)
        out["cache_touch"] = True
        out["incremental"] = "boundary_ok"
        return out

    inc = fetch_lsjz_eastmoney_json_api(
        fund_code,
        page_index=1,
        page_size=200,
        start_date=last_d,
        end_date=end_date,
        timeout=timeout,
    )
    if not inc.get("ok"):
        return None
    merged_asc = merge_lsjz_points_asc(
        pts,
        inc.get("points_asc") or [],
        start_date=start_date,
        end_date=end_date,
    )
    out = deepcopy(cached)
    out["points_asc"] = merged_asc
    out["points_desc"] = list(reversed(merged_asc))
    out["incremental"] = "merged_tail"
    out["pages_fetched"] = int(cached.get("pages_fetched") or 0) + int(inc.get("pages_fetched") or 0)
    if inc.get("range_truncated"):
        out["range_truncated"] = True
    out.pop("cache_touch", None)
    return out


def fetch_lsjz_eastmoney_json_api_cached(
    fund_code: str,
    *,
    page_index: int = 1,
    page_size: int = 50,
    start_date: str | None = None,
    end_date: str | None = None,
    timeout: float = 45.0,
) -> dict[str, Any]:
    """
    带服务端缓存的 lsjz JSON 拉取（本地 LRU；配置 REDIS_URL 时为多副本共享缓存）。

    - 仅对「同时提供 start_date + end_date」的区间模式启用 LRU；
      单页兼容模式仍每次直拉（通常用于调试或非区间场景）。
    - 热 TTL 内直接返回副本，不打东财；
    - 热 TTL 外、最大陈旧时间内尝试增量合并尾部区间，避免重复拉整段历史。
    """
    code = fund_code.strip()
    range_mode = bool(start_date and end_date)
    if not range_mode:
        return fetch_lsjz_eastmoney_json_api(
            fund_code,
            page_index=page_index,
            page_size=page_size,
            start_date=start_date,
            end_date=end_date,
            timeout=timeout,
        )

    key = _lsjz_range_cache_key(code, start_date or "", end_date or "")
    now = time.time()

    entry = _lsjz_cache_get(key)
    if entry is not None:
        ts, payload = entry
        age = max(0.0, now - ts)
        if isinstance(payload, dict) and payload.get("ok"):
            hot = float(settings.fund_lsjz_hot_ttl_sec)
            stale_max = float(settings.fund_lsjz_stale_max_sec)
            if age < hot:
                return deepcopy(payload)
            if age < stale_max and bool(settings.fund_lsjz_incremental_merge):
                merged = _lsjz_incremental_fetch_and_merge(
                    code, start_date or "", end_date or "", payload, timeout=timeout
                )
                if merged is not None:
                    _lsjz_cache_set(key, now, merged)
                    return deepcopy(merged)

    out = fetch_lsjz_eastmoney_json_api(
        fund_code,
        page_index=page_index,
        page_size=page_size,
        start_date=start_date,
        end_date=end_date,
        timeout=timeout,
    )
    if isinstance(out, dict) and out.get("ok"):
        _lsjz_cache_set(key, now, out)
    return out


def _lsjz_extract_rows_and_total(payload: dict[str, Any]) -> tuple[list[dict[str, Any]], int | None]:
    data_block = payload.get("Data")
    if data_block is None:
        data_block = payload.get("data")
    total = payload.get("TotalCount")
    if total is None:
        total = payload.get("totalCount")
    rows: list[dict[str, Any]]
    if data_block is None:
        rows = []
    elif isinstance(data_block, list):
        rows = [x for x in data_block if isinstance(x, dict)]
    elif isinstance(data_block, dict):
        raw = (
            data_block.get("LSJZList")
            or data_block.get("lsjzList")
            or data_block.get("list")
            or []
        )
        rows = [x for x in raw if isinstance(x, dict)]
        if total is None:
            total = data_block.get("TotalCount") or data_block.get("totalCount")
    else:
        rows = []
    if isinstance(total, str) and total.isdigit():
        total = int(total)
    return rows, int(total) if isinstance(total, int) else None


def _lsjz_rows_to_points_desc(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    points_desc: list[dict[str, Any]] = []
    for item in rows:
        fsrq = str(item.get("FSRQ") or item.get("fsrq") or "").strip()
        dwjz_raw = item.get("DWJZ") if item.get("DWJZ") is not None else item.get("dwjz")
        if dwjz_raw is None or not fsrq:
            continue
        try:
            dwjz = float(str(dwjz_raw).replace(",", ""))
        except ValueError:
            continue
        jzzzl = item.get("JZZZL") or item.get("jzzzl") or item.get("dailyGrowth")
        points_desc.append({"date": fsrq, "dwjz": dwjz, "jzzzl": jzzzl})
    return points_desc


def _lsjz_request(
    code: str,
    *,
    page_index: int,
    page_size: int,
    start_date: str | None,
    end_date: str | None,
    timeout: float,
) -> dict[str, Any]:
    params: dict[str, Any] = {
        "fundCode": code,
        "pageIndex": page_index,
        "pageSize": page_size,
    }
    if start_date:
        params["startDate"] = start_date
    if end_date:
        params["endDate"] = end_date
    _throttle_lsjz()
    r = httpx.get(
        _LSJZ_JSON_API,
        params=params,
        timeout=timeout,
        headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Referer": _FUND_F10_REFERER,
            "Accept": "application/json, text/plain, */*",
        },
    )
    r.raise_for_status()
    raw_text = r.text.strip()
    if raw_text.startswith("jQuery") or raw_text.startswith("callback"):
        raise ValueError("unexpected JSONP response")
    return json.loads(raw_text)


def fetch_lsjz_eastmoney_json_api(
    fund_code: str,
    *,
    page_index: int = 1,
    page_size: int = 50,
    start_date: str | None = None,
    end_date: str | None = None,
    timeout: float = 45.0,
) -> dict[str, Any]:
    """
    代理友好：拉取官方 JSON 历史净值列表（非 JSONP）。
    - 若同时提供 start_date、end_date（YYYY-MM-DD），按日期区间分页拉全（接口每页约 20 条）。
    - 否则为单页模式：page_index + page_size（兼容旧调用）。
    返回 points_asc：日期升序。
    """
    code = fund_code.strip()
    out: dict[str, Any] = {
        "ok": False,
        "fund_code": code,
        "points_desc": [],
        "points_asc": [],
        "total_count": None,
        "error": None,
        "source": "api.fund.eastmoney.com/f10/lsjz",
        "pages_fetched": 0,
        "range_truncated": False,
    }
    if not re.fullmatch(r"\d{6}", code):
        out["error"] = "invalid fund code"
        return out

    date_re = re.compile(r"^\d{4}-\d{2}-\d{2}$")
    range_mode = bool(start_date and end_date)
    if range_mode:
        if not date_re.match(start_date or "") or not date_re.match(end_date or ""):
            out["error"] = "invalid start_date or end_date"
            return out
    elif start_date or end_date:
        out["error"] = "start_date and end_date must be provided together"
        return out

    try:
        if range_mode:
            # 区间模式：先取第 1 页得到 TotalCount，再翻页（带日期时单页条数常被限制为 ~20）
            req_ps = 200
            payload = _lsjz_request(
                code,
                page_index=1,
                page_size=req_ps,
                start_date=start_date,
                end_date=end_date,
                timeout=timeout,
            )
            err = payload.get("ErrCode")
            if err not in (0, None, "0"):
                out["error"] = str(payload.get("ErrMsg") or payload.get("errMsg") or "lsjz ErrCode")
                return out
            rows_first, total = _lsjz_extract_rows_and_total(payload)
            api_ps = payload.get("PageSize")
            try:
                per_page = max(1, int(api_ps)) if api_ps is not None else max(1, len(rows_first) or 20)
            except (TypeError, ValueError):
                per_page = max(1, len(rows_first) or 20)
            merged: list[dict[str, Any]] = list(rows_first)
            total_pages = int(math.ceil(total / per_page)) if total and total > 0 else 1
            total_pages = min(total_pages, _LSJZ_MAX_PAGES)
            if total and total > 0 and total_pages * per_page < total:
                out["range_truncated"] = True

            pages_done = 1
            for p in range(2, total_pages + 1):
                time.sleep(_LSJZ_BURST_SLEEP_SEC)
                payload_n = _lsjz_request(
                    code,
                    page_index=p,
                    page_size=req_ps,
                    start_date=start_date,
                    end_date=end_date,
                    timeout=timeout,
                )
                err_n = payload_n.get("ErrCode")
                if err_n not in (0, None, "0"):
                    out["error"] = str(payload_n.get("ErrMsg") or payload_n.get("errMsg") or "lsjz ErrCode")
                    return out
                rows_n, _ = _lsjz_extract_rows_and_total(payload_n)
                if not rows_n:
                    break
                merged.extend(rows_n)
                pages_done = p

            # 按日期去重后升序
            by_date: dict[str, dict[str, Any]] = {}
            for item in merged:
                d = str(item.get("FSRQ") or item.get("fsrq") or "").strip()
                if d and d not in by_date:
                    by_date[d] = item
            merged_unique = sorted(by_date.values(), key=lambda x: str(x.get("FSRQ") or ""))
            points_asc = sorted(_lsjz_rows_to_points_desc(merged_unique), key=lambda z: z["date"])
            points_desc = list(reversed(points_asc))
            out["ok"] = True
            out["points_desc"] = points_desc
            out["points_asc"] = points_asc
            out["total_count"] = total
            out["pages_fetched"] = pages_done
            return out

        # ---------- 单页兼容（无日期）----------
        page_size = max(5, min(int(page_size), 200))
        page_index = max(1, int(page_index))
        payload = _lsjz_request(
            code,
            page_index=page_index,
            page_size=page_size,
            start_date=None,
            end_date=None,
            timeout=timeout,
        )
        err = payload.get("ErrCode")
        if err not in (0, None, "0"):
            out["error"] = str(payload.get("ErrMsg") or payload.get("errMsg") or "lsjz ErrCode")
            return out
    except json.JSONDecodeError as e:
        logger.warning("lsjz json decode failed: %s", e)
        out["error"] = f"json decode: {e}"
        return out
    except Exception as e:
        logger.warning("lsjz json api request failed: %s", e, exc_info=True)
        out["error"] = str(e)
        return out
    finally:
        global _last_lsjz_mono
        _last_lsjz_mono = time.monotonic()

    rows, total = _lsjz_extract_rows_and_total(payload)
    points_desc = _lsjz_rows_to_points_desc(rows)
    points_asc = sorted(points_desc, key=lambda z: z["date"])
    points_desc = list(reversed(points_asc))
    out["ok"] = True
    out["points_desc"] = points_desc
    out["points_asc"] = points_asc
    out["total_count"] = total
    out["pages_fetched"] = 1
    return out
