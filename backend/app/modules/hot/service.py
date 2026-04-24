from __future__ import annotations

import hashlib
import json
import logging
import threading
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.modules.hot.models import HotNews, HotNewsSnapshot

logger = logging.getLogger(__name__)

try:
    from redis import Redis
except Exception:  # pragma: no cover - runtime optional
    Redis = None  # type: ignore[assignment]

_HOT_CACHE_KEY = "hot:current_top"
_LOCAL_CACHE: dict[str, tuple[float, dict[str, Any]]] = {}
_CACHE_LOCK = threading.Lock()
_REDIS_CLIENT: Any = None
_REDIS_READY = False

SAMPLE_POOL = [
    {"title": "美联储维持利率不变，市场关注后续降息路径", "source": "财联社", "summary": "利率路径预期分化，成长与高股息风格切换加快。"},
    {"title": "AI 算力板块成交放大，龙头波动显著抬升", "source": "华尔街见闻", "summary": "热度仍高但分歧扩大，短线追高风险提升。"},
    {"title": "黄金与资源品联动走强，防御资产再获关注", "source": "新浪财经", "summary": "宏观不确定性上升带动避险与通胀交易升温。"},
    {"title": "银行红利策略回暖，低波资产配置需求上行", "source": "东方财富", "summary": "高股息与低估值组合在震荡市中表现稳健。"},
    {"title": "新能源链条分化延续，上游与整机景气错位", "source": "财联社", "summary": "产业链盈利传导不均，需关注库存周期拐点。"},
    {"title": "北向资金净流入修复，核心宽基获增配", "source": "华尔街见闻", "summary": "外资偏好再平衡，估值与流动性形成短期支撑。"},
    {"title": "半导体设备指数震荡加剧，机构分歧升温", "source": "新浪财经", "summary": "业绩兑现与估值约束并存，短期弹性加大。"},
    {"title": "医药创新主题回暖，政策预期推动估值修复", "source": "东方财富", "summary": "风险偏好提升背景下，成长医药重获关注。"},
    {"title": "消费复苏节奏不均，必选与可选表现剪刀差", "source": "财联社", "summary": "结构性复苏延续，行业轮动速度加快。"},
    {"title": "债市收益率震荡下行，固收+策略再受青睐", "source": "华尔街见闻", "summary": "低波资金偏好提升，久期资产受益明显。"},
    {"title": "军工主题异动，订单预期与估值修复共振", "source": "新浪财经", "summary": "主题活跃度回升，但持续性仍需业绩验证。"},
    {"title": "跨境ETF成交活跃，海外科技波动传导增强", "source": "东方财富", "summary": "全球风险资产联动加深，配置需控制汇率风险。"},
]


