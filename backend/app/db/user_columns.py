"""为 users 表补充出生时段字段（SQLite / MySQL 兼容，幂等）。"""

from __future__ import annotations

from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine


def ensure_user_birth_time_slot_column(engine: Engine) -> None:
    insp = inspect(engine)
    if "users" not in insp.get_table_names():
        return
    cols = {c["name"] for c in insp.get_columns("users")}
    if "birth_time_slot" in cols:
        return
    with engine.begin() as conn:
        conn.execute(text("ALTER TABLE users ADD COLUMN birth_time_slot VARCHAR(16)"))
