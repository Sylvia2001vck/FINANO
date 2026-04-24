from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.responses import success_response
from app.core.security import get_current_user
from app.db.session import get_db
from app.modules.replay.schemas import ReplayAnalyzeNotePayload
from app.modules.replay.service import analyze_replay_by_note, analyze_replay_by_trade

router = APIRouter(prefix="/replay", tags=["replay"])


@router.post("/analyze/trade/{trade_id}")
def replay_by_trade(trade_id: int, current_user=Depends(get_current_user), db: Session = Depends(get_db)):
    result = analyze_replay_by_trade(db, current_user.id, trade_id)
    return success_response(data=result.model_dump(), message="交易复盘分析完成")


@router.post("/analyze/note")
def replay_by_note(
    payload: ReplayAnalyzeNotePayload,
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    result = analyze_replay_by_note(db, current_user.id, payload)
    return success_response(data=result.model_dump(), message="心得复盘分析完成")
