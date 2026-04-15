from datetime import datetime

from pydantic import BaseModel, ConfigDict


class HotNewsRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    summary: str
    source: str
    publish_time: datetime
    created_at: datetime
