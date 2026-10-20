"""工作台 SQLite 存储层：人工池子（watchlist）+ 选股规则版本（rules）。

stdlib sqlite3，单文件库；表结构在构造时自动建齐（幂等）。
"""

from __future__ import annotations

import json
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
CREATE TABLE IF NOT EXISTS rules (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    name       TEXT NOT NULL,
    version    INTEGER NOT NULL,
    spec       TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE(name, version)
);
"""


class Store:
    """人工池子 + 规则版本持久化。个人单机用，单连接 + 写后 commit。"""

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

    # ---- 选股规则：同名再存 version+1，历史版本行保留（旧回测可追溯） ----

    def save_rule(self, name: str, spec: dict) -> int:
        """保存规则，返回新版本号（同名从 1 起自增）。"""
        row = self._conn.execute(
            "SELECT COALESCE(MAX(version), 0) AS v FROM rules WHERE name = ?", (name,)
        ).fetchone()
        version = row["v"] + 1
        self._conn.execute(
            "INSERT INTO rules(name, version, spec, created_at) VALUES(?, ?, ?, ?)",
            (name, version, json.dumps(spec, ensure_ascii=False),
             datetime.now().isoformat(timespec="seconds")),
        )
        self._conn.commit()
        return version

    @staticmethod
    def _rule_row(r) -> dict[str, Any]:
        out = dict(r)
        out["spec"] = json.loads(out["spec"])
        return out

    def list_rules(self) -> list[dict[str, Any]]:
        """规则清单：每个名字只出最新版本（历史版本仍在表里）。"""
        rows = self._conn.execute(
            "SELECT r.id, r.name, r.version, r.spec, r.created_at FROM rules r "
            "JOIN (SELECT name, MAX(version) AS v FROM rules GROUP BY name) t "
            "ON r.name = t.name AND r.version = t.v ORDER BY r.created_at",
        ).fetchall()
        return [self._rule_row(r) for r in rows]

    def get_rule(self, name: str) -> dict[str, Any] | None:
        row = self._conn.execute(
            "SELECT id, name, version, spec, created_at FROM rules "
            "WHERE name = ? ORDER BY version DESC LIMIT 1", (name,),
        ).fetchone()
        return self._rule_row(row) if row else None

    def delete_rule(self, name: str) -> bool:
        """删除规则的全部版本。"""
        cur = self._conn.execute("DELETE FROM rules WHERE name = ?", (name,))
        self._conn.commit()
        return cur.rowcount > 0


# 兼容旧名：watchlist CRUD 语义不变
WorkbenchStore = Store


__all__ = ["Store", "WorkbenchStore"]
