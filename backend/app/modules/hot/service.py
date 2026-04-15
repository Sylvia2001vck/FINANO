from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.hot.models import HotNews


SAMPLE_NEWS = [
    {
        "title": "美联储维持利率不变，市场关注后续降息路径",
        "summary": "利率决议保持稳定，成长和高股息板块情绪分化，适合在复盘中观察仓位与风险暴露。",
        "source": "Finano Demo Feed",
    },
    {
        "title": "AI 算力板块波动加剧，龙头成交显著放大",
        "summary": "热点延续但日内分歧增强，适合结合交易纪律与止盈规则复盘执行是否到位。",
        "source": "Finano Demo Feed",
    },
]


def bootstrap_hot_news(db: Session) -> None:
    existing = db.scalar(select(HotNews.id).limit(1))
    if existing:
        return

    now = datetime.utcnow()
    for index, item in enumerate(SAMPLE_NEWS):
        db.add(
            HotNews(
                title=item["title"],
                summary=item["summary"],
                source=item["source"],
                publish_time=now - timedelta(hours=index),
                created_at=now,
            )
        )
    db.commit()


def list_hot_news(db: Session) -> list[HotNews]:
    return list(db.scalars(select(HotNews).order_by(HotNews.publish_time.desc())))
