from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class PostCreate(BaseModel):
    title: str = Field(min_length=1, max_length=100)
    content: str = Field(min_length=1)


class PostRead(PostCreate):
    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int
    likes: int
    comments: int
    created_at: datetime
    updated_at: datetime
