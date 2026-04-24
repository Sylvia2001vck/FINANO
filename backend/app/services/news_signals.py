from __future__ import annotations

from datetime import datetime
from typing import Any

import httpx

_CLS_URL = "https://www.cls.cn/nodeapi/telegraphList"
_NEG_WORDS = [
    "处罚",
    "立案",
    "调查",
    "诉讼",
    "纠纷",
    "爆雷",
    "违约",
    "高管变动",
    "减持",
    "退市",
    "暴跌",
    "商誉",
    "亏损",
    "问询",
    "风险提示",
]
_POLICY_WORDS = [
    "政策",
    "监管",
    "发改",
    "财政",
    "央行",
    "工信部",
    "国常会",
    "会议",
    "规划",
    "产业",
]


def _safe_text(v: Any) -> str:
    s = str(v or "").strip()
    return s


def _build_keywords(fund: dict[str, Any]) -> list[str]:
    kws: list[str] = []
    track = _safe_text(fund.get("track"))
    if track:
        kws.append(track)
    name = _safe_text(fund.get("name"))
    if name:
        kws.extend([x for x in [name[:8], name[:4]] if x and x not in kws])
    for h in list(fund.get("top_holdings") or [])[:5]:
        hn = _safe_text(h.get("name"))
        hc = _safe_text(h.get("code"))
        if hn:
            kws.append(hn)
        if hc:
            kws.append(hc)
    uniq: list[str] = []
    for k in kws:
        kk = k.strip()
        if len(kk) < 2:
            continue
        if kk not in uniq:
            uniq.append(kk)
    return uniq[:12]


def _match_any(text: str, words: list[str]) -> bool:
    return any(w in text for w in words if w)


def _fetch_cls_feed(rn: int = 80, timeout: float = 8.0) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for page in (1, 2):
        try:
            r = httpx.get(
                _CLS_URL,
                params={"page": page, "rn": rn},
                timeout=timeout,
                headers={"User-Agent": "Mozilla/5.0", "Referer": "https://www.cls.cn/telegraph"},
            )
            r.raise_for_status()
            payload = r.json()
            rows = (((payload or {}).get("data") or {}).get("roll_data") or [])
            if isinstance(rows, list):
                out.extend([x for x in rows if isinstance(x, dict)])
        except Exception:
            continue
    return out


def _to_iso(ctime: Any) -> str | None:
    try:
        ts = int(ctime)
        if ts > 1_000_000_000:
            return datetime.fromtimestamp(ts).isoformat()
    except Exception:
        return None
    return None


def fetch_news_signals_for_fund(fund: dict[str, Any], *, timeout: float = 8.0) -> dict[str, Any]:
    kws = _build_keywords(fund)
    rows = _fetch_cls_feed(rn=60, timeout=timeout)
    if not rows:
        return {
            "source": "cls_telegraph",
            "fetched_at": datetime.utcnow().isoformat(),
            "keywords": kws,
            "fundamental_news": [],
            "risk_alerts": [],
            "policy_signal_score": 0.0,
            "black_swan_score": 0.0,
            "note": "news_feed_unavailable",
        }

    matched: list[dict[str, Any]] = []
    for it in rows:
        title = _safe_text(it.get("title"))
        content = _safe_text(it.get("content") or it.get("brief"))
        blob = f"{title} {content}"
        if kws and not _match_any(blob, kws):
            continue
        matched.append(
            {
                "title": title,
                "content": content[:180],
                "url": _safe_text(it.get("shareurl") or ""),
                "publish_time": _to_iso(it.get("ctime")),
                "blob": blob,
            }
        )

    fundamental_news: list[dict[str, Any]] = []
    risk_alerts: list[dict[str, Any]] = []
    for m in matched[:30]:
        blob = m["blob"]
        neg_hits = [w for w in _NEG_WORDS if w in blob]
        pol_hits = [w for w in _POLICY_WORDS if w in blob]
        if pol_hits:
            fundamental_news.append(
                {
                    "title": m["title"],
                    "summary": m["content"],
                    "url": m["url"],
                    "publish_time": m["publish_time"],
                    "tags": pol_hits[:3],
                    "impact": "policy_change_watch",
                }
            )
        if neg_hits:
            risk_alerts.append(
                {
                    "title": m["title"],
                    "summary": m["content"],
                    "url": m["url"],
                    "publish_time": m["publish_time"],
                    "tags": neg_hits[:4],
                    "negative_score": min(1.0, 0.25 * len(neg_hits)),
                }
            )

    policy_score = min(1.0, 0.18 * len(fundamental_news))
    swan_score = min(1.0, sum(float(x.get("negative_score") or 0.0) for x in risk_alerts[:6]))
    return {
        "source": "cls_telegraph",
        "fetched_at": datetime.utcnow().isoformat(),
        "keywords": kws,
        "fundamental_news": fundamental_news[:8],
        "risk_alerts": risk_alerts[:8],
        "policy_signal_score": round(policy_score, 3),
        "black_swan_score": round(swan_score, 3),
        "note": "ok",
    }
