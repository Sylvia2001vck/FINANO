from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.responses import success_response
from app.core.security import get_current_user
from app.db.session import get_db
from app.modules.note.schemas import NoteCreate, NoteRead
from app.modules.note.service import create_note, list_notes


router = APIRouter(prefix="/notes", tags=["notes"])


@router.get("")
def get_notes(current_user=Depends(get_current_user), db: Session = Depends(get_db)):
    notes = list_notes(db, current_user.id)
    data = [NoteRead.model_validate(note).model_dump() for note in notes]
    return success_response(data=data)


@router.post("")
def add_note(payload: NoteCreate, current_user=Depends(get_current_user), db: Session = Depends(get_db)):
    note = create_note(db, current_user.id, payload)
    return success_response(data=NoteRead.model_validate(note).model_dump(), message="复盘笔记创建成功")
