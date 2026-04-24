from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


ReplayIntent = Literal["trade", "note"]
ReplayRoute = Literal["history_compare", "native_analysis"]
ReplaySource = Literal["sql", "faiss", "mixed", "none"]


class ReplayAnalyzeNotePayload(BaseModel):
    note_id: int | None = Field(default=None, ge=1)
    content: str | None = Field(default=None, min_length=2, max_length=5000)
    title: str | None = Field(default=None, max_length=100)


class ReplayMatchedTrade(BaseModel):
    trade_id: int
    symbol: str
    name: str
    trade_date: datetime | str
    amount: float
    profit: float
    similarity: float = 0.0
    notes: list[str] = Field(default_factory=list)


class ReplayMatchedNote(BaseModel):
    note_id: int
    title: str
    content_preview: str
    created_at: datetime | str
    similarity: float = 0.0
    trade_id: int | None = None
    trade_symbol: str | None = None
    trade_profit: float | None = None


class ReplayAnalyzeResult(BaseModel):
    intent: ReplayIntent
    route: ReplayRoute
    retrieval_source: ReplaySource
    top_score: float = 0.0
    similarity_threshold: float
    has_match: bool
    analysis: str
    suggestions: list[str] = Field(default_factory=list)
    matched_trades: list[ReplayMatchedTrade] = Field(default_factory=list)
    matched_notes: list[ReplayMatchedNote] = Field(default_factory=list)
    trace: list[str] = Field(default_factory=list)
