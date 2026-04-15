from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class NoteCreate(BaseModel):
    trade_id: int | None = None
    title: str = Field(min_length=1, max_length=100)
    content: str = Field(min_length=1)
    tags: str | None = None


class NoteRead(NoteCreate):
    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int
    created_at: datetime
    updated_at: datetime
