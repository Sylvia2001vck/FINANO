from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.responses import success_response
from app.core.security import get_current_user
from app.modules.fund_offline.service import get_offline_status, sync_fund_nav_snapshot
from app.modules.fund_offline.session import get_offline_db

router = APIRouter(prefix="/offline", tags=["fund-offline"])


@router.get("/status")
def offline_status(_user=Depends(get_current_user), db: Session = Depends(get_offline_db)):
    return success_response(data=get_offline_status(db), message="ok")


@router.post("/sync")
def offline_sync(
    full: bool = False,
    rebuild_index: bool = True,
    _user=Depends(get_current_user),
    db: Session = Depends(get_offline_db),
):
    data = sync_fund_nav_snapshot(db, full=bool(full), rebuild_index=bool(rebuild_index))
    return success_response(data=data, message="ok" if data.get("ok") else "failed")
