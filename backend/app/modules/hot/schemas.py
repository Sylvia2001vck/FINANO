from datetime import datetime

from pydantic import BaseModel, ConfigDict


class HotNewsRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int | None = None
    news_id: str
    rank: int
    title: str
    summary: str
    source: str
    batch_time: datetime
    publish_time: datetime
    sentiment_score: float | None = None
    created_at: datetime


class HotNewsSnapshotRead(BaseModel):
    items: list[HotNewsRead]
    batch_time: datetime
    updated_at: datetime