def _floor_to_hour(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.replace(minute=0, second=0, microsecond=0)


def _news_id(title: str, source: str) -> str:
    h = hashlib.sha1(f"{source}::{title}".encode("utf-8")).hexdigest()
    return h[:20]


def _score_item(item: dict[str, str], batch_time: datetime) -> float:
    s = int(hashlib.md5(f"{batch_time.isoformat()}::{item['title']}".encode("utf-8")).hexdigest()[:6], 16)
    return float((s % 1000) / 1000.0)


def _build_hourly_top_news(batch_time: datetime, top_n: int) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for idx, item in enumerate(SAMPLE_POOL):
        score = _score_item(item, batch_time) + (0.0005 * (len(SAMPLE_POOL) - idx))
        candidates.append(
            {
                "news_id": _news_id(item["title"], item["source"]),
                "title": item["title"],
                "summary": item["summary"],
                "source": item["source"],
                "publish_time": batch_time - timedelta(minutes=5 * idx),
                "sentiment_score": round((score - 0.5) * 2.0, 3),
                "hot_score": score,
            }
        )
    candidates.sort(key=lambda x: x["hot_score"], reverse=True)
    deduped: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for item in candidates:
        nid = str(item.get("news_id") or "")
        if not nid or nid in seen_ids:
            continue
        seen_ids.add(nid)
        deduped.append(item)
        if len(deduped) >= top_n:
            break
    return deduped


def _get_redis_client() -> Any | None:
    global _REDIS_CLIENT, _REDIS_READY
    if _REDIS_READY:
        return _REDIS_CLIENT
    _REDIS_READY = True
    if not settings.redis_url or Redis is None:
        return None
    try:
        _REDIS_CLIENT = Redis.from_url(
            settings.redis_url,
            socket_timeout=float(settings.redis_socket_timeout_sec),
            decode_responses=True,
        )
        _REDIS_CLIENT.ping()
        return _REDIS_CLIENT
    except Exception:
        logger.warning("hot redis unavailable, fallback to in-memory cache", exc_info=True)
        _REDIS_CLIENT = None
        return None


def _cache_get() -> dict[str, Any] | None:
    rd = _get_redis_client()
    if rd is not None:
        try:
            raw = rd.get(_HOT_CACHE_KEY)
            if raw:
                return json.loads(raw)
        except Exception:
            logger.debug("hot redis read failed", exc_info=True)
    with _CACHE_LOCK:
        rec = _LOCAL_CACHE.get(_HOT_CACHE_KEY)
        if not rec:
            return None
        exp_ts, payload = rec
        if datetime.now(tz=timezone.utc).timestamp() > exp_ts:
            return None
        return payload


def _cache_set(payload: dict[str, Any]) -> None:
    ttl = int(settings.hot_cache_ttl_sec)
    rd = _get_redis_client()
    if rd is not None:
        try:
            rd.setex(_HOT_CACHE_KEY, ttl, json.dumps(payload, ensure_ascii=False))
        except Exception:
            logger.debug("hot redis write failed", exc_info=True)
    with _CACHE_LOCK:
        _LOCAL_CACHE[_HOT_CACHE_KEY] = (datetime.now(tz=timezone.utc).timestamp() + ttl, payload)


def refresh_hot_news_batch(db: Session, *, force: bool = False, now: datetime | None = None) -> dict[str, Any]:
    now_dt = now or datetime.now(tz=timezone.utc)
    batch_time = _floor_to_hour(now_dt)
    top_n = int(settings.hot_top_n)

    existed = list(
        db.scalars(
            select(HotNewsSnapshot).where(HotNewsSnapshot.batch_time == batch_time).order_by(HotNewsSnapshot.rank.asc())
        )
    )
    if existed and not force:
        payload = _snapshot_rows_to_payload(existed)
        _cache_set(payload)
        return payload

    rows = _build_hourly_top_news(batch_time, top_n)
    if existed:
        db.execute(delete(HotNewsSnapshot).where(HotNewsSnapshot.batch_time == batch_time))
        db.flush()

    now_naive = datetime.utcnow()
    created: list[HotNewsSnapshot] = []
    for rank, item in enumerate(rows, start=1):
        created.append(
            HotNewsSnapshot(
                news_id=item["news_id"],
                title=item["title"],
                summary=item["summary"],
                source=item["source"],
                rank=rank,
                batch_time=batch_time.replace(tzinfo=None),
                publish_time=item["publish_time"].replace(tzinfo=None),
                sentiment_score=float(item["sentiment_score"]),
                created_at=now_naive,
            )
        )
    db.add_all(created)
    db.commit()
    payload = _snapshot_rows_to_payload(created)
    _cache_set(payload)
    return payload


def _snapshot_rows_to_payload(rows: list[HotNewsSnapshot]) -> dict[str, Any]:
    if not rows:
        now = datetime.utcnow()
        return {"items": [], "batch_time": now.isoformat(), "updated_at": now.isoformat()}
    ordered = sorted(rows, key=lambda x: x.rank)
    batch_time = ordered[0].batch_time
    updated_at = max(x.created_at for x in ordered)
    items: list[dict[str, Any]] = []
    for x in ordered:
        items.append(
            {
                "id": x.id,
                "news_id": x.news_id,
                "rank": x.rank,
                "title": x.title,
                "summary": x.summary,
                "source": x.source,
                "batch_time": x.batch_time.isoformat(),
                "publish_time": x.publish_time.isoformat(),
                "sentiment_score": x.sentiment_score,
                "created_at": x.created_at.isoformat(),
            }
        )
    return {
        "items": items,
        "batch_time": batch_time.isoformat(),
        "updated_at": updated_at.isoformat(),
    }


def bootstrap_hot_news(db: Session) -> None:
    # 兼容老表：若历史表空则先塞两条演示数据
    old_existing = db.scalar(select(HotNews.id).limit(1))
    if not old_existing:
        now = datetime.utcnow()
        db.add(
            HotNews(
                title="美联储维持利率不变，市场关注后续降息路径",
                summary="演示旧表数据（兼容保留）；热点主读取已迁移到快照表。",
                source="Finano Demo Feed",
                publish_time=now,
                created_at=now,
            )
        )
        db.commit()
    refresh_hot_news_batch(db, force=False)


def list_hot_news_snapshot(db: Session) -> dict[str, Any]:
    cached = _cache_get()
    if cached:
        return cached
    latest_batch = db.scalar(select(HotNewsSnapshot.batch_time).order_by(HotNewsSnapshot.batch_time.desc()).limit(1))
    rows: list[HotNewsSnapshot] = []
    if latest_batch is not None:
        rows = list(
            db.scalars(
                select(HotNewsSnapshot)
                .where(HotNewsSnapshot.batch_time == latest_batch)
                .order_by(HotNewsSnapshot.rank.asc())
            )
        )
    if rows:
        payload = _snapshot_rows_to_payload(rows)
        _cache_set(payload)
        return payload
    return refresh_hot_news_batch(db, force=True)


def start_hot_scheduler(session_factory):
    if not settings.hot_scheduler_enabled:
        return None, None
    stop_event = threading.Event()

    def _worker():
        interval = max(300, int(settings.hot_refresh_interval_sec))
        while not stop_event.is_set():
            db = session_factory()
            try:
                refresh_hot_news_batch(db, force=False)
            except Exception:
                logger.exception("hot scheduler refresh failed")
            finally:
                db.close()
            stop_event.wait(interval)

    t = threading.Thread(target=_worker, daemon=True, name="hot-news-scheduler")
    t.start()
    return stop_event, t
