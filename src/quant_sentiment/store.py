"""选股工作台 SQLite 存储层：人工池子（watchlist）。

stdlib sqlite3，单文件库；表结构在构造时自动建齐（幂等）。
"""

from __future__ import annotations

import os
import sqlite3
from datetime import datetime
from typing import Any

_SCHEMA = """
CREATE TABLE IF NOT EXISTS watchlist (
    symbol   TEXT PRIMARY KEY,
    name     TEXT NOT NULL DEFAULT '',
    note     TEXT NOT NULL DEFAULT '',
    added_at TEXT NOT NULL
);
"""


class Store:
    """人工池子持久化。个人单机用，单连接 + 写后 commit。"""

    def __init__(self, db_path: str) -> None:
        parent = os.path.dirname(db_path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(_SCHEMA)
        # 旧库迁移：2.x 的 watchlist 表没有 note 列
        cols = [r[1] for r in self._conn.execute("PRAGMA table_info(watchlist)")]
        if "note" not in cols:
            self._conn.execute("ALTER TABLE watchlist ADD COLUMN note TEXT NOT NULL DEFAULT ''")
        self._conn.commit()

    def upsert(self, symbol: str, name: str = "", note: str = "") -> None:
        self._conn.execute(
            "INSERT INTO watchlist(symbol, name, note, added_at) VALUES(?, ?, ?, ?) "
            "ON CONFLICT(symbol) DO UPDATE SET name = excluded.name, note = excluded.note",
            (symbol, name, note, datetime.now().isoformat(timespec="seconds")),
        )
        self._conn.commit()

    def remove(self, symbol: str) -> bool:
        cur = self._conn.execute("DELETE FROM watchlist WHERE symbol = ?", (symbol,))
        self._conn.commit()
        return cur.rowcount > 0

    def list_all(self) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            "SELECT symbol, name, note, added_at FROM watchlist ORDER BY rowid"
        ).fetchall()
        return [dict(r) for r in rows]


# 兼容旧名：watchlist CRUD 语义不变
WorkbenchStore = Store


__all__ = ["Store", "WorkbenchStore"]
