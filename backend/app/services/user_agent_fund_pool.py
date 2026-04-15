"""用户 MAFB 自选基金池：仅存储 6 位代码，展示时从 fund_catalog 解析。"""

from __future__ import annotations

import re
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agent.fund_catalog import get_fund_by_code
from app.modules.user.models import UserAgentFund


def _norm_codes(codes: list[str]) -> list[str]:
    out: list[str] = []
    for c in codes:
        s = (c or "").strip()
        if re.fullmatch(r"\d{6}", s) and s not in out:
            out.append(s)
    return out


def list_pool_codes(db: Session, user_id: int) -> list[str]:
    rows = db.scalars(
        select(UserAgentFund.fund_code)
        .where(UserAgentFund.user_id == user_id)
        .order_by(UserAgentFund.created_at.desc())
    ).all()
    return [str(c) for c in rows]


def list_pool_funds(db: Session, user_id: int) -> tuple[list[dict[str, Any]], int]:
    codes = list_pool_codes(db, user_id)
    items: list[dict[str, Any]] = []
    for code in codes:
        row = get_fund_by_code(code, include_live=False)
        if row:
            items.append(row)
    return items, len(items)


def add_to_pool(db: Session, user_id: int, codes: list[str]) -> int:
    """返回新插入条数（已存在的代码跳过）。"""
    added = 0
    for code in _norm_codes(codes):
        exists = db.scalar(
            select(UserAgentFund.id).where(UserAgentFund.user_id == user_id, UserAgentFund.fund_code == code)
        )
        if exists:
            continue
        db.add(UserAgentFund(user_id=user_id, fund_code=code))
        added += 1
    db.commit()
    return added


def remove_from_pool(db: Session, user_id: int, fund_code: str) -> bool:
    code = fund_code.strip()
    if not re.fullmatch(r"\d{6}", code):
        return False
    row = db.scalar(
        select(UserAgentFund).where(UserAgentFund.user_id == user_id, UserAgentFund.fund_code == code)
    )
    if row is None:
        return False
    db.delete(row)
    db.commit()
    return True
