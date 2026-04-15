"""清理旧版本遗留表结构（当前模型已移除 Comment）。"""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.engine import Engine


def drop_legacy_comments_table(engine: Engine) -> None:
    """删除遗留的 comments 表（若存在）。SQLite / MySQL 等均支持 IF EXISTS。"""
    with engine.begin() as conn:
        conn.execute(text("DROP TABLE IF EXISTS comments"))
