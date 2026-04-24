from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.note.models import Note
from app.modules.note.schemas import NoteCreate
from app.modules.replay.service import upsert_note_embedding


def create_note(db: Session, user_id: int, payload: NoteCreate) -> Note:
    note = Note(user_id=user_id, **payload.model_dump())
    db.add(note)
    db.commit()
    db.refresh(note)
    try:
        upsert_note_embedding(db, user_id, note)
    except Exception:
        # 复盘向量索引失败不影响主流程
        pass
    return note


def list_notes(db: Session, user_id: int) -> list[Note]:
    return list(db.scalars(select(Note).where(Note.user_id == user_id).order_by(Note.created_at.desc())))
